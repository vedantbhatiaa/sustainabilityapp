"""
pages/page_my_records.py — My Records: full template table with Submit & Save.
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
import html as _html
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


def page_my_records():
    """
    My Records — view and save all historical KPI data.
    Shows the full template table with all 5 sheets.
    Has Submit & Save button top-right.
    Versioning (parquet) + master CSV sync on every save.
    CLIENT SIDE ONLY.
    """
    company   = st.session_state.user_company
    comp_hist = dl.get_company_hist(state.CONSOLIDATED_DF, company)
    all_yrs   = sorted(dl.get_years(state.CONSOLIDATED_DF, company) or [state.CURR_YEAR], reverse=True)

    # ── Header: title + year dropdown + Save button ───────────────────────────
    h_title, h_yr, h_btn = st.columns([3, 1, 1])
    with h_title:
        st.markdown(section_header_html(
            "My Records",
            f"{company} · Historical KPI data",
        ), unsafe_allow_html=True)
    with h_yr:
        _def_yr  = st.session_state.get("reporting_year", all_yrs[0] if all_yrs else state.CURR_YEAR)
        _def_idx = all_yrs.index(_def_yr) if _def_yr in all_yrs else 0
        sel_yr = st.selectbox("Year", all_yrs, index=_def_idx, key="myrec_year",
                               label_visibility="collapsed")
    with h_btn:
        save_clicked = st.button("💾  Submit & Save", type="primary",
                                  use_container_width=True, key="myrec_save_btn")

    # Show message from Submit Data redirect
    if "_last_save_msg" in st.session_state:
        st.success(f"✅ {st.session_state.pop('_last_save_msg')}")

    # ── Load data for selected year — use in-memory state.CONSOLIDATED_DF  ──────────
    # state.CONSOLIDATED_DF is updated in-memory by _save_submission_to_csv so it
    # always reflects the latest saved data without needing a disk re-read.
    st.session_state.reporting_company  = company
    st.session_state.reporting_year     = sel_yr

    fresh_hist = dl.get_company_hist(state.CONSOLIDATED_DF, company)
    step_data  = dl.get_step_data(fresh_hist, sel_yr) if fresh_hist else {}
    valid_flds = {f.name for f in TemplateInputs.__dataclass_fields__.values()}
    clean      = {k: v for k, v in step_data.items() if k in valid_flds}

    if clean:
        for k, v in clean.items():
            st.session_state[k] = v
        inp = TemplateInputs(company=company, year=sel_yr, **clean)
        out = calculate(inp)
    else:
        inp = TemplateInputs(company=company, year=sel_yr)
        out = calculate(inp)

    # Keep both step_data dict AND _codata_inp in sync
    st.session_state.step_data          = {fld: getattr(inp, fld) for fld in state.VALID_TEMPLATE_FIELDS}
    st.session_state["_codata_inp"]     = inp
    st.session_state["_codata_out"]     = out
    st.session_state.template_done      = True
    st.session_state.company_setup_done = True
    st.session_state.step               = 6

    # ── Save & sync on button click ───────────────────────────────────────────
    if save_clicked:
        msg = _save_submission_to_csv(inp, out)   # updates globals in-place
        st.success(f"✅ {msg}")
        st.rerun()   # force re-render so table shows updated values

    # ── All 5 template sheets as tabs ─────────────────────────────────────────
    tab_main, tab_elec, tab_waste, tab_people_tpl, tab_qual, tab_conv = st.tabs([
        "Main Data Input",
        "Electricity by Country",
        "Waste",
        "People & Governance",
        "Qualitative Data",
        "Conversion Tables",
    ])
    with tab_main: render_template_table()
    with tab_elec: render_electricity_tab()
    with tab_waste: render_waste_tab()
    with tab_people_tpl: _render_people_governance_tab()
    with tab_qual: render_qualitative_tab()
    with tab_conv: render_conversion_tab()