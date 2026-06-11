"""
components/render_people_tab.py — People & Governance section (H&S, Diversity, SBT).
All globals are read from state.py which app.py keeps up-to-date.
"""
from __future__ import annotations
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from pathlib import Path
from datetime import datetime, date

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
    get_benchmarks, fmt_num, yoy_change, BenchmarkResult,
)
from ui_components import (
    kpi_card_html, section_header_html, chart_layout_defaults,
    apply_chart_animation, GREEN, AMBER, RED, NAVY, BG, BORDER, TEXT, MUTED,
    CAT_CO2, CAT_ENERGY, CAT_WATER, CAT_WASTE, CAT_RENEW,
)


def _render_people_governance_tab():
    """
    People & Governance tab shown in My Records and Company Data.
    Reads live data from master CSV (promoted from supplementary) and displays
    as a structured table with all H&S, Diversity, and SBT fields across all years.
    """
    company  = st.session_state.get("reporting_company") or st.session_state.get("user_company") or ""
    rep_year = st.session_state.get("reporting_year", state.CURR_YEAR)
    hist     = get_hist_outputs()

    st.markdown(f"""<div style="border-left:4px solid #8B5CF6;padding:6px 12px;margin-bottom:12px">
      <b style="font-size:15px;color:#2a2825">People & Governance</b>
      <div style="font-size:11px;color:#6f7882">Health & Safety · Diversity & Inclusion · Science-Based Targets</div>
    </div>""", unsafe_allow_html=True)
    st.caption("Data entered via Submit Data → Sections 7–9. Submit new year to update.")

    # Row definitions: (label, unit, supp_key, master_col, is_section)
    PG_ROWS = [
        # H&S
        (True,  "Health & Safety",                  None,    None,       None),
        (False, "Total sites (H&S)",                "no.",   "hs_total_sites", None),
        (False, "Externally audited H&S sites",     "no.",   "hs_external_audit", "HS External Audit Sites"),
        (False, "— External audit coverage",        "%",     "hs_ext_pct",        "HS External Audit %"),
        (False, "Internally audited H&S sites",     "no.",   "hs_internal_audit", "HS Internal Audit Sites"),
        (False, "— Internal audit coverage",        "%",     "hs_int_pct",        "HS Internal Audit %"),
        # Diversity
        (True,  "Diversity & Inclusion",            None,    None,       None),
        (False, "Total employees",                  "no.",   "total_employees",   "Total Employees"),
        (False, "Female employees",                 "no.",   "female_employees",  "Female Employees"),
        (False, "— % Female employees",             "%",     "fem_emp_pct",       "Female Employees %"),
        (False, "Board of Directors (total)",       "no.",   "board_total",       "Board Total"),
        (False, "Female Board members",             "no.",   "female_board",      "Female Board"),
        (False, "— % Female Board",                 "%",     "fem_bod_pct",       "Female Board %"),
        # SBT
        (True,  "Science-Based Targets",            None,    None,       None),
        (False, "Total with SBT",                   "no.",   "sbt_total",         "SBT Total"),
        (False, "Validated",                        "no.",   "sbt_validated",     "SBT Validated"),
        (False, "Committed",                        "no.",   "sbt_committed",     "SBT Committed"),
        (False, "Non-committed",                    "no.",   "sbt_non_committed", "SBT Non-Committed"),
    ]

    def _get_supp_val(yr, supp_key, master_col, yr_supp, hi):
        """Read from master CSV first (post-migration), fall back to supplementary."""
        if master_col and not state.CONSOLIDATED_DF.empty and "Company" in state.CONSOLIDATED_DF.columns:
            mdf = state.CONSOLIDATED_DF[
                (state.CONSOLIDATED_DF["Company"] == company) &
                (state.CONSOLIDATED_DF["Year"] == yr)
            ]
            if not mdf.empty and master_col in mdf.columns:
                v = mdf[master_col].values[0]
                if pd.notna(v): return float(v)
        # Fall back to supplementary file
        return float(yr_supp.get(supp_key, 0) or 0)

    table_data = []
    yr_cols    = [str(yr) for yr, *_ in hist]

    for is_sec, label, unit, supp_key, master_col in PG_ROWS:
        row = {"Indicator": f"▸ {label}" if is_sec else ("  " + label), "Unit": unit or ""}
        if is_sec:
            for yc in yr_cols: row[yc] = ""
            row["YoY %"] = ""
            table_data.append(row); continue

        vals_num = []
        for yr, hi, ho in hist:
            yr_supp = _load_supplementary(company, yr)
            ts  = int(hi.total_sites) or 1   # total sites for % calc

            if supp_key == "hs_total_sites":
                v = _get_supp_val(yr, "hs_external_audit", "HS External Audit Sites", yr_supp, hi) or ts
            elif supp_key == "hs_ext_pct":
                ext = _get_supp_val(yr, "hs_external_audit", "HS External Audit Sites", yr_supp, hi)
                v = round(ext / max(ts, 1) * 100, 1)
            elif supp_key == "hs_int_pct":
                intr = _get_supp_val(yr, "hs_internal_audit", "HS Internal Audit Sites", yr_supp, hi)
                v = round(intr / max(ts, 1) * 100, 1)
            elif supp_key == "fem_emp_pct":
                emp = _get_supp_val(yr, "total_employees", "Total Employees", yr_supp, hi)
                fem = _get_supp_val(yr, "female_employees", "Female Employees", yr_supp, hi)
                v = round(fem / max(emp, 1) * 100, 1)
            elif supp_key == "fem_bod_pct":
                bod = _get_supp_val(yr, "board_total", "Board Total", yr_supp, hi)
                fem = _get_supp_val(yr, "female_board", "Female Board", yr_supp, hi)
                v = round(fem / max(bod, 1) * 100, 1)
            else:
                v = _get_supp_val(yr, supp_key, master_col, yr_supp, hi)

            try:
                fv = float(v)
                if unit == "%":
                    row[str(yr)] = f"{fv:.1f}%"
                elif fv == int(fv):
                    row[str(yr)] = f"{int(fv):,}" if fv else "—"
                else:
                    row[str(yr)] = f"{fv:,.1f}"
                if fv: vals_num.append(fv)
            except:
                row[str(yr)] = "—"

        row["YoY %"] = "—"
        if len(vals_num) >= 2:
            pv, lv = vals_num[-2], vals_num[-1]
            if pv:
                row["YoY %"] = f"{(lv-pv)/abs(pv)*100:+.1f}%"

        table_data.append(row)

    if table_data:
        df_pg = pd.DataFrame(table_data)
        cols  = ["Indicator","Unit"] + yr_cols + ["YoY %"]
        df_pg = df_pg.reindex(columns=[c for c in cols if c in df_pg.columns])
        # Read approved comments for the comment column
        _acomments = _get_approved_comments(company, rep_year)
        if _acomments:
            df_pg["Comments"] = df_pg["Indicator"].map(
                lambda label: _acomments.get(label.strip(), ""))
            df_pg["Comments"] = df_pg["Comments"].apply(
                lambda v: f"🔴 {v}" if v else "")

        st.dataframe(
            df_pg, use_container_width=True, hide_index=True,
            column_config={
                "Indicator": st.column_config.TextColumn("Indicator", width=260),
                "Unit":      st.column_config.TextColumn("Unit",      width=70),
                "YoY %":     st.column_config.TextColumn("YoY %",     width=80),
            },
            height=min(38 + len(table_data) * 35, 740),
        )
    else:
        st.info("No People & Governance data available. Submit data via Sections 7–9 in Submit Data.")