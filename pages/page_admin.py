"""
pages/page_admin.py — Admin panel: tenants, users, AI logs, system info.
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


def page_admin():
    """DSS+ Admin — tenant management, RBAC, AI usage."""
    st.markdown(section_header_html(
        "Admin", "Platform administration",
        badge="DSS+ Only",
    ), unsafe_allow_html=True)

    tab_tenants, tab_users, tab_ai, tab_system = st.tabs(
        ["Tenants", "Users", "AI Usage", "System"]
    )

    with tab_tenants:
        st.markdown("**Active Tenants (TIP Member Companies)**")
        for i, co in enumerate(state.COMPANIES):
            st.markdown(f"""
            <div style="background:#fff;border:1px solid {BORDER};border-radius:8px;
                padding:10px 14px;margin-bottom:4px;display:flex;
                align-items:center;justify-content:space-between">
              <div style="font-size:13px;font-weight:500;color:{TEXT}">{co}</div>
              <div style="display:flex;gap:8px">
                {status_chip_html('complete')}
                <span style="font-size:11px;color:{MUTED}">Active since 2021</span>
              </div>
            </div>""", unsafe_allow_html=True)

        st.markdown('<div style="height:12px"></div>', unsafe_allow_html=True)
        with st.expander("+ Add New Tenant"):
            st.text_input("Company Name", key="admin_co_name")
            st.text_input("Contact Email", key="admin_co_email")
            st.number_input("Joined Year", min_value=2009,
                            max_value=state.CURR_YEAR, value=state.CURR_YEAR,
                            key="admin_co_year")
            if st.button("Add Tenant", type="primary", key="admin_add_co"):
                st.info("Tenant provisioning will be available in v2 (Azure AD integration).")

    with tab_users:
        st.markdown("**Role-Based Access Control**")
        roles = {
            "Client User":    "Edit and submit own company data",
            "Client Admin":   "Manage users + approve within tenant",
            "DSS+ Analyst":   "Cross-tenant read, verification write",
            "DSS+ Admin":     "Super-user, manage all tenants and AI settings",
        }
        for role, desc in roles.items():
            st.markdown(f"""
            <div style="background:#fff;border:1px solid {BORDER};border-radius:8px;
                padding:10px 14px;margin-bottom:4px">
              <div style="font-size:13px;font-weight:600;color:{TEXT}">{role}</div>
              <div style="font-size:11px;color:{MUTED}">{desc}</div>
            </div>""", unsafe_allow_html=True)

    with tab_ai:
        st.markdown("**AI Usage Logs**")
        st.info("AI usage logs are stored in data_storage/chat_logs/ (JSONL format). "
                "Full usage analytics will be available in v2.")
        log_dir = Path("data_storage/chat_logs")
        if log_dir.exists():
            logs = list(log_dir.glob("*.jsonl"))
            st.metric("Log files this week", len(logs))
            for lf in sorted(logs, reverse=True)[:5]:
                st.markdown(f"• `{lf.name}` — {lf.stat().st_size:,} bytes")

    with tab_system:
        st.markdown("**System Information**")
        import platform, sys
        info = {
            "Python": sys.version.split()[0],
            "Platform": platform.system(),
            "Data Year Range": f"{cfg.DATA_YEAR_START}–{cfg.DATA_YEAR_END}",
            "Companies": len(state.COMPANIES),
            "Master CSV rows": len(state.CONSOLIDATED_DF) if not state.CONSOLIDATED_DF.empty else 0,
        }
        for k, v in info.items():
            st.markdown(f"""
            <div style="display:flex;justify-content:space-between;
                padding:6px 0;border-bottom:1px solid {BG};font-size:13px">
              <span style="color:{MUTED}">{k}</span>
              <span style="color:{TEXT};font-weight:500">{v}</span>
            </div>""", unsafe_allow_html=True)