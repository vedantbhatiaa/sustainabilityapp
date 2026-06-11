"""
components/render_conversion_tab.py — Conversion tables section.
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


def render_conversion_tab():
    st.markdown("#### Unit Conversion Tables")
    st.caption("Reference factors used to normalise data to corporate units. Do not edit.")
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**Energy conversion factors**")
        st.dataframe(pd.DataFrame({
            "Energy Type": ["Natural Gas","Propane","LPG","Diesel","Petrol","Fuel Oil","Coal","Biomass","Waste Tires"],
            "Unit":        ["GJ LHV"]*9,
            "CO2 EF (T.CO2/GJ)": [0.0561,0.0631,0.0561,0.0741,0.0693,0.0774,0.0950,0.0,0.0475],
        }), hide_index=True, use_container_width=True)
    with col2:
        st.markdown("**Unit conversion factors**")
        st.dataframe(pd.DataFrame({
            "Indicator": ["Production","Production","Water","Energy (electric)","Energy (electric)","Waste","Waste"],
            "From unit": ["kg","lb","m³","MWh","TJ","kg","lb"],
            "To unit":   ["metric t","metric t","m³","GJ","GJ","metric t","metric t"],
            "Factor":    [0.001,0.000454,1.0,3.6,1000.0,0.001,0.000454],
        }), hide_index=True, use_container_width=True)
    st.divider()
    st.markdown("**Source:** WBCSD TIP methodology · IEA country factors (Scope 2) · IPCC 2006 Guidelines")