"""
pages/page_portfolio.py — DSS portfolio overview: all companies submission status.
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


def page_portfolio():
    """DSS+ Portfolio — 10-company grid with status chips and KPI heatmap."""
    st.markdown(section_header_html(
        "Portfolio Overview",
        f"All TIP member companies · {state.CURR_YEAR} reporting cycle",
        badge=f"{len(state.COMPANIES)} Companies",
    ), unsafe_allow_html=True)

    if state.CONSOLIDATED_DF.empty:
        st.markdown(empty_state_html("🗂️", "No data loaded",
            "Run python build_esg_master.py to load company data."),
            unsafe_allow_html=True)
        return

    # Status summary bar
    statuses = ["complete", "review", "pending"]
    status_map = {}
    for i, co in enumerate(state.COMPANIES):
        # Determine status from data completeness
        hist = dl.get_company_hist(state.CONSOLIDATED_DF, co)
        step = dl.get_step_data(hist, state.CURR_YEAR) if hist else {}
        n    = len(step)
        status_map[co] = "complete" if n >= 15 else "review" if n >= 5 else "pending"

    n_complete = sum(1 for s in status_map.values() if s == "complete")
    n_review   = sum(1 for s in status_map.values() if s == "review")
    n_pending  = sum(1 for s in status_map.values() if s == "pending")

    st.markdown(f"""
    <div style="display:flex;gap:12px;margin-bottom:20px">
      <div style="background:#DCFCE7;border-radius:8px;padding:12px 20px;flex:1;text-align:center">
        <div style="font-size:28px;font-weight:700;color:#166534">{n_complete}</div>
        <div style="font-size:11px;color:#166534;font-weight:500">Complete</div>
      </div>
      <div style="background:#FEF3C7;border-radius:8px;padding:12px 20px;flex:1;text-align:center">
        <div style="font-size:28px;font-weight:700;color:#92400E">{n_review}</div>
        <div style="font-size:11px;color:#92400E;font-weight:500">In Review</div>
      </div>
      <div style="background:#F1F5F9;border-radius:8px;padding:12px 20px;flex:1;text-align:center">
        <div style="font-size:28px;font-weight:700;color:#475569">{n_pending}</div>
        <div style="font-size:11px;color:#475569;font-weight:500">Pending</div>
      </div>
    </div>""", unsafe_allow_html=True)

    # Company grid — 2 columns
    cols = st.columns(2, gap="medium")
    from formula_engine import TemplateInputs as TI, calculate as calc
    valid = {f.name for f in TI.__dataclass_fields__.values()}

    for i, company in enumerate(state.COMPANIES):
        hist  = dl.get_company_hist(state.CONSOLIDATED_DF, company)
        step  = dl.get_step_data(hist, state.CURR_YEAR) if hist else {}
        clean = {k: v for k, v in step.items() if k in valid}
        out   = calc(TI(company=company, year=state.CURR_YEAR, **clean))
        kpis  = {"co2_kpi": out.co2_kpi, "energy_kpi": out.energy_kpi,
                 "water_kpi": out.water_kpi}

        with cols[i % 2]:
            st.markdown(co_card_html(
                company, status_map[company], state.CURR_YEAR,
                kpis, anim_delay=i * 60,
            ), unsafe_allow_html=True)
            if st.button(f"Open {company.split()[0]} Template →",
                         key=f"port_view_{i}", use_container_width=True):
                st.session_state.portfolio_company  = company
                st.session_state.reporting_company  = company
                st.session_state.dss_verif_company  = company
                st.session_state.dss_ready_company  = company
                st.session_state.dss_analy_company  = company
                st.session_state.company_setup_done = False
                st.session_state.template_done      = False
                st.session_state.step               = 0
                st.session_state.page               = "company_data"
                st.rerun()
        st.markdown('<div style="height:4px"></div>', unsafe_allow_html=True)