"""
pages/page_my_dashboard.py — My Dashboard: sector comparison and trend charts.
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


def page_my_dashboard():
    """
    Client My Dashboard — Sector analysis view.
    """
    company = st.session_state.user_company
    st.markdown(section_header_html(
        "My Dashboard",
        f"TIP Sector Analysis · {company} highlighted",
    ), unsafe_allow_html=True)

    if state.CONSOLIDATED_DF.empty or state.SECTOR_DF.empty:
        st.info("Sector data not loaded. Run build_esg_master.py first.")
        return

    # Define has_wide locally (same as in page_analysis)
    df      = state.CONSOLIDATED_DF
    has_wide = not df.empty and "Row_Label" not in df.columns

    # ── Year range selector ───────────────────────────────────────────────────
    col_yr1, col_yr2, col_toggle, _ = st.columns([1, 1, 2, 2])
    with col_yr1:
        _dash_data_yrs = sorted(
            state.CONSOLIDATED_DF["Year"].dropna().unique().astype(int).tolist()
            if not state.CONSOLIDATED_DF.empty else state.LONG_YEARS
        ) or list(state.LONG_YEARS)
        yr_start = st.selectbox("From", _dash_data_yrs, index=0, key="dash_yr_start")
    with col_yr2:
        yr_end   = st.selectbox("To", _dash_data_yrs[::-1], index=0, key="dash_yr_end")
    with col_toggle:
        show_company = st.toggle(f"Highlight {company.split()[0]}", value=True, key="dash_highlight")

    yr_range = [y for y in _dash_data_yrs if yr_start <= y <= yr_end]
    if not yr_range:
        yr_range = _dash_data_yrs

    # Sector data for the range
    sec_range = state.SECTOR_DF[state.SECTOR_DF["Year"].isin(yr_range)].sort_values("Year")

    # Company overlay data
    comp_hist = dl.get_company_hist(state.CONSOLIDATED_DF, company)
    from formula_engine import TemplateInputs as TI, calculate as calc
    valid = {f.name for f in TI.__dataclass_fields__.values()}
    co_kpis = {}
    if show_company:
        for y in yr_range:
            sd = dl.get_step_data(comp_hist, y)
            sc = {k: v for k, v in sd.items() if k in valid}
            if sc:
                o = calc(TI(company=company, year=y, **sc))
                co_kpis[y] = {
                    "co2_kpi": o.co2_kpi, "energy_kpi": o.energy_kpi,
                    "water_kpi": o.water_kpi, "total_co2": o.total_co2,
                }

    # ── 4-metric summary row ──────────────────────────────────────────────────
    if not sec_range.empty:
        latest_sec = sec_range.iloc[-1]
        latest_yr  = int(latest_sec["Year"])
        prev_sec   = sec_range.iloc[-2] if len(sec_range) > 1 else None

        metric_cols = st.columns(4)
        metrics = [
            ("Sector CO₂ Intensity", "Avg_CO2_KPI",    ".3f", "tCO₂/t"),
            ("Sector Energy KPI",    "Avg_Energy_KPI", ".2f", "GJ/t"),
            ("Sector Water KPI",     "Avg_Water_KPI",  ".2f", "m³/t"),
            ("Avg Renewable %",      "Avg_Renewable_Share", ".1f", "%"),
        ]
        for i, (label, col, fmt, unit) in enumerate(metrics):
            with metric_cols[i]:
                val  = latest_sec.get(col, 0)
                prev = prev_sec.get(col, 0) if prev_sec is not None else None
                delta = (f"{(val-prev)/abs(prev)*100:+.1f}%" if prev and prev != 0 else None)
                st.metric(label, f"{val:{fmt}} {unit}", delta=delta)

    st.markdown('<div style="height:4px"></div>', unsafe_allow_html=True)

    # ── Charts ────────────────────────────────────────────────────────────────
    r1c1, r1c2 = st.columns(2, gap="medium")

    with r1c1:
        # Sector total CO₂ bar + company line overlay
        fig1 = go.Figure()
        fig1.add_trace(go.Bar(
            x=sec_range["Year"].tolist(),
            y=sec_range["Total_CO2"].tolist() if "Total_CO2" in sec_range else [],
            name="Sector Total CO₂",
            marker_color="#B8CDD9", marker_line_width=0, width=0.62,
            hovertemplate="<b>%{x}</b><br>Sector: %{y:,.0f} tCO₂<extra></extra>",
        ))
        if co_kpis and show_company:
            co_yrs = sorted(co_kpis.keys())
            fig1.add_trace(go.Scatter(
                x=co_yrs, y=[co_kpis[y]["total_co2"] for y in co_yrs],
                name=company.split()[0], mode="lines+markers",
                line=dict(color=CAT_CO2, width=2.5),
                marker=dict(size=7, color=CAT_CO2, symbol="circle"),
                yaxis="y2",
                hovertemplate="<b>%{x}</b><br>Your CO₂: %{y:,.0f} T<extra></extra>",
            ))
        fig1.update_layout(
            **chart_layout_defaults("Sector CO₂ vs Your Performance", height=300),
            yaxis2=dict(overlaying="y", side="right",
                        title=dict(text=f"{company.split()[0]} CO₂", font=dict(color=CAT_CO2, size=10))),
        )
        apply_chart_animation(fig1)
        st.plotly_chart(fig1, use_container_width=True)

    with r1c2:
        # CO₂ intensity trend — sector average vs company
        fig2 = go.Figure()
        if "Avg_CO2_KPI" in sec_range.columns:
            fig2.add_trace(go.Scatter(
                x=sec_range["Year"].tolist(), y=sec_range["Avg_CO2_KPI"].tolist(),
                name="Sector Average", mode="lines+markers",
                line=dict(color="#9aa1a9", width=1.8, dash="dot"),
                marker=dict(size=5, color="#9aa1a9"),
                fill="tozeroy", fillcolor="rgba(185,200,212,0.12)",
                hovertemplate="Sector avg: %{y:.3f}<extra></extra>",
            ))
        if co_kpis and show_company:
            co_yrs = sorted(co_kpis.keys())
            fig2.add_trace(go.Scatter(
                x=[str(y) for y in co_yrs], y=[co_kpis[y]["co2_kpi"] for y in co_yrs],
                name=company.split()[0],
                mode="lines+markers",
                line=dict(color="#cab6a5", width=2.2),
                marker=dict(size=7, color="#f5f4f2", symbol="circle",
                            line=dict(color="white", width=1.5)),
                hovertemplate=f"{company.split()[0]}: %{{y:.3f}}<extra></extra>",
            ))
        fig2.update_layout(
            **chart_layout_defaults("CO₂ Intensity Trend (tCO₂/t)", height=300),
        )
        apply_chart_animation(fig2)
        st.plotly_chart(fig2, use_container_width=True)

    r2c1, r2c2 = st.columns(2, gap="medium")

    with r2c1:
        # Energy & renewable share
        fig3 = go.Figure()
        if "Avg_Energy_KPI" in sec_range.columns:
            fig3.add_trace(go.Bar(
                x=sec_range["Year"].tolist(), y=sec_range["Avg_Energy_KPI"].tolist(),
                name="Sector Energy KPI", marker_color=CAT_ENERGY, marker_line_width=0, opacity=0.8,
                hovertemplate="<b>%{x}</b><br>Sector avg: %{y:.2f} GJ/t<extra></extra>",
            ))
        if co_kpis and show_company:
            co_yrs = sorted(co_kpis.keys())
            fig3.add_trace(go.Scatter(
                x=[str(y) for y in co_yrs], y=[co_kpis[y]["energy_kpi"] for y in co_yrs],
                name=company.split()[0], mode="lines+markers",
                line=dict(color="#5C2700", width=3.5),
                marker=dict(size=8, color="#5C2700",
                            line=dict(color="white", width=1.5)),
                hovertemplate=f"{company.split()[0]}: %{{y:.2f}} GJ/t<extra></extra>",
            ))
        if "Avg_Renewable_Share" in sec_range.columns:
            fig3.add_trace(go.Scatter(
                x=sec_range["Year"].tolist(), y=sec_range["Avg_Renewable_Share"].tolist(),
                name="Renewable Share %", mode="lines", yaxis="y2",
                line=dict(color=CAT_RENEW, width=1.5, dash="longdash"),
                hovertemplate="Renew. %: %{y:.1f}%<extra></extra>",
            ))
        fig3.update_layout(
            **chart_layout_defaults("Energy KPI vs Renewable Share", height=300),
            yaxis2=dict(overlaying="y", side="right", ticksuffix="%",
                        title=dict(font=dict(color=CAT_RENEW, size=10))),
        )
        apply_chart_animation(fig3)
        st.plotly_chart(fig3, use_container_width=True)

    with r2c2:
        # Water intensity trend
        fig4 = go.Figure()
        if "Avg_Water_KPI" in sec_range.columns:
            fig4.add_trace(go.Scatter(
                x=sec_range["Year"].tolist(), y=sec_range["Avg_Water_KPI"].tolist(),
                name="Sector Average", mode="lines",
                line=dict(color=CAT_WATER, width=2),
                fill="tozeroy", fillcolor="rgba(8,145,178,0.10)",
                hovertemplate="Sector avg: %{y:.2f}<extra></extra>",
            ))
        if co_kpis and show_company:
            co_yrs = sorted(co_kpis.keys())
            fig4.add_trace(go.Scatter(
                x=[str(y) for y in co_yrs], y=[co_kpis[y]["water_kpi"] for y in co_yrs],
                name=company.split()[0], mode="lines+markers",
                line=dict(color="#0C4A6E", width=3.5),
                marker=dict(size=8, color="#0C4A6E", symbol="square",
                            line=dict(color="white", width=1.5)),
                hovertemplate=f"{company.split()[0]}: %{{y:.2f}} m³/t<extra></extra>",
            ))
        fig4.update_layout(
            **chart_layout_defaults("Water Intensity Trend (m³/t)", height=300),
        )
        apply_chart_animation(fig4)
        st.plotly_chart(fig4, use_container_width=True)

    # ── Sector production & companies chart ───────────────────────────────────
    if "Total_Production" in sec_range.columns:
        fig5 = go.Figure()
        fig5.add_trace(go.Scatter(
            x=sec_range["Year"].tolist(),
            y=(sec_range["Total_Production"] / 1e6).tolist(),
            mode="lines+markers",
            fill="tozeroy", fillcolor="rgba(22,163,74,0.08)",
            line=dict(color=GREEN, width=2.5),
            marker=dict(size=6, color=GREEN),
            name="TIP Total Production",
            hovertemplate="<b>%{x}</b><br>%{y:.2f} million T<extra></extra>",
        ))
        fig5.update_layout(**chart_layout_defaults(
            "TIP Sector Total Production (million metric t)", height=220, showlegend=False))
        apply_chart_animation(fig5)
        st.plotly_chart(fig5, use_container_width=True,
                        key=_chart_key(company, "dash_prod"))

    # ── Additional client-facing charts ───────────────────────────────────────
    st.markdown('<div style="height:8px"></div>', unsafe_allow_html=True)
    st.markdown(f"**{company.split()[0]} — Company-specific trends vs sector**")
    st.caption("Your data highlighted · Toggle 'Highlight' to show/hide company overlay")

    r3c1, r3c2 = st.columns(2, gap="medium")

    with r3c1:
        # Renewable electricity trend for this company vs sector
        sec_renew_mean, sec_renew_q25, sec_renew_q75 = {}, {}, {}
        if has_wide and "Renewable_Electricity_Share_%" in sec_range.columns:
            sec_renew_mean = sec_range.set_index("Year")["Renewable_Electricity_Share_%"].to_dict()
        if not state.CONSOLIDATED_DF.empty and "Renewable_Electricity_Share_%" in state.CONSOLIDATED_DF.columns:
            grp = state.CONSOLIDATED_DF.groupby("Year")["Renewable_Electricity_Share_%"]
            sec_renew_q25 = grp.quantile(.25).to_dict()
            sec_renew_q75 = grp.quantile(.75).to_dict()

        fig6 = go.Figure()
        if sec_renew_q25:
            fig6.add_trace(go.Scatter(x=yr_range, y=[sec_renew_q75.get(y) for y in yr_range],
                fill=None, mode="lines", line=dict(width=0), showlegend=False))
            fig6.add_trace(go.Scatter(x=yr_range, y=[sec_renew_q25.get(y) for y in yr_range],
                fill="tonexty", mode="lines", line=dict(width=0),
                fillcolor="rgba(22,163,74,0.10)", name="Sector IQR"))
            fig6.add_trace(go.Scatter(x=yr_range, y=[sec_renew_mean.get(y) for y in yr_range],
                mode="lines", name="Sector Median",
                line=dict(color="#94A3B8", width=1.5, dash="dashdot")))
        if show_company and co_kpis:
            fig6.add_trace(go.Scatter(
                x=sorted(co_kpis.keys()),
                y=[co_kpis[y].get("renew_pct", 0) for y in sorted(co_kpis.keys())],
                mode="lines+markers", name=company.split()[0],
                line=dict(color=CAT_RENEW, width=2.5),
                marker=dict(size=7, color=CAT_RENEW),
                hovertemplate="<b>%{x}</b><br>Renewable: %{y:.1f}%<extra></extra>",
            ))
        fig6.update_layout(**chart_layout_defaults("Renewable Electricity Share (%)", height=270),
                           yaxis=dict(ticksuffix="%", gridcolor="#e6eaed", showline=True,
                                      linecolor="#9aa1a9", showticklabels=True,
                                      tickfont=dict(size=12, color="#6f7882")))
        apply_chart_animation(fig6)
        st.plotly_chart(fig6, use_container_width=True,
                        key=_chart_key(company, sel_yr if 'sel_yr' in dir() else 0, "renew_dash"))

    with r3c2:
        # YoY CO₂ change bar chart for this company
        if co_kpis and len(sorted(co_kpis.keys())) >= 2:
            co_yrs_sorted = sorted(co_kpis.keys())
            yoy_bars  = []
            yoy_years = []
            for j in range(1, len(co_yrs_sorted)):
                y_cur  = co_yrs_sorted[j]
                y_prev = co_yrs_sorted[j-1]
                cur_v  = co_kpis.get(y_cur, {}).get("co2_kpi", 0)
                prv_v  = co_kpis.get(y_prev, {}).get("co2_kpi", 0)
                if prv_v and prv_v != 0:
                    yoy_bars.append((cur_v - prv_v) / abs(prv_v) * 100)
                    yoy_years.append(y_cur)
            if yoy_bars:
                bar_colors = [CAT_RENEW if v < 0 else RED for v in yoy_bars]
                fig7 = go.Figure(go.Bar(
                    x=yoy_years, y=yoy_bars,
                    marker_color=bar_colors, marker_line_width=0,
                    hovertemplate="<b>%{x}</b><br>YoY: %{y:+.2f}%<extra></extra>",
                ))
                fig7.add_hline(y=0, line_color="#CBD5E1", line_width=1)
                fig7.update_layout(**chart_layout_defaults(
                    f"CO₂ Intensity YoY Change (%) — {company.split()[0]}", height=270,
                    showlegend=False),
                    yaxis=dict(ticksuffix="%", gridcolor="#e6eaed", zeroline=False,
                               showline=True, linecolor="#9aa1a9",
                               tickfont=dict(size=12, color="#6f7882")))
                apply_chart_animation(fig7)
                st.plotly_chart(fig7, use_container_width=True,
                                key=_chart_key(company, "yoy_co2_dash"))