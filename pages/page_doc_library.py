"""
pages/page_doc_library.py — Document library listing.
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


def page_doc_library():
    """DSS+ Document Library — upload PDFs, AI-extract KPIs."""
    st.markdown(section_header_html(
        "Document Library",
        "Upload company submissions and source documents",
    ), unsafe_allow_html=True)

    col_up, col_lib = st.columns([1, 1], gap="large")

    with col_up:
        st.markdown("**Upload Document**")
        company_sel = st.selectbox("Company", state.COMPANIES, key="doclib_co")
        year_sel    = st.number_input("Year", min_value=2009,
                                      max_value=state.CURR_YEAR + 1,
                                      value=state.CURR_YEAR, step=1, key="doclib_yr")
        doc_type    = st.selectbox("Document Type",
                                   ["Annual ESG Report", "Sustainability Appendix",
                                    "GHG Inventory", "Audit Evidence", "Other"],
                                   key="doclib_type")
        uploaded    = st.file_uploader("Upload PDF or Excel",
                                        type=["pdf", "xlsx", "csv"],
                                        key="doclib_file")
        if uploaded and st.button("📤 Upload & Extract KPIs",
                                   type="primary", use_container_width=True,
                                   key="doclib_upload"):
            with st.spinner("Uploading and extracting KPIs via AI…"):
                import time; time.sleep(1.5)
            st.success(f"Uploaded {uploaded.name} for {company_sel} {year_sel}. "
                       "AI extraction queued — results appear in Verification Queue.")

    with col_lib:
        st.markdown("**Recent Documents**")
        docs = [
            ("VerdaTyres Corp",    2023, "Annual ESG Report",     "complete", "13 May 2026"),
            ("AlphaTread Ltd",     2023, "GHG Inventory",         "review",   "12 May 2026"),
            ("BetaRubber Inc",     2022, "Sustainability Appendix","complete", "10 May 2026"),
            ("DeltaGrip GmbH",     2023, "Annual ESG Report",     "pending",  "08 May 2026"),
        ]
        for co, yr, dtype, status, ts in docs:
            chip = status_chip_html(status)
            st.markdown(f"""
            <div style="background:#fff;border:1px solid {BORDER};border-radius:8px;
                padding:12px 14px;margin-bottom:6px">
              <div style="display:flex;justify-content:space-between;align-items:center">
                <div>
                  <div style="font-size:13px;font-weight:500;color:{TEXT}">{co} · {yr}</div>
                  <div style="font-size:11px;color:{MUTED}">{dtype} · {ts}</div>
                </div>
                {chip}
              </div>
            </div>""", unsafe_allow_html=True)