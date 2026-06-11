"""
utils/comment_utils.py — TIP ESG Platform · Comment & Verification Utilities
==============================================================================
All functions for the field-level change-comment workflow:
  - Saving comments typed in the template table (client side)
  - Loading comments for display (both client and DSS views)
  - Updating comment status from the Verification Queue (Accept/Seen/Reject)
  - Writing comment state to the master CSV change_comment column
  - Creating version parquet snapshots for every comment event

On Azure migration: replace CSV read/write with Azure SQL INSERT/UPDATE,
and parquet writes with Blob Storage uploads.
"""

from __future__ import annotations
from pathlib import Path
import csv
import logging

import data_loader as dl

logger = logging.getLogger(__name__)

# ── CSV schema ────────────────────────────────────────────────────────────────
_COMMENTS_PATH = Path("data_storage/field_comments.csv")
_COMMENT_COLS  = [
    "Company", "Year", "FieldKey", "FieldLabel",
    "OldValue", "NewValue", "Reason",
    "SubmittedAt", "Status", "ApprovedBy", "ApprovedAt",
]


# ── Read helpers ──────────────────────────────────────────────────────────────

def load_comments(company: str = None, status: str = None) -> list[dict]:
    """Return all comment records, optionally filtered by company and/or status."""
    if not _COMMENTS_PATH.exists():
        return []
    try:
        with open(_COMMENTS_PATH, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        if company:
            rows = [r for r in rows if r["Company"] == company]
        if status:
            rows = [r for r in rows if r["Status"] == status]
        return rows
    except Exception as e:
        logger.warning("[comment_utils] load_comments error: %s", e)
        return []


def get_approved_comments(company: str, year: int) -> dict:
    """Return {field_key: reason} for all Approved comments for company+year."""
    return {r["FieldKey"]: r["Reason"]
            for r in load_comments(company, "Approved")
            if str(r["Year"]) == str(year)}


def get_all_active_comments(company: str, year: int) -> dict:
    """
    Return {field_key: (status, display_text)} for every non-Accepted comment.
    Both client (My Records) and DSS (Company Data) use this so both sides
    always see the same comment state with the correct status prefix.

    Status → display:
      Pending  → raw reason text (red bold in template)
      Seen     → "⏳ reason"  (amber in template)
      Rejected → "⚠ reason"  (orange in template)
      Accepted → not included (comment gone from both templates)
    """
    result = {}
    for r in load_comments(company=company):
        if str(r["Year"]) != str(year):
            continue
        st_ = r.get("Status", "Pending")
        rsn = r.get("Reason", "")
        if st_ == "Accepted":
            continue
        elif st_ == "Pending":
            result[r["FieldKey"]] = ("Pending",  rsn)
        elif st_ == "Seen":
            result[r["FieldKey"]] = ("Seen",     f"⏳ {rsn}")
        elif st_ == "Rejected":
            result[r["FieldKey"]] = ("Rejected",  f"⚠ {rsn}")
        elif st_ == "Approved":
            result[r["FieldKey"]] = ("Approved",  rsn)
    return result


# ── Write helpers ─────────────────────────────────────────────────────────────

def save_change_comment(company: str, year, field_key: str, field_label: str,
                         old_val, new_val, reason: str) -> None:
    """
    Save a Pending comment to field_comments.csv.
    Replaces any existing entry for the same company+year+field (any status).
    Also writes immediately to master CSV and creates a version parquet.
    """
    from datetime import datetime
    _COMMENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    if _COMMENTS_PATH.exists():
        with open(_COMMENTS_PATH, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    # Replace existing entry for same co+yr+field
    rows = [r for r in rows if not (
        r["Company"] == company and str(r["Year"]) == str(year)
        and r["FieldKey"] == field_key)]
    rows.append({
        "Company": company, "Year": str(year), "FieldKey": field_key,
        "FieldLabel": field_label, "OldValue": str(old_val),
        "NewValue": str(new_val), "Reason": reason,
        "SubmittedAt": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "Status": "Pending", "ApprovedBy": "", "ApprovedAt": "",
    })
    with open(_COMMENTS_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=_COMMENT_COLS)
        w.writeheader(); w.writerows(rows)
    try: update_master_comment_cell(company, year, field_key, reason)
    except Exception: pass
    try: save_comment_version(company, year, field_key, reason, "Pending", "Client")
    except Exception: pass


def update_comment_status(company: str, year, field_key: str,
                           status: str, approved_by: str = "") -> None:
    """
    Update a comment's status from the Verification Queue.

    Accepted → removes record entirely; clears master CSV change_comment cell.
               Comment disappears from both My Records and Company Data.
    Seen     → keeps record; prepends ⏳ in master CSV cell.
               Visible on both templates with timer symbol.
    Rejected → keeps record; prepends ⚠ in master CSV cell.
               Visible on both templates with danger symbol.
    """
    from datetime import datetime
    if not _COMMENTS_PATH.exists():
        return
    with open(_COMMENTS_PATH, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    reason_text = next((r.get("Reason", "") for r in rows
                        if r["Company"] == company and str(r["Year"]) == str(year)
                        and r["FieldKey"] == field_key), "")
    if status == "Accepted":
        rows = [r for r in rows if not (
            r["Company"] == company and str(r["Year"]) == str(year)
            and r["FieldKey"] == field_key)]
        update_master_comment_cell(company, year, field_key, "")
    else:
        prefix = {"Seen": "⏳ ", "Rejected": "⚠ "}.get(status, "")
        for r in rows:
            if (r["Company"] == company and str(r["Year"]) == str(year)
                    and r["FieldKey"] == field_key):
                r["Status"]     = status
                r["ApprovedBy"] = approved_by
                r["ApprovedAt"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        update_master_comment_cell(company, year, field_key, prefix + reason_text)
    with open(_COMMENTS_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=_COMMENT_COLS)
        w.writeheader(); w.writerows(rows)
    save_comment_version(company, year, field_key, reason_text, status, approved_by)


def delete_comment(company: str, year, field_key: str) -> None:
    """Remove comment from CSV + master CSV (triggered when client clears cell)."""
    if not _COMMENTS_PATH.exists():
        return
    with open(_COMMENTS_PATH, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    rows = [r for r in rows if not (
        r["Company"] == company and str(r["Year"]) == str(year)
        and r["FieldKey"] == field_key)]
    with open(_COMMENTS_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=_COMMENT_COLS)
        w.writeheader(); w.writerows(rows)
    update_master_comment_cell(company, year, field_key, "")


def update_master_comment_cell(company: str, year, field_key: str,
                                value: str) -> None:
    """
    Write value into the change_comment column of the master CSV for
    the company+year row, replacing only the entry for field_key.
    Empty value clears that field's entry (on Accept or delete).
    """
    try:
        import pandas as _pd
        _ecands = dl._get_csv_candidates()
        csv_p = next((pp for pp in _ecands if pp.exists()
                      and pp.name.startswith("ESG_MASTER_WIDE_ALL_COMPANIES_")), None)
        if not csv_p:
            return
        mdf = _pd.read_csv(csv_p)
        if "change_comment" not in mdf.columns:
            mdf["change_comment"] = ""
        mask = ((mdf["Company"] == company)
                & (mdf["Year"].astype(str) == str(year)))
        if not mask.any():
            return
        existing = str(mdf.loc[mask, "change_comment"].fillna("").iloc[0])
        parts = [p for p in existing.split(" | ")
                 if not p.startswith(field_key + ":") and p.strip()]
        if value:
            parts.append(f"{field_key}: {value}")
        mdf.loc[mask, "change_comment"] = " | ".join(parts)
        mdf.to_csv(csv_p, index=False)
    except Exception as e:
        logger.warning("[comment_utils] update_master_comment_cell: %s", e)


def save_comment_version(company: str, year, field_key: str, reason: str,
                          status: str, actor: str) -> None:
    """
    Save a lightweight version parquet recording a single comment event.
    Stored in data_storage/versions/{Company}/ for audit trail.
    On Azure migration: replace with INSERT INTO versions table + Blob upload.
    """
    try:
        import pandas as _pd
        from datetime import datetime as _dt
        _vdir = Path("data_storage/versions") / company.replace(" ", "_")
        _vdir.mkdir(parents=True, exist_ok=True)
        ts = _dt.now().strftime("%Y%m%d_%H%M%S")
        _pd.DataFrame([{
            "Company": company, "Year": year, "FieldKey": field_key,
            "Reason": reason, "Status": status, "Actor": actor,
            "Timestamp": _dt.now().strftime("%Y-%m-%d %H:%M:%S"),
        }]).to_parquet(
            _vdir / f"{company.replace(' ','_')}_{year}_cmt_{status}_{ts}.parquet",
            index=False)
    except Exception as e:
        logger.warning("[comment_utils] save_comment_version: %s", e)