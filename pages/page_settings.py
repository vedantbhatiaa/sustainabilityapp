"""
pages/page_settings.py — User settings (notifications, display preferences).
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


def page_settings():
    """Settings page — for both client and DSS+ users."""
    st.markdown(section_header_html("Settings", "Account & preferences"),
                unsafe_allow_html=True)

    tab_acct, tab_notif, tab_about = st.tabs(["Account", "Notifications", "About"])

    with tab_acct:
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**Profile**")
            st.text_input("Display Name", value=st.session_state.user_name,
                          key="set_name")
            st.text_input("Email", value=st.session_state.user_email,
                          disabled=True, key="set_email")
            role = "dss+ Analyst (Internal)" if st.session_state.is_dss else "Client Company User"
            st.text_input("Role", value=role, disabled=True, key="set_role")
            if st.button("Save Profile", key="save_profile"):
                st.success("Profile updated.")
        with col2:
            st.markdown("**Security**")
            st.text_input("Current Password", type="password", key="set_cur_pw")
            st.text_input("New Password",     type="password", key="set_new_pw")
            st.text_input("Confirm Password", type="password", key="set_cfm_pw")
            if st.button("Change Password", key="change_pw"):
                st.info("Password change will be available in the full production release.")

    with tab_notif:
        st.markdown("**Email notifications**")
        st.checkbox("Submission deadline reminders",          value=True,  key="n1")
        st.checkbox("Verification status updates",            value=True,  key="n2")
        st.checkbox("Sector benchmarks published",            value=False, key="n3")
        st.checkbox("AI anomaly alerts",                      value=True,  key="n4")
        if st.button("Save notification preferences", key="save_notif"):
            st.success("Preferences saved.")

    with tab_about:
        st.markdown(f"""
        **TIP ESG Platform**

        Version 1.0 · Built for the WBCSD Tire Industry Project by dss+

        - Formula engine: GHG Protocol Scope 1 & 2
        - Benchmark data: TIP member companies 2009–{state.CURR_YEAR}
        - AI assistant: Local Ollama (phi3) / Azure OpenAI Enterprise
        - Storage: Local filesystem (v1) → Azure SharePoint (v2)

        *For technical support contact your dss+ account manager.*
        """)