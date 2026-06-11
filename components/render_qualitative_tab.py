"""
components/render_qualitative_tab.py — Qualitative data section.
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


def render_qualitative_tab():
    st.markdown("""
    <div style="background:#F9FAFB;border:1px solid #E5E7EB;border-radius:8px;padding:14px 18px;margin-bottom:16px;font-size:13px;color:#374151;line-height:1.7">
    This section gathers qualitative data to help gain additional insights for better interpretation of your
    quantitative data. Please report your company's main programs, trends, or actions that are already
    implemented, under implementation or planned.<br>
    <span style="color:#9CA3AF;font-size:12px">Non-public information will be kept confidential and only used at an aggregated level.</span>
    </div>
    """, unsafe_allow_html=True)

    def qual_section(icon, title, questions):
        st.markdown(f"""
        <div style="background:#0A2240;color:#fff;font-size:13px;font-weight:700;
            padding:9px 16px;border-radius:8px 8px 0 0;margin-top:18px;margin-bottom:0">
          {icon} {title}
        </div>
        """, unsafe_allow_html=True)
        with st.container(border=True):
            for q_label, q_hint, q_key in questions:
                st.markdown(f"**{q_label}**")
                if q_hint: st.caption(q_hint)
                c1, c2, c3 = st.columns([2,2,1])
                with c1: st.text_area("Public information",   key=f"pub_{title}_{q_key}",   height=90, placeholder="Information for the Global KPIs Report...")
                with c2: st.text_area("Non-public (confidential)", key=f"nonpub_{title}_{q_key}", height=90, placeholder="Used only at aggregated level...")
                with c3: st.text_area("Other comments",       key=f"cmt_{title}_{q_key}",   height=90, placeholder="Any additional remarks...")
                st.divider()

    qual_section("", "Energy", [
        ("Program — Management approach", "Explain how your organization manages the energy topic: policies, commitments, ISO 50001 certifications, goals & targets.", "program"),
        ("Impacts", "Include the expected impacts related to the program initiatives. Do you expect efforts to impact the Energy KPI?", "impacts"),
        ("Specific projects completed / underway", "Report specific projects related to energy that you are currently running, implementing or planning.", "projects"),
    ])
    qual_section("", "CO2 Emissions", [
        ("Program — Management approach", "Explain how your organization manages CO2: policies, commitments, goals & targets.", "program"),
        ("Impacts", "Do you expect the efforts to positively or negatively impact the CO2 KPI?", "impacts"),
        ("Specific projects completed / underway", "Report specific projects related to CO2 reduction.", "projects"),
    ])
    qual_section("", "Water", [
        ("Program — Management approach", "Explain how your organization manages water: policies, commitments, goals & targets.", "program"),
        ("Specific projects completed / underway", "Report specific projects related to water management.", "projects"),
    ])
    qual_section("", "Waste", [
        ("Program — Management approach", "Explain how your organization manages waste: policies, commitments, goals & targets.", "program"),
        ("Specific projects completed / underway", "Report the specific projects related to waste that you are currently running.", "projects"),
    ])

    st.markdown("""<div style="background:#0A2240;color:#fff;font-size:13px;font-weight:700;
        padding:9px 16px;border-radius:8px 8px 0 0;margin-top:18px;margin-bottom:0">
      Additional Information</div>""", unsafe_allow_html=True)
    with st.container(border=True):
        st.markdown("**Other information that may affect the five environmental KPIs**")
        st.text_area("Additional comments", key="qual_additional", height=120,
                     placeholder="e.g. major plant closures, acquisitions, production restructuring...")