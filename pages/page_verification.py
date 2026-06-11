"""
pages/page_verification.py — Verification Queue: Accept / Seen / Reject pending comments.
Globals are read from state.py (populated by app.py at startup).
"""
from __future__ import annotations
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from pathlib import Path
from datetime import datetime, date

import html as _html
import config as cfg
import data_loader as dl
import state
from utils.helpers import (
    get_hist_outputs, _get_fresh_hist, get_current_outputs,
    _load_company_year_outputs, _compute_industry_scores,
    _compute_kpi_improvement, _chart_key,
    _compute_completeness, _compute_readiness_score,
    _dss_company_selector,
)
from utils.data_utils import (
    _load_supplementary, _save_supplementary, _build_master_row,
    _save_version_parquet, _write_verification_status,
    _save_submission_to_csv, _save_electricity_to_master,
    _sync_consolidate_excel, _sync_company_member_files,
    _elec_col,
)
from utils.comment_utils import (
    load_comments as _load_comments,
    save_change_comment as _save_change_comment,
    update_comment_status as _update_comment_status,
    get_approved_comments as _get_approved_comments,
    get_all_active_comments as _get_all_active_comments,
    update_master_comment_cell as _update_master_comment_cell,
    delete_comment as _delete_comment,
    save_comment_version as _save_comment_version,
)
from ui_components import chart_layout_defaults, apply_chart_animation
import logging
_log = logging.getLogger("esg_app")
from formula_engine import (
    TemplateInputs, calculate, validate_submission,
    get_benchmarks, build_template_dataframe, fmt_num,
    yoy_change, ValidationFlag, BenchmarkResult,
)
from ui_components import (
    inject_global_css, kpi_card_html, skeleton_card_html, skeleton_chart_html,
    status_chip_html, section_header_html, empty_state_html, co_card_html,
    apply_chart_animation, chart_layout_defaults, sparkline_html,
    GREEN, AMBER, RED, NAVY, BG, BORDER, TEXT, MUTED,
    CAT_CO2, CAT_ENERGY, CAT_WATER, CAT_WASTE, CAT_RENEW,
)
from components.render_template_table import render_template_table
from components.render_electricity_tab import render_electricity_tab
from components.render_waste_tab import render_waste_tab
from components.render_people_tab import _render_people_governance_tab
from components.render_qualitative_tab import render_qualitative_tab
from components.render_conversion_tab import render_conversion_tab


def page_verification():
    if not st.session_state.is_dss:
        st.error("This section is restricted to dss+ analysts and managers."); return

    st.markdown("## Data Verification")
    st.caption("Select any company and reporting year from the consolidated dataset to review.")

    sel_co, sel_yr, inp, out, prev_inp, prev_out, hist = _dss_company_selector("verif")
    st.divider()

    # -- Real flags from formula_engine ----------------------------------------
    flags = validate_submission(inp, out, prev_out, threshold=20.0)

    # -- Also compute YoY field-level flags from the data ----------------------
    extra_flags = []
    yoy_fields = [
        ("nat_gas",              "Natural Gas"),
        ("renew_elec_purchased", "Renewable Electricity"),
        ("nonrenew_elec_purchased","Non-Renewable Electricity"),
        ("fuel_oil_heavy_a",     "Fuel Oil"),
        ("coal_sub",             "Coal"),
        ("water_withdrawals",    "Water Withdrawals"),
        ("production",           "Production"),
    ]
    from formula_engine import ValidationFlag
    for field, label in yoy_fields:
        cur  = getattr(inp,      field, 0) or 0
        prev = getattr(prev_inp, field, 0) or 0
        if prev > 0 and cur > 0:
            pct = (cur - prev) / abs(prev) * 100
            if abs(pct) > 20:
                direction = "increase" if pct > 0 else "decrease"
                extra_flags.append(ValidationFlag(
                    severity="warning",
                    message=f"{label} — >{20}% YoY {direction} ({pct:+.1f}%)",
                    detail=(f"{label}: {prev:,.0f} → {cur:,.0f} "
                            f"({'↑' if pct>0 else '↓'}{abs(pct):.1f}%). "
                            f"Verify with company documentation.")
                ))

    all_flags = flags + extra_flags

    # -- Completeness + summary metrics ----------------------------------------
    completeness = _compute_completeness(inp, out)
    avg_complete  = int(sum(completeness.values()) / len(completeness))
    n_err  = sum(1 for f in all_flags if f.severity == "error")
    n_warn = sum(1 for f in all_flags if f.severity == "warning")
    score, label = _compute_readiness_score(completeness, all_flags)

    c1,c2,c3,c4,c5 = st.columns(5)
    c1.metric("Company",      sel_co)
    c2.metric("Year",         str(sel_yr))
    c3.metric("Status",       "Ready" if score >= 90 else "Pending review")
    c4.metric("Completeness", f"{avg_complete}%")
    c5.metric("Open flags",   f"{n_warn} warning{'s' if n_warn!=1 else ''} · {n_err} error{'s' if n_err!=1 else ''}")
    st.divider()

    # -- Flag cards ------------------------------------------------------------
    if not st.session_state.get("flags_resolved_real"):
        st.session_state["flags_resolved_real"] = set()

    resolved_set = st.session_state["flags_resolved_real"]

    # ── Pending Change-Request Comments from clients ───────────────────────────
    pending_comments = _load_comments(status="Pending")
    if pending_comments:
        st.markdown(f"""<div style="border-left:4px solid {AMBER};padding:6px 12px;
          background:#FFFBEB;border-radius:4px;margin-bottom:12px">
          <b>🔔 {len(pending_comments)} pending change request(s) from clients</b>
          <div style="font-size:12px;color:{MUTED}">Review and approve/reject below. Approved comments will appear in red in the template.</div>
        </div>""", unsafe_allow_html=True)
        for idx_c, cmt in enumerate(pending_comments):
            with st.expander(
                f"🏢 {cmt['Company']} · {cmt['Year']} · submitted {cmt['SubmittedAt']}",
                expanded=True
            ):
                cc1, cc2 = st.columns([3, 1])
                with cc1:
                    st.markdown(f"""
                    **Field:** {cmt['FieldLabel']}
                    **Reason given:** {cmt['Reason']}
                    """)
                with cc2:
                    _analyst = st.session_state.get("username", "DSS Analyst")
                    _ba, _bs, _br = st.columns(3)
                    if _ba.button("✅ Accept", key=f"accept_{idx_c}",
                                  use_container_width=True, type="primary",
                                  help="Comment disappears from both templates"):
                        _update_comment_status(cmt['Company'], int(cmt['Year']),
                                               cmt['FieldKey'], "Accepted", approved_by=_analyst)
                        for _ck in list(st.session_state.keys()):
                            if _ck.startswith(f"tbl_editor_{cmt['Company']}_{cmt['Year']}"):
                                del st.session_state[_ck]
                        st.success("✅ Accepted — comment removed from both templates.")
                        st.rerun()
                    if _bs.button("⏳ Seen", key=f"seen_{idx_c}",
                                  use_container_width=True,
                                  help="⏳ stays on both templates"):
                        _update_comment_status(cmt['Company'], int(cmt['Year']),
                                               cmt['FieldKey'], "Seen", approved_by=_analyst)
                        for _ck in list(st.session_state.keys()):
                            if _ck.startswith(f"tbl_editor_{cmt['Company']}_{cmt['Year']}"):
                                del st.session_state[_ck]
                        st.info("⏳ Seen — ⏳ symbol now visible on both templates.")
                        st.rerun()
                    if _br.button("⚠ Reject", key=f"reject_{idx_c}",
                                  use_container_width=True,
                                  help="⚠ stays on both templates"):
                        _update_comment_status(cmt['Company'], int(cmt['Year']),
                                               cmt['FieldKey'], "Rejected", approved_by=_analyst)
                        for _ck in list(st.session_state.keys()):
                            if _ck.startswith(f"tbl_editor_{cmt['Company']}_{cmt['Year']}"):
                                del st.session_state[_ck]
                        st.warning("⚠ Rejected — ⚠ symbol now visible on both templates.")
                        st.rerun()
        st.divider()

    for i, flag in enumerate(all_flags):
        flag_id  = f"flag_{sel_co}_{sel_yr}_{i}"
        resolved = flag_id in resolved_set

        sev = "ok" if resolved else flag.severity
        icon_map  = {"ok":"✓", "warning":"!", "error":"✕", "warn":"!"}
        color_map = {"ok":"fc-ok fi-ok", "warning":"fc-warn fi-warn",
                     "error":"fc-error fi-error", "warn":"fc-warn fi-warn"}
        fc, fi = color_map.get(sev, "fc-ok fi-ok").split()
        icon   = icon_map.get(sev, "OK")
        title  = flag.message + (" — Approved" if resolved else "")
        detail = flag.detail

        # H3 FIX: escape flag content before injecting into HTML
        st.markdown(f"""<div class="flag-card {fc}">
          <div class="fc-icon {fi}">{_html.escape(icon)}</div>
          <div><div class="fc-title">{_html.escape(title)}</div>
               <div class="fc-detail">{_html.escape(detail)}</div></div>
        </div>""", unsafe_allow_html=True)

        if not resolved and flag.severity in ("warning","error"):
            cols = st.columns([6,1,1])
            with cols[1]:
                if st.button("Query", key=f"q_{flag_id}"):
                    st.toast(f"Query logged: {flag.message[:50]}...")
            with cols[2]:
                if flag.severity == "warning":
                    if st.button("Accept", key=f"a_{flag_id}", type="primary"):
                        resolved_set.add(flag_id)
                        st.session_state["flags_resolved_real"] = resolved_set
                        st.rerun()
                else:
                    if st.button("Send Back", key=f"sb_{flag_id}"):
                        st.toast(f"Submission returned to {sel_co} with error details.")

    st.divider()
    col_approve, col_flag, col_export, _ = st.columns([1.5, 1.5, 1.5, 1])
    with col_approve:
        warn_ids = [f"flag_{sel_co}_{sel_yr}_{i}"
                    for i, f in enumerate(all_flags) if f.severity == "warning"]
        if st.button("Verify & Approve", type="primary"):
            resolved_set.update(warn_ids)
            st.session_state["flags_resolved_real"] = resolved_set
            # Persist verification status so client's submission bar reflects it
            _write_verification_status(sel_co, sel_yr, "Verified")
            st.success(f"✅ {sel_co} {sel_yr} marked as Verified")
            st.rerun()
    with col_flag:
        if st.button("Mark as Pending", key="mark_pending_btn"):
            _write_verification_status(sel_co, sel_yr, "Pending")
            st.info(f"Marked {sel_co} {sel_yr} as Pending Review")
            st.rerun()
    with col_export:
        if st.button("Export Flag Report"):
            rows = [{"Flag": f.message, "Severity": f.severity, "Detail": f.detail,
                     "Status": "Resolved" if f"flag_{sel_co}_{sel_yr}_{i}" in resolved_set else "Open"}
                    for i, f in enumerate(all_flags)]
            export_df = pd.DataFrame(rows)
            st.download_button(
                "Download CSV", data=export_df.to_csv(index=False).encode(),
                file_name=f"flags_{sel_co.replace(' ','_')}_{sel_yr}.csv",
                mime="text/csv", key="dl_flags"
            )