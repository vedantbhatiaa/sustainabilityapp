"""
pages/page_home.py — Client home dashboard with KPI tiles and trend charts.
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


def page_home():
    """
    Client Home — 8 animated KPI cards, interactive trend charts, summary data table.
    This is the client's personal performance dashboard.
    """
    company  = st.session_state.user_company
    comp_hist = dl.get_company_hist(state.CONSOLIDATED_DF, company)
    years     = sorted(dl.get_years(state.CONSOLIDATED_DF, company))

    # ── Header: Welcome + year selector + Submit Data inline ─────────────────
    h_left, h_mid, h_right = st.columns([3, 1, 1])
    with h_left:
        st.markdown(section_header_html(
            f"Welcome, {st.session_state.user_name.split()[0]} 👋",
            f"{company} · Your Performance Dashboard",
        ), unsafe_allow_html=True)
    with h_mid:
        if years:
            sel_yr = st.selectbox("", sorted(years, reverse=True),
                                  key="home_yr", label_visibility="collapsed")
        else:
            sel_yr = state.CURR_YEAR
    with h_right:
        if st.button("📋 Submit Data", use_container_width=True, key="home_submit_btn"):
            st.session_state.page = "entry"
            st.rerun()

    if not years:
        st.markdown(empty_state_html("📊", "No data yet",
            "Submit your first KPI report to see your dashboard.",
            "→ Submit Data"), unsafe_allow_html=True)
        return

    from formula_engine import TemplateInputs as TI, calculate as calc
    valid = {f.name for f in TI.__dataclass_fields__.values()}

    step  = dl.get_step_data(comp_hist, sel_yr)
    clean = {k: v for k, v in step.items() if k in valid}
    inp   = TI(company=company, year=sel_yr, **clean)
    out   = calc(inp)

    prev_out = None
    if sel_yr - 1 in years:
        ps = dl.get_step_data(comp_hist, sel_yr - 1)
        pc = {k: v for k, v in ps.items() if k in valid}
        prev_out = calc(TI(company=company, year=sel_yr - 1, **pc))

    # ── Submission status strip — data completeness + DSS+ verification state ───
    status_hist  = dl.get_company_hist(state.CONSOLIDATED_DF, company)
    step_data_yr = dl.get_step_data(status_hist, sel_yr) if status_hist else {}

    def _has(key, min_val=1):
        v = step_data_yr.get(key, 0)
        try: return float(v) >= min_val
        except: return bool(v)

    section_done = [
        _has("total_sites"),
        _has("production"),
        _has("water_withdrawals"),
        _has("renew_elec_purchased") or _has("nonrenew_elec_purchased") or _has("nat_gas"),
        step_data_yr.get("co2_scope2_steam") is not None and _has("production"),
        _has("waste_total"),
    ]
    n_done = sum(section_done)
    pct    = n_done / 6 * 100
    sc     = GREEN if pct == 100 else (AMBER if pct >= 50 else RED)

    # Check DSS+ verification status from persistent CSV
    verif_status = "Not Submitted"
    verif_color  = "#94A3B8"
    verif_icon   = "○"
    try:
        from pathlib import Path
        vcsv = Path("data_storage/verifications.csv")
        if vcsv.exists():
            import csv
            with open(vcsv, newline="") as f:
                for row in csv.DictReader(f):
                    if row.get("Company","").strip() == company and str(row.get("Year","")).strip() == str(sel_yr):
                        vs = row.get("Status","").strip()
                        if vs == "Verified":
                            verif_status = "Verified by dss+"; verif_color = GREEN; verif_icon = "✓"
                        elif vs == "Pending":
                            verif_status = "Pending Review";   verif_color = AMBER; verif_icon = "◉"
                        elif vs == "Flagged":
                            verif_status = "Flagged — see notes"; verif_color = RED; verif_icon = "⚑"
        elif n_done > 0:
            verif_status = "Pending Review"; verif_color = AMBER; verif_icon = "◉"
    except Exception:
        pass

    st.markdown(f"""
    <div style="background:#fff;border:1px solid {BORDER};border-radius:8px;
        padding:12px 20px;margin-bottom:16px;display:flex;align-items:center;gap:16px">
      <div style="flex:1">
        <div style="font-size:12px;color:{MUTED};margin-bottom:5px">
          {sel_yr} Submission Status</div>
        <div style="background:#F1F5F9;border-radius:4px;height:6px;overflow:hidden">
          <div style="background:{sc};width:{pct:.0f}%;height:100%;border-radius:4px;
              transition:width .8s ease"></div>
        </div>
      </div>
      <div style="font-size:18px;font-weight:700;color:{sc}">{n_done}/6</div>
      <div style="font-size:12px;color:{MUTED}">sections complete</div>
      <div style="border-left:1px solid {BORDER};padding-left:16px;font-size:12px;
          color:{verif_color};font-weight:600;white-space:nowrap">
        {verif_icon} {verif_status}</div>
    </div>""", unsafe_allow_html=True)

    # ── 8 KPI cards (4 × 2) ──────────────────────────────────────────────────
    renew_tot = max(inp.renew_elec_purchased + inp.nonrenew_elec_purchased + inp.self_gen_elec, 1)
    renew_pct = inp.renew_elec_purchased / renew_tot * 100

    def _yoy(cur, prev_val, lower=True):
        if not prev_val or prev_val == 0: return "", ""
        pct = (cur - prev_val) / abs(prev_val) * 100
        good = pct <= 0 if lower else pct >= 0
        bg   = "#DCFCE7" if good else "#FEE2E2"
        col  = "#166534" if good else "#991B1B"
        arr  = "▼" if pct < 0 else "▲"
        sign = "+" if pct > 0 else ""
        chip = (f'<span style="background:{bg};color:{col};font-size:10px;font-weight:600;'
                f'padding:2px 7px;border-radius:4px">{arr}{sign}{pct:.1f}%</span>')
        return chip, bg

    p = prev_out
    cards = [
        ("CO₂ Absolute",      f"{out.total_co2:,.0f}",           "tCO₂",  *_yoy(out.total_co2, p.total_co2 if p else 0),       CAT_CO2),
        ("CO₂ Intensity",     f"{out.co2_kpi:.3f}",              "t/t",    *_yoy(out.co2_kpi,   p.co2_kpi   if p else 0),       CAT_CO2),
        ("Energy Intensity",  f"{out.energy_kpi:.2f}",           "GJ/t",   *_yoy(out.energy_kpi,p.energy_kpi if p else 0),      CAT_ENERGY),
        ("Renewable Share",   f"{renew_pct:.1f}",                "%",      *_yoy(renew_pct, 0, lower=False),                    CAT_RENEW),
        ("Water Intensity",   f"{out.water_kpi:.2f}",            "m³/t",   *_yoy(out.water_kpi, p.water_kpi if p else 0),       CAT_WATER),
        ("Water Withdrawal",  f"{inp.water_withdrawals:,.0f}",   "m³",     *_yoy(inp.water_withdrawals, 0),                     CAT_WATER),
        ("Waste Recovery",    f"{out.waste_recovery_pct*100:.1f}","%",     *_yoy(out.waste_recovery_pct*100, (p.waste_recovery_pct*100 if p else 0), lower=False), CAT_WASTE),
        ("ISO 14001",         f"{out.pct_certified*100:.0f}",    "%",      *_yoy(out.pct_certified*100, (p.pct_certified*100 if p else 0), lower=False), GREEN),
    ]
    COLORS_CARD = [CAT_CO2,CAT_CO2,CAT_ENERGY,CAT_RENEW,CAT_WATER,CAT_WATER,CAT_WASTE,GREEN]

    for row_start in [0, 4]:
        cols = st.columns(4)
        for i, (label, val_str, unit, chip_html, _, color) in enumerate(cards[row_start:row_start+4]):
            with cols[i]:
                st.markdown(f"""
                <div style="background:#fff;border:1px solid {BORDER};border-radius:10px;
                    padding:16px 18px 14px;margin-bottom:8px;height:110px;
                    display:flex;flex-direction:column;justify-content:space-between;
                    animation:tipFadeIn 400ms ease-out {i*70+row_start*30}ms both;
                    transition:box-shadow 200ms,transform 200ms"
                    onmouseover="this.style.boxShadow='0 6px 20px rgba(15,23,42,.1)';this.style.transform='translateY(-2px)'"
                    onmouseout="this.style.boxShadow='';this.style.transform=''">
                  <div style="font-size:10.5px;font-weight:600;color:{MUTED};
                      text-transform:uppercase;letter-spacing:.6px">{label}</div>
                  <div style="font-size:26px;font-weight:700;color:{color};
                      font-variant-numeric:tabular-nums;line-height:1;letter-spacing:-.5px;
                      white-space:nowrap;overflow:hidden;text-overflow:ellipsis">
                    {val_str}
                    <span style="font-size:11px;font-weight:400;color:{MUTED};margin-left:2px">{unit}</span>
                  </div>
                  <div style="margin-top:2px">{chip_html}</div>
                </div>""", unsafe_allow_html=True)

    st.markdown('<div style="height:8px"></div>', unsafe_allow_html=True)

    # ── Interactive charts ────────────────────────────────────────────────────
    t1, t2, t3, t4 = st.tabs(["📈 CO₂ Trend", "⚡ Energy Mix", "💧 Water", "♻️ Waste & Fuel"])

    # Build multi-year computed KPIs for charts
    yr_kpis = {}
    for y in years:
        sd = dl.get_step_data(comp_hist, y)
        sc = {k: v for k, v in sd.items() if k in valid}
        o  = calc(TI(company=company, year=y, **sc))
        ii = TI(company=company, year=y, **sc)
        rt = max(ii.renew_elec_purchased + ii.nonrenew_elec_purchased + ii.self_gen_elec, 1)
        yr_kpis[y] = {
            "scope1": o.total_co2_scope1, "scope2": o.total_co2_scope2,
            "total_co2": o.total_co2, "co2_kpi": o.co2_kpi,
            "energy_kpi": o.energy_kpi, "water_kpi": o.water_kpi,
            "waste_pct": o.waste_recovery_pct * 100,
            "renew_pct": ii.renew_elec_purchased / rt * 100,
            "nat_gas": ii.nat_gas, "coal": ii.coal_sub, "diesel": ii.diesel,
            "biomass": ii.biomass, "renew_elec": ii.renew_elec_purchased,
            "nonrenew_elec": ii.nonrenew_elec_purchased,
            "water_m3": ii.water_withdrawals, "production": ii.production,
        }

    # Filter to years that have actual production data (non-zero) to avoid
    # invisible zero bars squashing the chart. Cap at last 10 years max.
    ys = [y for y in years if yr_kpis.get(y, {}).get("production", 0) > 0]
    if not ys:
        ys = years  # fallback: use all years if filter removes everything
    ys = ys[-10:]   # cap at last 10 years for readability
    ys_str = [str(y) for y in ys]  # string labels for Plotly category x-axis

    # Note: stackgroup Scatter traces force Plotly to linear axis — each chart
    # must explicitly override xaxis with type="category" in update_layout.

    with t1:
        # Stacked bar: Scope 1 + Scope 2 with CO₂ intensity line on y2.
        # Uses 0-based indices as x (not year numbers) so Plotly auto-spaces
        # bars evenly regardless of the gap between year values (e.g. 2016-2025).
        # Year labels are applied via tickvals/ticktext.
        _xi = list(range(len(ys)))   # 0, 1, 2, ..., n-1

        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=_xi, y=[yr_kpis[y]["scope2"] for y in ys],
            name="Scope 2 (indirect)",
            marker_color="rgba(185,200,212,0.88)", marker_line_width=0,
            width=0.62,
            customdata=ys_str,
            hovertemplate="<b>%{customdata}</b> · Scope 2<br>%{y:,.0f} tCO₂<extra></extra>",
        ))
        fig.add_trace(go.Bar(
            x=_xi, y=[yr_kpis[y]["scope1"] for y in ys],
            name="Scope 1 (direct)",
            marker_color="rgba(70,92,102,0.88)", marker_line_width=0,
            width=0.62,
            customdata=ys_str,
            hovertemplate="<b>%{customdata}</b> · Scope 1<br>%{y:,.0f} tCO₂<extra></extra>",
        ))
        # Intensity line — same index-based x
        fig.add_trace(go.Scatter(
            x=_xi, y=[yr_kpis[y]["co2_kpi"] for y in ys],
            name="CO₂ Intensity (t/t)", yaxis="y2",
            mode="lines",
            line=dict(color="#cab6a5", width=2.2),
            customdata=ys_str,
            hovertemplate="<b>%{customdata}</b><br>Intensity: %{y:.3f} t/t<extra></extra>",
        ))
        # Best-intensity-year annotation
        if len(ys) >= 2:
            best_y  = min(ys, key=lambda y: yr_kpis[y]["co2_kpi"])
            best_xi = ys.index(best_y)
            fig.add_annotation(x=best_xi, y=yr_kpis[best_y]["co2_kpi"], yref="y2",
                               text="Best", showarrow=True, arrowhead=2,
                               ax=0, ay=-30, font=dict(size=11, color=GREEN),
                               arrowcolor=GREEN)
        fig.update_layout(
            barmode="stack",
            plot_bgcolor="#f5f4f2", paper_bgcolor="#f5f4f2",
            height=320,
            bargap=0.24,
            margin=dict(l=55, r=70, t=50, b=55),
            title=dict(text="<b>Total CO₂ Emissions (Scope 1 + 2) with Intensity</b>",
                       font=dict(size=14, color="#2a2825"), x=0),
            xaxis=dict(
                tickmode="array", tickvals=_xi, ticktext=ys_str,
                showgrid=False, showline=True, linecolor="#9aa1a9", linewidth=1.2,
                tickfont=dict(size=12, color="#6f7882"), zeroline=False,
            ),
            yaxis=dict(
                title=dict(text="tCO₂", font=dict(size=12, color="#6f7882")),
                tickformat=",", showline=True, linecolor="#9aa1a9", linewidth=1.2,
                showticklabels=True, tickfont=dict(size=12, color="#6f7882"),
                gridcolor="#e6eaed", zeroline=False,
            ),
            yaxis2=dict(
                title=dict(text="CO₂ Intensity (t/t)", font=dict(size=11, color="#cab6a5")),
                overlaying="y", side="right", tickformat=".3f",
                showgrid=False, showline=True, linecolor="#9aa1a9",
                tickfont=dict(size=12, color="#6f7882"),
            ),
            legend=dict(orientation="h", x=0.5, xanchor="center", y=-0.22,
                        font=dict(size=12, color="#6f7882"), bgcolor="rgba(0,0,0,0)"),
            hovermode="x unified",
        )
        apply_chart_animation(fig)
        st.plotly_chart(fig, use_container_width=True)

    with t2:
        fuel_cfg = [
            ("Renewable Elec.",  [yr_kpis[y]["renew_elec"]    for y in ys], "#7BAF74"),   # TIP bar_green
            ("Non-Renew. Elec.", [yr_kpis[y]["nonrenew_elec"] for y in ys], "#B8CDD9"),   # TIP bar_blue
            ("Natural Gas",      [yr_kpis[y]["nat_gas"]        for y in ys], "#C8B49A"),   # TIP bar_beige
            ("Coal",             [yr_kpis[y]["coal"]           for y in ys], "#2D4A5A"),   # TIP bar_blue2
            ("Diesel",           [yr_kpis[y]["diesel"]         for y in ys], "#E0935A"),   # TIP bar_orange
            ("Biomass",          [yr_kpis[y]["biomass"]        for y in ys], "#9FB8C5"),   # TIP bar_commit
        ]
        fig2 = go.Figure()
        for label, vals, color in fuel_cfg:
            if any(v > 0 for v in vals):
                fig2.add_trace(go.Bar(
                    name=label, x=list(range(len(ys))), y=vals, marker_color=color,
                    marker_line_width=0,
                    hovertemplate=f"<b>{label}</b><br>%{{x}}: %{{y:,.0f}} GJ<br>%{{customdata:.1f}}% of total<extra></extra>",
                ))
        fig2.update_layout(
            barmode="stack",
            plot_bgcolor="#f5f4f2", paper_bgcolor="#f5f4f2",
            height=320, bargap=0.28,
            margin=dict(l=55, r=65, t=50, b=55),
            title=dict(text="<b>Energy Mix by Source (GJ)</b>",
                       font=dict(size=14, color="#2a2825"), x=0),
            xaxis=dict(tickmode="array", tickvals=list(range(len(ys))),
                       ticktext=ys_str, showgrid=False, showline=True,
                       linecolor="#9aa1a9", linewidth=1.2,
                       tickfont=dict(size=12, color="#6f7882"), zeroline=False),
            yaxis=dict(showgrid=True, gridcolor="#e6eaed", showline=True,
                       linecolor="#9aa1a9", linewidth=1.2,
                       tickfont=dict(size=12, color="#6f7882"), zeroline=False),
            legend=dict(orientation="h", x=0.5, xanchor="center", y=-0.22,
                        font=dict(size=12, color="#6f7882"), bgcolor="rgba(0,0,0,0)"),
            hovermode="x unified", showlegend=True,
        )
        apply_chart_animation(fig2)
        st.plotly_chart(fig2, use_container_width=True)

    with t3:
        w_m3  = [yr_kpis[y]["water_m3"]  for y in ys]
        w_kpi = [yr_kpis[y]["water_kpi"] for y in ys]
        fig3  = go.Figure()
        fig3.add_trace(go.Bar(
            x=list(range(len(ys))), y=w_m3, name="Total Withdrawals",
            marker_color="#B8CDD9", marker_line_width=0,    # TIP bar_blue
            width=0.62,
            hovertemplate="<b>%{x}</b><br>%{y:,.0f} m³<extra></extra>",
        ))
        fig3.add_trace(go.Scatter(
            x=list(range(len(ys))), y=w_kpi, name="Intensity (m³/t)",
            yaxis="y2", mode="lines",
            line=dict(color="#2D4A5A", width=2.2),          # TIP line_dark
            hovertemplate="<b>%{x}</b><br>Intensity: %{y:.2f} m³/t<extra></extra>",
        ))
        fig3.update_layout(
            plot_bgcolor="#f5f4f2", paper_bgcolor="#f5f4f2",
            height=320, bargap=0.24,
            margin=dict(l=55, r=70, t=50, b=55),
            title=dict(text="<b>Water Withdrawals & Intensity</b>",
                       font=dict(size=14, color="#2a2825"), x=0),
            xaxis=dict(tickmode="array", tickvals=list(range(len(ys))),
                       ticktext=ys_str, showgrid=False, showline=True,
                       linecolor="#9aa1a9", linewidth=1.2,
                       tickfont=dict(size=12, color="#6f7882"), zeroline=False),
            yaxis=dict(title=dict(text="m³", font=dict(size=12, color="#6f7882")),
                       tickformat=",", showline=True, linecolor="#9aa1a9", linewidth=1.2,
                       showticklabels=True, tickfont=dict(size=12, color="#6f7882"),
                       gridcolor="#e6eaed", zeroline=False),
            yaxis2=dict(title=dict(text="Water Intensity (m³/t)",
                        font=dict(size=11, color="#2D4A5A")),
                        overlaying="y", side="right", tickformat=".2f",
                        showgrid=False, showline=True, linecolor="#9aa1a9",
                        tickfont=dict(size=12, color="#6f7882")),
            hovermode="x unified",
        )
        apply_chart_animation(fig3)
        st.plotly_chart(fig3, use_container_width=True)

    with t4:
        w_total    = [dl.get_step_data(comp_hist, y).get("waste_total",    0) for y in ys]
        w_recovery = [dl.get_step_data(comp_hist, y).get("waste_recovery", 0) for y in ys]
        w_pcts     = [yr_kpis[y]["waste_pct"]   for y in ys]

        c1, c2 = st.columns([2, 1])
        with c1:
            fig4 = go.Figure()
            fig4.add_trace(go.Bar(
                x=list(range(len(ys))), y=w_total, name="Total Waste",
                marker_color="#B8CDD9", marker_line_width=0,   # TIP bar_blue
                width=0.62,
            ))
            fig4.add_trace(go.Bar(
                x=list(range(len(ys))), y=w_recovery, name="Recovered",
                marker_color="#7BAF74", marker_line_width=0,   # TIP bar_green
                width=0.62,
            ))
            fig4.add_trace(go.Scatter(
                x=list(range(len(ys))), y=w_pcts, name="Recovery %",
                yaxis="y2", mode="lines",
                line=dict(color="#2D4A5A", width=2.2),         # TIP line_dark
                hovertemplate="Recovery: %{y:.1f}%<extra></extra>",
            ))
            fig4.update_layout(
                barmode="overlay",
                plot_bgcolor="#f5f4f2", paper_bgcolor="#f5f4f2",
                height=300, bargap=0.24,
                margin=dict(l=55, r=70, t=50, b=55),
                title=dict(text="<b>Waste Recovery (T)</b>",
                           font=dict(size=14, color="#2a2825"), x=0),
                xaxis=dict(tickmode="array", tickvals=list(range(len(ys))),
                           ticktext=ys_str, showgrid=False, showline=True,
                           linecolor="#9aa1a9", linewidth=1.2,
                           tickfont=dict(size=12, color="#6f7882"), zeroline=False),
                yaxis=dict(title=dict(text="Metric t", font=dict(size=12, color="#6f7882")),
                           tickformat=",", showline=True, linecolor="#9aa1a9", linewidth=1.2,
                           showticklabels=True, tickfont=dict(size=12, color="#6f7882"),
                           gridcolor="#e6eaed", zeroline=False),
                yaxis2=dict(title=dict(text="Recovery %", font=dict(size=11, color="#2D4A5A")),
                            overlaying="y", side="right", range=[0, 110], ticksuffix="%",
                            showgrid=False, showline=True, linecolor="#9aa1a9",
                            tickfont=dict(size=12, color="#6f7882")),
                hovermode="x unified",
            )
            apply_chart_animation(fig4)
            st.plotly_chart(fig4, use_container_width=True)

        with c2:
            # Waste recovery % trend — more useful than a static gauge
            rec_pcts = [yr_kpis[y]["waste_pct"] for y in ys]
            fig_rec = go.Figure()
            # Background zones
            fig_rec.add_hrect(y0=0,  y1=70,  fillcolor="#FEE2E2", opacity=0.25, line_width=0)
            fig_rec.add_hrect(y0=70, y1=85,  fillcolor="#FEF3C7", opacity=0.25, line_width=0)
            fig_rec.add_hrect(y0=85, y1=100, fillcolor="#DCFCE7", opacity=0.25, line_width=0)
            # 90% best-practice target line
            fig_rec.add_hline(y=90, line_dash="dot", line_color=GREEN,
                              line_width=1.5, annotation_text="Target 90%",
                              annotation_font=dict(size=9, color=GREEN))
            # Recovery trend
            fig_rec.add_trace(go.Scatter(
                x=list(range(len(ys))), y=rec_pcts, mode="lines+markers",
                fill="tozeroy",
                fillcolor="rgba(123,175,116,0.12)",    # TIP bar_green faint
                line=dict(color="#465c66", width=2.2),  # TIP_SPRUCE
                marker=dict(size=7, color="#f5f4f2", symbol="circle",
                            line=dict(color="#465c66", width=2)),
                hovertemplate="<b>%{x}</b><br>Recovery: %{y:.1f}%<extra></extra>",
                name="Recovery %",
            ))
            fig_rec.update_layout(
                **chart_layout_defaults("Waste Recovery Trend (%)", height=300,
                                        showlegend=False),
                yaxis=dict(range=[0, 105], ticksuffix="%", gridcolor="#e6eaed",
                           showline=True, linecolor="#9aa1a9", linewidth=1.2,
                           showticklabels=True, tickfont=dict(size=12, color="#6f7882"),
                           zeroline=False),
                xaxis=dict(showgrid=False, showline=True, linecolor="#9aa1a9"),
            )
            apply_chart_animation(fig_rec)
            st.plotly_chart(fig_rec, use_container_width=True)

    # ── Historical KPI summary table ──────────────────────────────────────────
    st.markdown('<div style="height:8px"></div>', unsafe_allow_html=True)
    st.markdown(f"**Historical KPI Summary — {company}**")

    import pandas as pd
    tbl_rows = []
    table_years = sorted([y for y in years if 2014 <= y <= 2023], reverse=True)
    for y in table_years:
        sd = dl.get_step_data(comp_hist, y)
        sc = {k: v for k, v in sd.items() if k in valid}
        o  = calc(TI(company=company, year=y, **sc))
        ii = TI(company=company, year=y, **sc)
        rt = max(ii.renew_elec_purchased + ii.nonrenew_elec_purchased + ii.self_gen_elec, 1)
        tbl_rows.append({
            "Year":              y,
            "Production (MT)":   f"{ii.production/1e6:.3f}",
            "CO₂ Total (T)":     f"{o.total_co2:,.0f}",
            "CO₂ Intensity":     f"{o.co2_kpi:.3f}",
            "Energy KPI (GJ/t)": f"{o.energy_kpi:.2f}",
            "Renew. Elec. %":    f"{ii.renew_elec_purchased/rt*100:.1f}%",
            "Water KPI (m³/t)":  f"{o.water_kpi:.2f}",
            "Waste Recovery %":  f"{o.waste_recovery_pct*100:.1f}%",
        })
    tbl_df = pd.DataFrame(tbl_rows)
    st.dataframe(
        tbl_df.style
            .set_properties(**{"text-align": "right", "font-size": "12px"})
            .set_table_styles([
                {"selector": "th", "props": [
                    ("font-size","11px"), ("text-transform","uppercase"),
                    ("letter-spacing",".4px"), ("color","#64748B"),
                    ("background","#F8FAFC"), ("padding","8px 12px"),
                ]},
                {"selector": "td:first-child", "props": [
                    ("font-weight","600"), ("color","#0F172A"), ("text-align","center"),
                ]},
            ]),
        use_container_width=True, hide_index=True,
    )