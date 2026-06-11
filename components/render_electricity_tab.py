"""
components/render_electricity_tab.py — Electricity by country editor.
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


def render_electricity_tab():
    """
    Electricity-by-country editor.

    Fix for two bugs:
    1. VALUES RESET BUG — st.data_editor with a static key causes Streamlit to
       discard edits on the first rerun. Fix: never use a static key on the
       data_editor when its underlying data comes from session_state. Instead
       read the widget result back via `on_change` / direct assignment and
       give the editor a key that is stable only within one company+year session,
       so it re-initialises exactly when the company or year changes.

    2. PRE-LOAD BUG — elec_data was always initialised to zeros even when the
       master CSV already had non-zero Elec_*_GJ values for this company.
       Fix: on first load (or when company/year changes) read Elec_*_GJ cols
       from state.CONSOLIDATED_DF, convert GJ→MWh, and populate the editor.
    """
    # Countries shown in the UI (all 31 — display-only for countries not in master schema)
    ELEC_COUNTRIES = state.ELEC_ALL_COUNTRIES  # module-level list of all 31
    COUNTRY_COL_GJ = state.ELEC_COUNTRY_COLS  # all 31 countries stored in master
    GJ_TO_MWH = 1.0 / 3.6

    company  = st.session_state.get("reporting_company") or st.session_state.get("user_company", "")
    rep_year = st.session_state.get("reporting_year", state.CURR_YEAR)

    # Build YEARS dynamically: always include the latest submitted year + any
    # year the company has data for. This ensures 2024/2025 columns appear
    # automatically when the company submits for those years.
    _co_yrs = []
    if not state.CONSOLIDATED_DF.empty and company:
        _co_yrs = dl.get_years(state.CONSOLIDATED_DF, company) or []
    # Always go up to the reporting year (rep_year)
    _max_yr = max([rep_year] + (_co_yrs or [2023]))
    YEARS = list(range(2009, _max_yr + 1))

    # ── Key that tracks which company+year the editor was last initialised for ──
    # When this changes we rebuild elec_data from the master so the editor
    # always shows what is actually stored in the DB.
    load_key = f"{company}|{rep_year}"
    needs_reload = st.session_state.get("_elec_load_key") != load_key

    if needs_reload:
        # Build base DataFrame of zeros
        rows = [{"Country": c, "Unit": "MWh", **{str(yr): 0.0 for yr in YEARS}}
                for c in ELEC_COUNTRIES]
        df = pd.DataFrame(rows)

        # Pre-populate from master CSV for countries that are stored
        if not state.CONSOLIDATED_DF.empty and company:
            for country, col_gj in COUNTRY_COL_GJ.items():
                if col_gj not in state.CONSOLIDATED_DF.columns:
                    continue
                co_df = state.CONSOLIDATED_DF[state.CONSOLIDATED_DF["Company"] == company]
                for _, mrow in co_df.iterrows():
                    yr = int(mrow["Year"]) if pd.notna(mrow.get("Year")) else None
                    if yr is None or yr < 2009:
                        continue
                    # Extend YEARS list if master has data for a year not yet in YEARS
                    if yr not in YEARS:
                        YEARS.append(yr)
                        df[str(yr)] = 0.0
                    gj_val = mrow.get(col_gj)
                    if pd.notna(gj_val) and float(gj_val) != 0:
                        mwh_val = round(float(gj_val) * GJ_TO_MWH, 2)
                        idx = df.index[df["Country"] == country]
                        if len(idx):
                            df.loc[idx[0], str(yr)] = mwh_val

        # Ensure all year columns are numeric (avoid object dtype after assignment)
        for yr in YEARS:
            df[str(yr)] = pd.to_numeric(df[str(yr)], errors="coerce").fillna(0.0)

        st.session_state.elec_data     = df
        st.session_state._elec_load_key = load_key
        # Drop the old widget key so Streamlit re-renders a fresh editor
        if "_elec_editor_key_idx" not in st.session_state:
            st.session_state._elec_editor_key_idx = 0
        st.session_state._elec_editor_key_idx += 1

    # ── Editor key: unique per company+year so Streamlit does not reuse ───────
    # the old internal widget state (which is what causes edits to be lost).
    editor_key = f"elec_editor_{st.session_state.get('_elec_editor_key_idx', 0)}"

    st.markdown("#### Non-Renewable Electricity Purchased by Country")


    col_cfg = {
        "Country": st.column_config.TextColumn("Country", disabled=True, width="medium"),
        "Unit":    st.column_config.TextColumn("Unit",    disabled=True, width="small"),
    }
    for yr in YEARS:
        col_cfg[str(yr)] = st.column_config.NumberColumn(
            str(yr), min_value=0, format="%.2f", width="small"
        )

    # Render the editor — DO NOT write its return value back to session_state
    # here; instead use the on-change callback approach via a separate Save button.
    # The data_editor return value IS the live edited state on every rerun.
    edited = st.data_editor(
        st.session_state.elec_data,
        column_config=col_cfg,
        hide_index=True,
        use_container_width=True,
        height=900,
        key=editor_key,
        # num_rows="fixed" so no row add/delete accidentally resets things
        num_rows="fixed",
    )
    # Always keep session_state in sync with what the editor returns this frame
    st.session_state.elec_data = edited

    # ── Save button ───────────────────────────────────────────────────────────
    col_a, col_b = st.columns([4, 1])
    with col_b:
        if st.button("💾 Save electricity data", type="primary", key="elec_save_btn"):
            msg = _save_electricity_to_master(company, rep_year)
            if "saved" in msg.lower() or "synced" in msg.lower():
                st.success("✅ Saved successfully — added to your database.")
            else:
                st.warning(msg)

    # ── Summary metrics ───────────────────────────────────────────────────────
    rep_yr_str = str(rep_year)
    total_rep  = edited[rep_yr_str].sum() if rep_yr_str in edited.columns else 0
    total_all  = sum(edited[str(yr)].sum() for yr in YEARS if str(yr) in edited.columns)
    c1, c2 = st.columns(2)
    c1.metric(f"Total — {rep_yr_str} (all countries)", f"{total_rep:,.0f} MWh")
    c2.metric("Grand total all years", f"{total_all:,.0f} MWh")