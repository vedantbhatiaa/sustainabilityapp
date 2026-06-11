"""
pages/page_company_data.py — DSS full KPI template view for any company+year.
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


def page_company_data():
    """
    DSS+ Company Data — full KPI template table for a selected company.
    Accessed from Portfolio 'Open Template' button or directly from nav.
    """
    st.markdown(section_header_html(
        "Company Data",
        "Full KPI template for selected company · All historical years",
    ), unsafe_allow_html=True)

    companies_in_db = dl.get_companies(state.CONSOLIDATED_DF) or state.COMPANIES

    # Pre-select company from portfolio if set
    pre_co = st.session_state.pop("portfolio_company", None)
    default_co = (pre_co
                  or st.session_state.get("reporting_company")
                  or companies_in_db[0])
    if default_co not in companies_in_db:
        default_co = companies_in_db[0]

    col_co, col_yr, _ = st.columns([2, 1, 3])
    with col_co:
        sel_co = st.selectbox(
            "Company", options=companies_in_db,
            index=companies_in_db.index(default_co),
            key="codata_company"
        )
    with col_yr:
        avail_years = dl.get_years(state.CONSOLIDATED_DF, sel_co) or [state.CURR_YEAR]
        sel_yr = st.selectbox(
            "Year", options=sorted(avail_years, reverse=True),
            key="codata_year"
        )

    # Set session state so all render_*_tab() functions read the right data
    st.session_state.reporting_company  = sel_co
    st.session_state.reporting_year     = sel_yr

    # Load and populate session state with this company's data
    hist    = dl.get_company_hist(state.CONSOLIDATED_DF, sel_co)
    step_data = dl.get_step_data(hist, sel_yr) if hist else {}
    valid_fields = state.VALID_TEMPLATE_FIELDS

    for field, val in step_data.items():
        if field in valid_fields:
            st.session_state[field] = val

    from formula_engine import TemplateInputs as TI, calculate as calc
    valid = {f.name for f in TI.__dataclass_fields__.values()}
    clean = {k: v for k, v in step_data.items() if k in valid}
    inp   = TI(company=sel_co, year=sel_yr, **clean)
    out   = calc(inp)

    st.session_state["_codata_inp"] = inp
    st.session_state["_codata_out"] = out
    st.session_state["template_done"]       = True
    st.session_state["company_setup_done"]  = True
    st.session_state["step"]                = 6

    # ── Render all template sheets as tabs ────────────────────────────────────
    tab_main, tab_elec, tab_waste, tab_people_tpl, tab_qual, tab_conv = st.tabs([
        "Main Data Input",
        "Electricity by Country",
        "Waste",
        "People & Governance",
        "Qualitative Data",
        "Conversion Tables",
    ])
    with tab_main:
        render_template_table()
    with tab_elec:
        render_electricity_tab()
    with tab_waste:
        render_waste_tab()
    with tab_people_tpl:
        _render_people_governance_tab()
    with tab_qual:
        render_qualitative_tab()
    with tab_conv:
        render_conversion_tab()

    st.markdown('<div style="height:12px"></div>', unsafe_allow_html=True)
    if st.button("← Back to Portfolio", key="codata_back"):
        st.session_state.page = "portfolio"
        st.rerun()