"""
pages/page_benchmarking.py — Benchmarking tabs (CO₂, Energy, Water, Waste) + PDF download.
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


def page_benchmarking():
    """
    Benchmarking — KPI-topic tabs (General, CO₂, Energy, Electricity, Water, Waste).
    Client: no company selector (own company only).
    DSS+: company dropdown.
    No peer company names exposed in any chart.
    PDF download available per tab.
    """
    from pdf.pdf_report import generate_executive_pdf, build_kpi_dict_from_outputs, REPORTLAB_OK
    import io

    # ── Hero card (matches My Dashboard style) ────────────────────────────────
    NAVY_DARK = "#0F2540"
    NAVY_MID  = "#1A3A5C"

    st.markdown(f"""
    <style>
    .bench-hero {{
        background: linear-gradient(135deg, {NAVY_DARK} 0%, {NAVY_MID} 100%);
        border-radius: 12px; padding: 22px 28px; margin-bottom: 18px;
        display: flex; justify-content: space-between; align-items: flex-start;
    }}
    .bench-hero-eyebrow {{ font-size: 11px; letter-spacing: .06em; text-transform: uppercase;
                          color: rgba(255,255,255,.55); margin-bottom: 6px; }}
    .bench-hero-title {{ font-size: 30px; font-weight: 800; color: white; line-height: 1.2; }}
    .bench-hero-sub {{ font-size: 12.5px; color: rgba(255,255,255,.7); margin-top: 4px; }}
    .bench-hero-year-label {{ font-size: 10px; color: rgba(255,255,255,.5); text-align: right;
                             text-transform: uppercase; letter-spacing: .05em; }}
    .bench-hero-year {{ font-size: 30px; font-weight: 700; color: white; text-align: right; line-height: 1; }}
    .bench-hero-badge {{ font-size: 10.5px; color: #6EE7B7; text-align: right; margin-top: 4px; }}
    </style>
    """, unsafe_allow_html=True)

    companies_in_db = dl.get_companies(state.CONSOLIDATED_DF) or state.COMPANIES
    is_dss = st.session_state.get("is_dss", False)

    # ── Company selector (DSS only) ───────────────────────────────────────────
    _b_range_opts = {
        "Last 3 years":  3,  "Last 5 years":  5,  "Last 7 years":  7,
        "Last 8 years":  8,  "Last 10 years": 10, "Last 12 years": 12, "All": 0,
    }
    if is_dss:
        default_co = (st.session_state.get("reporting_company") or
                      st.session_state.get("user_company") or companies_in_db[0])
        if default_co not in companies_in_db: default_co = companies_in_db[0]
        bc1, _ = st.columns([3, 1])
        with bc1:
            company = st.selectbox("Company", companies_in_db,
                                   index=companies_in_db.index(default_co),
                                   key="bench_company_dss")
    else:
        company = st.session_state.user_company

    # Time range — derived from widget below, default "Last 5 years"
    _b_range_lbl = st.session_state.get("bench_year_range", "Last 5 years")


    # ── Derive rep_year automatically (most recent year in range with data) ──────
    _bn      = _b_range_opts[_b_range_lbl]
    _all_db_yrs = sorted(dl.get_years(state.CONSOLIDATED_DF, company) or [state.CURR_YEAR])
    _avail_in_range = ([y for y in _all_db_yrs if not _bn or y >= (_all_db_yrs[-1] - _bn + 1)]
                       or _all_db_yrs)
    rep_year = max(_avail_in_range)

    # ── Load data ─────────────────────────────────────────────────────────────
    inp, out = _load_company_year_outputs(company, rep_year)
    bench_kpis = dl.get_benchmark_kpis(state.CONSOLIDATED_DF, rep_year)
    renew_val  = (inp.renew_elec_purchased + inp.self_gen_elec) / max(out.total_electricity, 1) * 100
    waste_pct  = out.waste_recovery_pct * 100

    # ── Hero card ─────────────────────────────────────────────────────────────
    st.markdown(f'''<div class="bench-hero">
        <div>
            <div class="bench-hero-eyebrow">Tire Industry Platform</div>
            <div class="bench-hero-title">{company}</div>
            <div class="bench-hero-sub">ESG Performance Benchmarking</div>
        </div>
        <div>
            <div class="bench-hero-year-label">Reporting Year</div>
            <div class="bench-hero-year">{rep_year}</div>
        </div>
    </div>''', unsafe_allow_html=True)


    def live_bench(col, val, unit, lb):
        vals = bench_kpis[col].dropna().values if (not bench_kpis.empty and col in bench_kpis.columns) else []
        if len(vals) >= 3:
            q25, med, q75 = (float(np.percentile(vals, p)) for p in [25, 50, 75])
            lo,  hi       = float(np.percentile(vals, 10)), float(np.percentile(vals, 90))
        else:
            # FALLBACK when <3 peer submissions: assume ±15% and ±30% margins around company value
            # Methodology: 25th percentile = 85% of value, median = 100%, 75th = 115%
            #              10th percentile = 70% of value, 90th = 130%
            # TODO: Document the official benchmark methodology and data source for this fallback
            # TODO: Post-Azure, query live sector percentiles from SQL instead of using fixed percentages
            q25, med, q75, lo, hi = val*.85, val, val*1.15, val*.7, val*1.3
        b = BenchmarkResult(col, val, q25, med, q75, unit, lb)
        b._lo, b._hi, b._vals = lo, hi, vals
        return b

    BM = [
        live_bench("Total CO2 - KPI",              out.co2_kpi,  "tCO₂/t", True),
        live_bench("Total energy - KPI",            out.energy_kpi,"GJ/t",   True),
        live_bench("Water intake - KPI",            out.water_kpi, "m³/t",   True),
        live_bench("Renewable_Electricity_Share_%", renew_val,     "%",      False),
        live_bench("Waste_Recovery_Rate_%",         waste_pct,     "%",      False),
    ]
    KPI_NAMES = ["CO₂ Intensity","Energy Intensity","Water Intensity","Renewable Elec.","Waste Recovery"]
    KPI_COLORS = [CAT_CO2, CAT_ENERGY, CAT_WATER, CAT_RENEW, CAT_WASTE]
    for b, n in zip(BM, KPI_NAMES): b.kpi_name = n

    # ── KPI comparison cards: Company vs TIP aggregate ───────────────────────
    # Find the best year: latest year where sector has ≥2 companies (real peers)
    def _best_kpi_year():
        if state.CONSOLIDATED_DF.empty: return rep_year
        for yr in sorted(state.CONSOLIDATED_DF["Year"].unique(), reverse=True):
            n = state.CONSOLIDATED_DF[state.CONSOLIDATED_DF["Year"] == yr]["Company"].nunique()
            if n >= 2:
                return int(yr)
        return rep_year  # fallback to rep_year even if single company

    _kpi_year = _best_kpi_year()
    _kpi_year_note_needed = (_kpi_year != rep_year)

    # Load company KPIs for _kpi_year
    _inp_ky, _out_ky = _load_company_year_outputs(company, _kpi_year)
    _renew_ky = (_inp_ky.renew_elec_purchased + _inp_ky.self_gen_elec) / max(_out_ky.total_electricity, 1) * 100
    _waste_ky = _out_ky.waste_recovery_pct * 100

    def _peer_kpi(col):
        """Mean of col for _kpi_year across all companies EXCEPT current company."""
        if state.CONSOLIDATED_DF.empty or col not in state.CONSOLIDATED_DF.columns:
            return None
        peers = state.CONSOLIDATED_DF[
            (state.CONSOLIDATED_DF["Year"] == _kpi_year) &
            (state.CONSOLIDATED_DF["Company"] != company)
        ]
        if peers.empty: return None
        v = peers[col].dropna()
        return float(v.mean()) if not v.empty else None

    _n_peers = 0
    if not state.CONSOLIDATED_DF.empty:
        _n_peers = state.CONSOLIDATED_DF[
            (state.CONSOLIDATED_DF["Year"] == _kpi_year) &
            (state.CONSOLIDATED_DF["Company"] != company)
        ]["Company"].nunique()

    tip_co2_kpi    = _peer_kpi("Total CO2 - KPI")
    tip_energy_kpi = _peer_kpi("Total energy - KPI")
    tip_water_kpi  = _peer_kpi("Water intake - KPI")
    tip_renew_kpi  = _peer_kpi("Renewable_Electricity_Share_%")
    tip_waste_kpi  = _peer_kpi("Waste_Recovery_Rate_%")

    _co_short = company.split()[0] if company else "Company"
    _tip_lbl  = "TIP avg" if _n_peers > 0 else "TIP avg*"

    KPI_DEF = [
        ("CO₂ Intensity",    _out_ky.co2_kpi,    tip_co2_kpi,    "tCO₂/t", CAT_CO2,    True),
        ("Energy Intensity", _out_ky.energy_kpi, tip_energy_kpi, "GJ/t",   CAT_ENERGY, True),
        ("Water Intensity",  _out_ky.water_kpi,  tip_water_kpi,  "m³/t",   CAT_WATER,  True),
        ("Renewable Elec.",  _renew_ky,           tip_renew_kpi,  "%",      CAT_RENEW,  False),
        ("Waste Recovery",   _waste_ky,           tip_waste_kpi,  "%",      CAT_WASTE,  False),
    ]

    chip_cols = st.columns(5)
    for i, (name, co_val, tip_avg, unit, color, lower_is_better) in enumerate(KPI_DEF):
        tip_str = f"{tip_avg:.2f}" if tip_avg is not None else "N/A"

        with chip_cols[i]:
            st.markdown(f"""
            <div style="background:#fff;border:1px solid {BORDER};border-radius:8px;
                padding:12px 14px;animation:tipFadeIn 400ms ease-out {i*60}ms both;text-align:center">
              <div style="font-size:9.5px;color:{MUTED};font-weight:600;text-transform:uppercase;
                  letter-spacing:.5px;margin-bottom:8px">{name}</div>
              <div style="display:flex;justify-content:center;align-items:flex-end;gap:12px">
                <div style="text-align:center">
                  <div style="font-size:9px;color:{MUTED};margin-bottom:2px">{_co_short}</div>
                  <div style="font-size:22px;font-weight:700;color:{color};
                      font-variant-numeric:tabular-nums;line-height:1">{co_val:.2f}</div>
                  <div style="font-size:9px;color:{MUTED};margin-top:2px">{unit}</div>
                </div>
                <div style="width:1px;height:36px;background:{BORDER};margin-bottom:6px"></div>
                <div style="text-align:center">
                  <div style="font-size:9px;color:{MUTED};margin-bottom:2px">{_tip_lbl}</div>
                  <div style="font-size:22px;font-weight:700;color:{MUTED};
                      font-variant-numeric:tabular-nums;line-height:1">{tip_str}</div>
                  <div style="font-size:9px;color:{MUTED};margin-top:2px">{unit}</div>
                </div>
              </div>
            </div>""", unsafe_allow_html=True)

    # ── Footnote about which year scores are from ─────────────────────────────
    if _kpi_year_note_needed:
        st.markdown(
            f"<div style='font-size:11px;color:{MUTED};margin-top:2px;margin-bottom:0px'>"
            f"Scores shown for <b>{_kpi_year}</b> (most recent year with full sector data). "
            f"<b>{rep_year}</b> TIP member submissions are still being collected — "
            f"benchmarks will update once all members have reported.</div>",
            unsafe_allow_html=True)
    elif _n_peers == 0:
        st.markdown(
            f"<div style='font-size:11px;color:{MUTED};margin-top:2px;margin-bottom:0px'>"
            f"Only {company}'s data is available for {_kpi_year}. "
            f"TIP avg will reflect peer benchmarks once other member submissions are received.</div>",
            unsafe_allow_html=True)

    # ── KPI Tabs + Time range ─────────────────────────────────────────────────
    # Negative margin pulls the dropdown row up to visually align with tab bar
    st.markdown("""<style>
    .bench-range-row { margin-bottom: -48px; margin-top: 6px; position: relative; z-index: 0; }
    </style>""", unsafe_allow_html=True)
    st.markdown("<div class='bench-range-row'></div>", unsafe_allow_html=True)
    _spacer, _range_col = st.columns([5, 1])
    with _range_col:
        _b_range_lbl = st.selectbox(
            "Time range", list(_b_range_opts.keys()),
            index=list(_b_range_opts.keys()).index(
                st.session_state.get("bench_year_range", "Last 5 years")),
            key="bench_year_range",
            label_visibility="collapsed",
        )

    tab_energy, tab_co2, tab_water, tab_waste, tab_people = st.tabs([
        "Energy & Certifications", "CO₂ Emissions", "Water", "Waste", "People & Governance"
    ])
    comp_hist = dl.get_company_hist(state.CONSOLIDATED_DF, company)
    all_years = sorted(dl.get_years(state.CONSOLIDATED_DF, company) or [rep_year])
    from formula_engine import TemplateInputs as TI, calculate as calc
    valid_flds = {f.name for f in TI.__dataclass_fields__.values()}

    def _co_trend(field_key):
        """Return dict year→value for a computed KPI across all years."""
        result = {}
        for y in all_years:
            sd = dl.get_step_data(comp_hist, y)
            sc = {k: v for k, v in sd.items() if k in valid_flds}
            if not sc: continue
            o  = calc(TI(company=company, year=y, **sc))
            ii = TI(company=company, year=y, **sc)
            rt = max(ii.renew_elec_purchased + ii.nonrenew_elec_purchased + ii.self_gen_elec, 1)
            result[y] = {
                "co2_kpi": o.co2_kpi, "energy_kpi": o.energy_kpi,
                "water_kpi": o.water_kpi, "waste_pct": o.waste_recovery_pct*100,
                "renew_pct": ii.renew_elec_purchased / rt * 100,
                "nonrenew_pct": ii.nonrenew_elec_purchased / rt * 100,
                "renew_gj": ii.renew_elec_purchased,
                "nonrenew_gj": ii.nonrenew_elec_purchased,
                "nat_gas": ii.nat_gas, "coal": ii.coal_sub,
                "diesel": ii.diesel, "biomass": ii.biomass,
                "water_m3": ii.water_withdrawals,
                "waste_total": ii.waste_total, "waste_rec": ii.waste_recovery,
                "scope1": o.total_co2_scope1, "scope2": o.total_co2_scope2,
            }
        return result

    trend   = _co_trend(None)
    _all_ys = sorted(trend.keys())
    ys = _all_ys[-_bn:] if _bn else _all_ys

    def _sector_series(col):
        """Sector mean, p25, p75 by year."""
        if state.CONSOLIDATED_DF.empty or col not in state.CONSOLIDATED_DF.columns:
            return {}, {}, {}
        grp = state.CONSOLIDATED_DF.groupby("Year")[col]
        return (grp.mean().to_dict(), grp.quantile(.25).to_dict(),
                grp.quantile(.75).to_dict())

    def _anon_scatter(col, your_val, color, title, xlab, ylab, x_col=None):
        """Scatter plot of all peer values — anonymous dots + your company highlighted."""
        fig = go.Figure()
        yr_df = state.CONSOLIDATED_DF[state.CONSOLIDATED_DF["Year"] == rep_year]
        if not yr_df.empty and col in yr_df.columns:
            peer_vals = yr_df[yr_df["Company"] != company][col].dropna()
            x_vals    = (yr_df[yr_df["Company"] != company][x_col].dropna()
                         if x_col else pd.Series([None]*len(peer_vals)))
            # Anonymous peers
            for j, (idx, pv) in enumerate(peer_vals.items()):
                xv = float(yr_df.loc[idx, x_col]) if x_col and idx in yr_df.index else j+1
                fig.add_trace(go.Scatter(
                    x=[xv], y=[pv], mode="markers",
                    marker=dict(size=9, color="#CBD5E1",
                                line=dict(color="white", width=1)),
                    name=f"Peer {j+1}", showlegend=False,
                    hovertemplate=f"Peer: {pv:.3f}<extra></extra>",
                ))
        # Your company
        fig.add_trace(go.Scatter(
            x=[your_val if not x_col else float(
                state.CONSOLIDATED_DF[(state.CONSOLIDATED_DF["Company"]==company) &
                (state.CONSOLIDATED_DF["Year"]==rep_year)].get(x_col, pd.Series([your_val])).iloc[0])],
            y=[your_val], mode="markers+text",
            marker=dict(size=14, color=color, symbol="diamond",
                        line=dict(color="white", width=2)),
            text=[company.split()[0]], textposition="top center",
            textfont=dict(size=10, color=color, family="Inter"),
            name="You", showlegend=False,
            hovertemplate=f"<b>You</b>: {your_val:.3f}<extra></extra>",
        ))
        fig.update_layout(**chart_layout_defaults(title, height=250, showlegend=False),
                          xaxis=dict(title=dict(text=xlab, font=dict(size=12, color="#6f7882")),
                                     showgrid=False, showline=True, linecolor="#9aa1a9"),
                          yaxis=dict(title=dict(text=ylab, font=dict(size=12, color="#6f7882")),
                                     gridcolor="#e6eaed", showline=True, linecolor="#9aa1a9"))
        apply_chart_animation(fig)
        return fig

    def _trend_vs_sector(kpi_key, sec_col, label, color, show_quartiles=True):
        """Company trend line vs sector IQR band with Q1/Median/Q3 reference lines.
        Uses string x-axis (categorical) to prevent float interpolation."""
        sec_mean, sec_q25, sec_q75 = _sector_series(sec_col)
        # Only show years that are IN the selected time range (ys)
        # This ensures sector bands and company lines cover exactly the same window
        _ys_int = ys   # integers, already range-filtered
        # For sector: only include years from ys that have sector data
        yr_list  = [y for y in sorted(_ys_int) if y in sec_mean]
        # For company: only include years from ys that have company trend data
        yr_str   = [str(y) for y in yr_list]
        ys_str   = [str(y) for y in _ys_int if y in trend]

        fig = go.Figure()
        # IQR band (Q1–Q3 shaded)
        fig.add_trace(go.Scatter(
            x=yr_str, y=[sec_q75.get(y) for y in yr_list],
            fill=None, mode="lines", line=dict(width=0), showlegend=False,
            name="Q3"))
        r, g, b = int(color[1:3],16), int(color[3:5],16), int(color[5:7],16)
        fig.add_trace(go.Scatter(
            x=yr_str, y=[sec_q25.get(y) for y in yr_list],
            fill="tonexty", mode="lines", line=dict(width=0),
            fillcolor=f"rgba({r},{g},{b},0.12)",
            name="Sector IQR (Q1–Q3)",
        ))
        if show_quartiles:
            fig.add_trace(go.Scatter(
                x=yr_str, y=[sec_q25.get(y) for y in yr_list],
                mode="lines", name="Q1 (25th pct)",
                line=dict(color="#9aa1a9", width=1, dash="dot"),
                hovertemplate="Q1: %{y:.3f}<extra></extra>",
            ))
            fig.add_trace(go.Scatter(
                x=yr_str, y=[sec_mean.get(y) for y in yr_list],
                mode="lines", name="Sector Median",
                line=dict(color="#6f7882", width=1.5, dash="dashdot"),
                hovertemplate="Median: %{y:.3f}<extra></extra>",
            ))
            fig.add_trace(go.Scatter(
                x=yr_str, y=[sec_q75.get(y) for y in yr_list],
                mode="lines", name="Q3 (75th pct)",
                line=dict(color="#9aa1a9", width=1, dash="dot"),
                hovertemplate="Q3: %{y:.3f}<extra></extra>",
            ))
        # Company line — only years that exist in trend data
        co_y = [trend[y][kpi_key] for y in _ys_int if y in trend]
        fig.add_trace(go.Scatter(
            x=ys_str, y=co_y, mode="lines",
            name=company.split()[0],
            line=dict(color=color, width=2.2),
            marker=dict(size=7, color="#f5f4f2", line=dict(color=color, width=2)),
            hovertemplate="%{y:.3f}<extra>" + company.split()[0] + "</extra>",
        ))
        fig.update_layout(**chart_layout_defaults(label, height=430),
                          yaxis=dict(
                              gridcolor="#e6eaed",
                              tickfont=dict(size=12, color="#6f7882", family="Arial"),
                              showline=True, linecolor="#9aa1a9", linewidth=1.2,
                              showticklabels=True,
                          ),
                          yaxis2=dict(
                              tickfont=dict(size=12, color="#6f7882", family="Arial"),
                              showgrid=False, showline=True, linecolor="#9aa1a9",
                              showticklabels=True,
                          ),
                          xaxis=dict(
                              showgrid=False, type="category",
                              tickfont=dict(size=12, color="#6f7882", family="Arial"),
                              showline=True, linecolor="#9aa1a9", linewidth=1.2,
                              showticklabels=True,
                          ))
        apply_chart_animation(fig)
        return fig

    def _pdf_download_btn(label: str, key: str, figs_data: list = None):
        """
        Generate a multi-section benchmarking PDF using matplotlib (no kaleido).
        figs_data: list of (section_title, chart_type, *data_args) tuples.
        """
        import sys, os
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        try:
            import pdf.pdf_charts_v2 as pc
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.units    import mm
            from reportlab.pdfgen       import canvas as rl_canvas
            from reportlab.lib.utils    import ImageReader
            import io as _io

            W, H = A4; MARGIN = 14*mm; CW = W - 2*MARGIN
            buf = _io.BytesIO()
            c   = rl_canvas.Canvas(buf, pagesize=A4)

            # Cover header
            c.setFillColor((10/255, 34/255, 64/255))
            c.rect(0, H - 26*mm, W, 26*mm, fill=1, stroke=0)
            c.setFont("Helvetica-Bold", 13)
            c.setFillColor((1,1,1))
            c.drawString(MARGIN, H - 12*mm, f"{company}  ·  {rep_year}  —  {label} Benchmarking")
            c.setFont("Helvetica", 8)
            c.setFillColor((0.55, 0.65, 0.75))
            c.drawString(MARGIN, H - 20*mm, "TIP ESG Platform  ·  dss+ consulting  ·  WBCSD Tire Industry Project")
            cursor = H - 30*mm

            def _embed(img_bytes, title="", h=62*mm):
                nonlocal cursor
                if cursor - h < MARGIN + 10*mm:
                    c.showPage(); cursor = H - MARGIN
                if title:
                    c.setFont("Helvetica-Bold", 9); c.setFillColor((10/255,34/255,64/255))
                    c.drawString(MARGIN, cursor - 5*mm, title); cursor -= 7*mm
                reader = ImageReader(_io.BytesIO(img_bytes))
                c.drawImage(reader, MARGIN, cursor - h, width=CW, height=h,
                            preserveAspectRatio=True)
                cursor -= h + 5*mm

            if figs_data:
                # Compute sector series once for trend charts
                def _ss(col):
                    if state.CONSOLIDATED_DF.empty or col not in state.CONSOLIDATED_DF.columns:
                        return {}, {}, {}
                    grp = state.CONSOLIDATED_DF.groupby("Year")[col]
                    return grp.mean().to_dict(), grp.quantile(.25).to_dict(), grp.quantile(.75).to_dict()

                for item in figs_data:
                    kind = item[0]
                    if kind == "radar":
                        _, dims, co_sc, sec_sc, co_name = item
                        _embed(pc.radar_chart(dims, co_sc, sec_sc, co_name), "ESG Performance Radar")
                    elif kind == "position_bar":
                        _, names, positions, colors_list = item
                        _embed(pc.position_bar(names, positions, colors_list), "Sector Percentile Position")
                    elif kind == "improvement_table":
                        _, rows = item
                        # Simple text table
                        if rows:
                            c.setFont("Helvetica-Bold", 9)
                            c.setFillColor((10/255,34/255,64/255))
                            c.drawString(MARGIN, cursor - 4*mm, "Improvement Summary")
                            cursor -= 7*mm
                            c.setFont("Helvetica", 8)
                            for row in rows:
                                c.setFillColor((10/255,34/255,64/255))
                                kpi_txt = str(row.get("KPI",""))
                                val_txt = str(list(row.values())[-1])
                                c.drawString(MARGIN, cursor - 4*mm, f"• {kpi_txt}: {val_txt}")
                                cursor -= 5*mm
                    elif kind == "line_vs_sector":
                        _, sec_col, kpi_key, title_str, color = item
                        sm, sq25, sq75 = _ss(sec_col)
                        co_y = [trend.get(y, {}).get(kpi_key) for y in ys]
                        _embed(pc.line_vs_sector(ys, co_y, sm, sq25, sq75,
                               company.split()[0], title_str, color=color), title_str)
                    elif kind == "stacked_area_scope":
                        _, title_str = item
                        _embed(pc.stacked_area(ys,
                            {"Scope 1": [trend.get(y,{}).get("scope1",0) for y in ys],
                             "Scope 2": [trend.get(y,{}).get("scope2",0) for y in ys]},
                            title_str, color_dict={"Scope 1": pc.C["co2"], "Scope 2": "#94A3B8"}),
                            title_str)
                    elif kind == "energy_mix_bar":
                        _, title_str = item
                        fuel_map = {
                            "Nat. Gas": [trend.get(y,{}).get("nat_gas",0) for y in ys],
                            "Renew. Elec": [trend.get(y,{}).get("renew_gj",0) for y in ys],
                            "Non-Renew.": [trend.get(y,{}).get("nonrenew_gj",0) for y in ys],
                            "Coal":     [trend.get(y,{}).get("coal",0) for y in ys],
                            "Diesel":   [trend.get(y,{}).get("diesel",0) for y in ys],
                        }
                        cmap = {"Nat. Gas":pc.C["energy"],"Renew. Elec":pc.C["green"],
                                "Non-Renew.":"#94A3B8","Coal":"#475569","Diesel":"#78716C"}
                        _embed(pc.stacked_bar(ys, fuel_map, title_str, color_dict=cmap), title_str)
                    elif kind == "elec_mix_bar":
                        _, title_str = item
                        total_e = [max(trend.get(y,{}).get("renew_gj",0)+trend.get(y,{}).get("nonrenew_gj",0),1) for y in ys]
                        _embed(pc.stacked_bar(ys, {
                            "Renewable":     [trend.get(y,{}).get("renew_gj",0)/t*100 for y,t in zip(ys,total_e)],
                            "Non-Renewable": [trend.get(y,{}).get("nonrenew_gj",0)/t*100 for y,t in zip(ys,total_e)],
                        }, title_str, color_dict={"Renewable":pc.C["green"],"Non-Renewable":"#94A3B8"},
                        pct_mode=True), title_str)
                    elif kind == "water_bar":
                        _, title_str = item
                        _embed(pc.bar_chart(ys, [trend.get(y,{}).get("water_m3",0)/1e6 for y in ys],
                               title_str, "M m³", color=pc.C["water"]), title_str)
                    elif kind == "waste_area":
                        _, title_str = item
                        _embed(pc.area_with_target(ys, [trend.get(y,{}).get("waste_pct",0) for y in ys],
                               title_str, "%", color=pc.C["waste"]), title_str)
                    elif kind == "waste_bar":
                        _, title_str = item
                        _embed(pc.stacked_bar(ys, {
                            "Total Waste": [trend.get(y,{}).get("waste_total",0) for y in ys],
                            "Recovered":   [trend.get(y,{}).get("waste_rec",0)   for y in ys],
                        }, title_str, color_dict={"Total Waste":"#E2E8F0","Recovered":pc.C["waste"]}),
                        title_str)

            c.save(); buf.seek(0); pdf_bytes = buf.read()
            st.download_button(
                f"⬇  Download {label} Report (PDF)",
                data=pdf_bytes,
                file_name=f"{company.replace(' ','_')}_{label.replace(' ','_')}_{rep_year}_Benchmark.pdf",
                mime="application/pdf", key=key, use_container_width=True,
            )
        except Exception as e:
            st.error(f"PDF generation failed: {e}. Make sure pdf_charts_v2.py and reportlab are installed.")

    # ── Full combined PDF — all sections in one document ─────────────────────
    def _full_bench_pdf():
        """Generate one PDF with all 6 benchmark sections: General → Waste."""
        import sys as _sys, os as _os
        _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
        try:
            import pdf.pdf_charts_v2 as pc
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.units    import mm
            from reportlab.pdfgen       import canvas as rl_canvas
            from reportlab.lib.utils    import ImageReader
            import io as _io

            W, H = A4; MARGIN = 14*mm; CW = W - 2*MARGIN
            buf = _io.BytesIO()
            cv  = rl_canvas.Canvas(buf, pagesize=A4)

            def _cover():
                cv.setFillColor((10/255, 34/255, 64/255))
                cv.rect(0, H - 30*mm, W, 30*mm, fill=1, stroke=0)
                cv.setFont("Helvetica-Bold", 14); cv.setFillColor((1,1,1))
                cv.drawString(MARGIN, H - 13*mm, f"{company}  ·  ESG Benchmarking Report  ·  {rep_year}")
                cv.setFont("Helvetica", 8); cv.setFillColor((.55,.65,.75))
                cv.drawString(MARGIN, H-21*mm, "TIP ESG Platform  ·  dss+ consulting  ·  WBCSD Tire Industry Project")

            def _section_title(cv, title, cursor):
                cv.setFillColor((.94,.95,.98)); cv.rect(MARGIN, cursor-9*mm, CW, 9*mm, fill=1, stroke=0)
                cv.setFillColor((10/255,34/255,64/255)); cv.rect(MARGIN, cursor-9*mm, 2.5, 9*mm, fill=1, stroke=0)
                cv.setFont("Helvetica-Bold", 11); cv.setFillColor((10/255,34/255,64/255))
                cv.drawString(MARGIN+5, cursor-6*mm, title)
                return cursor - 11*mm

            def _embed(cv, img_bytes, cursor, caption="", h=60*mm):
                if cursor - h < MARGIN + 15*mm:
                    cv.showPage(); _cover(); cursor = H - 34*mm
                if caption:
                    cv.setFont("Helvetica", 8); cv.setFillColor((.4,.4,.4))
                    cv.drawString(MARGIN, cursor-4*mm, caption); cursor -= 6*mm
                reader = ImageReader(_io.BytesIO(img_bytes))
                cv.drawImage(reader, MARGIN, cursor-h, width=CW, height=h, preserveAspectRatio=True)
                return cursor - h - 4*mm

            def _ss(col):
                if state.CONSOLIDATED_DF.empty or col not in state.CONSOLIDATED_DF.columns:
                    return {},{},{}
                grp = state.CONSOLIDATED_DF.groupby("Year")[col]
                return grp.mean().to_dict(), grp.quantile(.25).to_dict(), grp.quantile(.75).to_dict()

            _cover()
            cursor = H - 34*mm

            # ── CO₂ ──────────────────────────────────────────────────────────
            cursor = _section_title(cv, "CO₂ — Total Emissions & Intensity", cursor)
            tip_co2_abs, _, _ = _sector_series("Total CO2")
            tip_co2_kpi, _, _ = _sector_series("Total CO2 - KPI")
            co2_tip  = [tip_co2_abs.get(y, 0) for y in ys]
            co2_co   = [trend.get(y,{}).get("scope1",0) + trend.get(y,{}).get("scope2",0) for y in ys]
            int_tip  = [tip_co2_kpi.get(y, 0) for y in ys]
            int_co   = [trend.get(y,{}).get("co2_kpi",0) for y in ys]
            cursor = _embed(cv, pc.grouped_bar_line(
                ys, co2_tip, co2_co, int_tip, int_co,
                "Total CO₂ — TIP vs Company (tCO₂)",
                "Total CO₂ (tCO₂)", "CO₂ Intensity (tCO₂/t)",
                bar1_label="TIP", bar2_label=company.split()[0],
                line1_label="Intensity (TIP)", line2_label="Intensity (Co.)",
                bar1_color="#3DBDB5", bar2_color="#1A1A2E"),
                cursor, "TIP sector aggregate vs company · intensity on right axis")
            cursor = _embed(cv, pc.stacked_bar(ys,
                {"Scope 1":[trend.get(y,{}).get("scope1",0) for y in ys],
                 "Scope 2":[trend.get(y,{}).get("scope2",0) for y in ys]},
                "Scope 1 vs Scope 2 (tCO₂)",
                color_dict={"Scope 1":"#3DBDB5","Scope 2":"#0F7F78"}),
                cursor, "Scope 1 = fuel combustion · Scope 2 = purchased energy")

            # ── Energy ────────────────────────────────────────────────────────
            cursor = _section_title(cv, "Energy — Intensity & Fuel Mix", cursor)
            tip_e_abs, _, _ = _sector_series("Total energy")
            tip_e_kpi, _, _ = _sector_series("Total energy - KPI")
            e_tip  = [tip_e_abs.get(y,0)/1e6 for y in ys]   # PJ
            e_co   = [sum([trend.get(y,{}).get(k,0) for k in ["nat_gas","coal","diesel","renew_gj","nonrenew_gj"]])/1e6 for y in ys]
            ei_tip = [tip_e_kpi.get(y,0) for y in ys]
            ei_co  = [trend.get(y,{}).get("energy_kpi",0) for y in ys]
            cursor = _embed(cv, pc.grouped_bar_line(
                ys, e_tip, e_co, ei_tip, ei_co,
                "Total Energy — TIP vs Company (PJ)",
                "Total Energy (PJ)", "Energy Intensity (GJ/t)",
                bar1_label="TIP", bar2_label=company.split()[0],
                line1_label="Intensity (TIP)", line2_label="Intensity (Co.)",
                bar1_color="#3DBDB5", bar2_color="#1A1A2E"),
                cursor, "TIP sector aggregate vs company · intensity on right axis")
            cursor = _embed(cv, pc.stacked_bar(ys,
                {"Nat. Gas":[trend.get(y,{}).get("nat_gas",0) for y in ys],
                 "Renew. Elec":[trend.get(y,{}).get("renew_gj",0) for y in ys],
                 "Diesel":[trend.get(y,{}).get("diesel",0) for y in ys],
                 "Coal":[trend.get(y,{}).get("coal",0) for y in ys]},
                "Energy Mix by Source (GJ)",
                color_dict={"Nat. Gas":"#F5A623","Renew. Elec":"#7BAF74",
                            "Diesel":"#78716C","Coal":"#475569"}),
                cursor, "Fuel mix evolution over selected years")

            # ── Electricity ───────────────────────────────────────────────────
            cursor = _section_title(cv, "Electricity — Renewable vs Non-Renewable", cursor)
            tip_re, _, _ = _sector_series("Renewable Electricity Purchased")
            tip_nr, _, _ = _sector_series("Non-Renewable Electricity Purchased")
            tip_re_pct, tip_nr_pct, co_re_pct, co_nr_pct = [], [], [], []
            for y in ys:
                r = tip_re.get(y,0); n = tip_nr.get(y,0); t = max(r+n,1)
                tip_re_pct.append(r/t*100); tip_nr_pct.append(n/t*100)
                te = max(trend.get(y,{}).get("renew_gj",0)+trend.get(y,{}).get("nonrenew_gj",0),1)
                co_re_pct.append(trend.get(y,{}).get("renew_gj",0)/te*100)
                co_nr_pct.append(trend.get(y,{}).get("nonrenew_gj",0)/te*100)
            cursor = _embed(cv, pc.grouped_stacked_bar(
                ys, tip_re_pct, tip_nr_pct, co_re_pct, co_nr_pct,
                "Electricity from Renewable Sources (%)",
                tip_re_color="#2D4A5A", tip_nr_color="#D4C5A9",
                co_re_color="#3DBDB5", co_nr_color="#B8CDD9",
                tip_label="TIP", co_label=company.split()[0]),
                cursor, "TIP aggregate vs company · renewable share comparison")

            # ── Water ─────────────────────────────────────────────────────────
            cursor = _section_title(cv, "Water — Intensity & Withdrawals", cursor)
            tip_w_abs, _, _ = _sector_series("Water intake")
            tip_w_kpi, _, _ = _sector_series("Water intake - KPI")
            w_tip  = [tip_w_abs.get(y,0)/1e6 for y in ys]
            w_co   = [trend.get(y,{}).get("water_m3",0)/1e6 for y in ys]
            wi_tip = [tip_w_kpi.get(y,0) for y in ys]
            wi_co  = [trend.get(y,{}).get("water_kpi",0) for y in ys]
            cursor = _embed(cv, pc.grouped_bar_line(
                ys, w_tip, w_co, wi_tip, wi_co,
                "Water Withdrawals — TIP vs Company (M m³)",
                "Water (M m³)", "Water Intensity (m³/t)",
                bar1_label="TIP", bar2_label=company.split()[0],
                line1_label="Intensity (TIP)", line2_label="Intensity (Co.)",
                bar1_color="#3DBDB5", bar2_color="#1A1A2E"),
                cursor, "TIP sector aggregate vs company · intensity on right axis")

            # ── Waste ─────────────────────────────────────────────────────────
            cursor = _section_title(cv, "Waste — Generated & Recovery Rate", cursor)
            tip_wst, _, _ = _sector_series("Total Waste")
            tip_wrr, _, _ = _sector_series("Waste_Recovery_Rate_%")
            wst_tip = [tip_wst.get(y,0) for y in ys]
            wst_co  = [trend.get(y,{}).get("waste_total",0) for y in ys]
            wrr_tip = [tip_wrr.get(y,0) for y in ys]
            wrr_co  = [trend.get(y,{}).get("waste_pct",0) for y in ys]
            cursor = _embed(cv, pc.grouped_bar_line(
                ys, wst_tip, wst_co, wrr_tip, wrr_co,
                "Total Waste — TIP vs Company (metric T)",
                "Total Waste (T)", "Recovery Rate (%)",
                bar1_label="TIP", bar2_label=company.split()[0],
                line1_label="Recovery (TIP)", line2_label="Recovery (Co.)",
                bar1_color="#3DBDB5", bar2_color="#1A1A2E"),
                cursor, "TIP sector aggregate vs company · recovery rate on right axis")

            # Footer on last page
            cv.setFillColor((.95,.96,.98)); cv.rect(0,0,W,11*mm,fill=1,stroke=0)
            cv.setFont("Helvetica",6); cv.setFillColor((.4,.4,.4))
            cv.drawString(MARGIN, 5*mm, "TIP ESG Platform · dss+ consulting · WBCSD Tire Industry Project · Methodology: GHG Protocol")
            from datetime import date as _ddate
            cv.drawRightString(W-MARGIN, 5*mm, f"Generated {_ddate.today():%d %b %Y} · {company} · {rep_year}")
            cv.save(); buf.seek(0)
            return buf.read()
        except Exception as ex:
            try:
                import traceback as _tb
                _err = _tb.format_exc().strip().split("\n")[-1]
                st.session_state["_pdf_bench_error"] = _err
            except Exception:
                pass
            return None


    # ── TIP Chart helpers shared with benchmarking ───────────────────────────
    from plotly.subplots import make_subplots as _msp

    _TC = {
        "bar_blue":   "#B8CDD9", "bar_blue2":  "#2D4A5A",
        "bar_beige":  "#C8B49A", "bar_beige2": "#8A7B68",
        "bar_green":  "#7BAF74", "bar_orange": "#E0935A",
        "bar_sand":   "#D4C5A9","bar_committed":"#9FB8C5",
        "line_dark":  "#2D4A5A", "line_light": "#8FA5B5",
    }

    def _blt(title="", h=330, r=115):
        """Benchmarking layout — TIP report design system."""
        return dict(
            title=dict(text=f"<b>{title}</b>",
                       font=dict(size=14, color="#2a2825", family="Arial, sans-serif"), x=0),
            height=h, margin=dict(l=55, r=r, t=50, b=30),
            plot_bgcolor="#f5f4f2", paper_bgcolor="#f5f4f2",
            xaxis=dict(
                showgrid=False, linecolor="#9aa1a9", linewidth=1.2,
                showline=True, mirror=False,
                tickfont=dict(size=12, color="#6f7882", family="Arial"),
                tickangle=0, type="category",
            ),
            yaxis=dict(
                showgrid=True, gridcolor="#e6eaed", zeroline=False,
                showline=True, linecolor="#9aa1a9", linewidth=1.2,
                tickfont=dict(size=12, color="#6f7882", family="Arial"),
                showticklabels=True,
                autorange=True,
            ),
            legend=dict(orientation="h", x=0.5, xanchor="center", y=-0.24,
                        font=dict(size=12, color="#6f7882"), bgcolor="rgba(0,0,0,0)"),
            hovermode="x unified", showlegend=True,
        )

    def _open_mk(col, sz=9):
        return dict(symbol="circle", size=sz, color="white", line=dict(color=col, width=2))

    def _b_dbline(xs, bv, bl, bc, lv, ll, lc, title="", h=430,
                  bfmt=".1f", lfmt=".2f", byt="", lyt=""):
        """Dual-axis bar+line — TIP report style with values in two rows below x-axis.
        Same pattern as _dual() in page_analysis:
          Row 1 (paper y≈0.21): ■ bar label + bar value per year
          Row 2 (paper y≈0.10): —○— line label + line value per year
        Chart area occupies top 68% of figure (domain [0.42, 1.0]).
        """
        n     = len(xs)
        x_idx = list(range(n))

        def _fv(v, fmt):
            if v is None: return ""
            try:
                fv = float(v)
                return "" if fv != fv else format(fv, fmt)
            except Exception:
                return ""

        fig = _msp(specs=[[{"secondary_y": True}]])

        # ── Bar trace (no inline text — values go below x-axis) ──────────────
        fig.add_trace(go.Bar(
            x=x_idx, y=bv, name=bl,
            marker_color=bc, marker_line_width=0, width=0.52,
            hovertemplate=f"{bl}: %{{y:{bfmt}}}<extra></extra>",
            cliponaxis=False,
        ), secondary_y=False)

        # ── Line trace (open-circle markers, no inline text) ─────────────────
        fig.add_trace(go.Scatter(
            x=x_idx, y=lv, name=ll,
            mode="lines",                      # no markers — removes the visible circle
            line=dict(color=lc, width=2.2),
            hovertemplate=f"{ll}: %{{y:{lfmt}}}<extra></extra>",
            cliponaxis=False,
        ), secondary_y=True)

        lay = _blt(title, h, r=115)
        lay["showlegend"] = False   # annotations serve as legend

        # Headroom: 20% above max bar so bars don't clip at domain top
        valid_bv = [v for v in bv if v is not None and v == v]
        if valid_bv:
            lay["yaxis"]["range"] = [0, max(valid_bv) * 1.22]
            lay["yaxis"].pop("autorange", None)
        lay["yaxis"]["title"] = dict(
            text=f"<b>{byt}</b>" if byt else "",
            font=dict(size=12, color="#6f7882", family="Arial"),
        )

        # ── Domain: top 68% for chart, bottom 32% for annotation rows ────────
        lay["yaxis"]["domain"]  = [0.42, 1.0]
        lay["yaxis2"] = dict(
            tickfont=dict(size=12, color="#6f7882", family="Arial"),
            showgrid=False, zeroline=False,
            showline=True, linecolor="#9aa1a9", linewidth=1.2,
            showticklabels=True, autorange=True, domain=[0.42, 1.0],
            title=dict(text=f"<b>{lyt}</b>" if lyt else "",
                       font=dict(size=12, color="#6f7882", family="Arial")),
        )

        # x-axis: numeric indices + year text labels, 18% left gap for y-label
        lay["xaxis"].update(dict(
            domain=[0.18, 1.0],
            tickmode="array",
            tickvals=x_idx,
            ticktext=[str(x) for x in xs],
            type="linear",
        ))
        lay["margin"]["b"] = 30

        fig.update_layout(**lay)
        fig.update_yaxes(showticklabels=True, showline=True, linecolor="#9aa1a9")

        # ── Annotation rows below x-axis ─────────────────────────────────────
        # Left legend labels
        fig.add_annotation(x=0.01, y=0.28, xref="paper", yref="paper",
            text=f"■ {bl}", showarrow=False,
            font=dict(size=12, color=bc, family="Arial"),
            align="left", xanchor="left")
        fig.add_annotation(x=0.01, y=0.13, xref="paper", yref="paper",
            text=f"—○— {ll}", showarrow=False,
            font=dict(size=12, color=lc, family="Arial"),
            align="left", xanchor="left")
        # Per-year values
        for i in x_idx:
            fig.add_annotation(x=i, y=0.28, xref="x", yref="paper",
                text=_fv(bv[i] if i < len(bv) else None, bfmt),
                showarrow=False, font=dict(size=11, color="#6f7882", family="Arial"),
                align="center")
            fig.add_annotation(x=i, y=0.13, xref="x", yref="paper",
                text=_fv(lv[i] if i < len(lv) else None, lfmt),
                showarrow=False, font=dict(size=11, color="#6f7882", family="Arial"),
                align="center")
        return fig

    def _b_stack100(xs, traces, title="", h=430):
        fig = go.Figure()
        for (vals, lbl, col) in traces:
            fig.add_trace(go.Bar(x=xs, y=vals, name=lbl, marker_color=col, marker_line_width=0,
                text=[f"{v:.1f}%" if v and v>5 else "" for v in vals],
                textposition="inside", textfont=dict(size=13, color="white", family="Arial"),
                hovertemplate=f"{lbl}: %{{y:.1f}}%<extra></extra>"))
        lay = _blt(title, h)
        lay["barmode"] = "stack"
        lay["yaxis"]["ticksuffix"] = "%"
        lay["yaxis"]["range"] = [0, 100]
        fig.update_layout(**lay)
        return fig

    def _b_dline(xs, s1v, s1l, s1c, s2v, s2l, s2c, title="", h=430,
                 s1f=".1f", s2f=".1f", yt="", s2yt="", right_y=False):
        fig = _msp(specs=[[{"secondary_y": True}]]) if right_y else go.Figure()
        kw1 = dict(x=xs, y=s1v, name=s1l, mode="lines+markers+text",
                   line=dict(color=s1c, width=2.5), marker=_open_mk(s1c),
                   text=[f"{v:{s1f}}" if v is not None else "" for v in s1v],
                   textposition="top center", textfont=dict(size=13, color="#2a2825", family="Arial"))
        kw2 = dict(x=xs, y=s2v, name=s2l, mode="lines+markers+text",
                   line=dict(color=s2c, width=2.5), marker=_open_mk(s2c),
                   text=[f"{v:{s2f}}" if v is not None else "" for v in s2v],
                   textposition="top center", textfont=dict(size=13, color="#2a2825", family="Arial"))
        if right_y:
            fig.add_trace(go.Scatter(**kw1), secondary_y=False)
            fig.add_trace(go.Scatter(**kw2), secondary_y=True)
            lay = _blt(title, h)
            lay["yaxis"]["title"] = dict(text=yt, font=dict(size=11, color="#666"))
            lay["yaxis"]["ticksuffix"] = "%"
            lay["yaxis2"] = dict(
            tickfont=dict(size=12, color="#6f7882", family="Arial"),
            showgrid=False, zeroline=False,
            showline=True, linecolor="#9aa1a9", linewidth=1.2,
            showticklabels=True,
            title=dict(text=s2yt, font=dict(size=11, color="#444")),
        )
        else:
            fig.add_trace(go.Scatter(**kw1))
            fig.add_trace(go.Scatter(**kw2))
            lay = _blt(title, h)
            lay["yaxis"]["title"] = dict(text=yt, font=dict(size=11, color="#666"))
            lay["yaxis"]["ticksuffix"] = "%"
        fig.update_layout(**lay)
        return fig

    _ys_str = [str(y) for y in ys]

    with tab_energy:
        # ── Fuel mix definitions — order matches TIP annual report (bottom→top) ──
        FUEL_DEFS = [
            ("nat_gas",     "Natural Gas",                                "#8FA5B5"),
            ("coal",        "Coal",                                       "#555E6E"),
            ("diesel",      "Diesel/LPG/Other",                          _TC["bar_orange"]),
            ("renew_gj",    "Renewable Electricity (purchased+self-gen)", _TC["bar_green"]),
            ("nonrenew_gj", "Non-renewable Electricity",                  _TC["bar_sand"]),
        ]

        def _mix_traces(data_per_year):
            totals = [max(sum(d.get(fk, 0) for fk, _, _ in FUEL_DEFS), 1)
                      for d in data_per_year]
            traces = []
            for fkey, flbl, fcol in FUEL_DEFS:
                pcts = [d.get(fkey, 0) / t * 100 for d, t in zip(data_per_year, totals)]
                if any(p > 0 for p in pcts):
                    traces.append((pcts, flbl, fcol))
            return traces

        def _mix_fig(xs, traces, title, h=490):
            fig = go.Figure()
            for (vals, lbl, col) in traces:
                fig.add_trace(go.Bar(
                    x=xs, y=vals, name=lbl,
                    marker=dict(color=col, line=dict(width=0)),
                    text=[f"{v:.1f}%" if v and v > 4 else "" for v in vals],
                    textposition="inside",
                    textfont=dict(size=10, color="white", family="Arial"),
                    hovertemplate=f"{lbl}: %{{y:.1f}}%<extra></extra>",
                ))
            lay = _blt(title, h)
            lay["barmode"]            = "stack"
            lay["showlegend"]         = False
            lay["yaxis"]["ticksuffix"] = "%"
            lay["yaxis"]["range"]      = [0, 100]
            lay["margin"]              = dict(l=50, r=20, t=50, b=50)
            # Transparent backgrounds so outer container provides the single bg
            lay["plot_bgcolor"]  = "rgba(0,0,0,0)"
            lay["paper_bgcolor"] = "rgba(0,0,0,0)"
            fig.update_layout(**lay)
            return fig

        # ── TIP aggregate from _sector_series ─────────────────────────────────
        col_map = {
            "nat_gas":     "Natural Gas",
            "coal":        "Coal",
            "diesel":      "Diesel",
            "renew_gj":    "Renewable Electricity Purchased",
            "nonrenew_gj": "Non-Renewable Electricity Purchased",
        }
        tip_fuel_raw = {}
        for fkey, _, _ in FUEL_DEFS:
            mean_vals, _, _ = _sector_series(col_map.get(fkey, fkey))
            tip_fuel_raw[fkey] = mean_vals

        tip_data = [{fk: tip_fuel_raw[fk].get(y, 0) for fk, _, _ in FUEL_DEFS} for y in ys]
        co_data  = [{fk: trend[y].get(fk, 0)        for fk, _, _ in FUEL_DEFS} for y in ys]

        tip_traces = _mix_traces(tip_data)
        co_traces  = _mix_traces(co_data)

        # ── Shared HTML legend ─────────────────────────────────────────────────
        legend_items = "".join([
            f'''<div style="display:flex;align-items:center;gap:7px;margin-bottom:10px">
                  <div style="width:13px;height:13px;border-radius:2px;
                      background:{col};flex-shrink:0"></div>
                  <span style="font-size:10.5px;color:#374151;font-family:Arial;
                      line-height:1.3">{lbl}</span>
                </div>'''
            for _, lbl, col in FUEL_DEFS
        ])

        # ── Single shared background via CSS targeting the columns block ─────
        # Using a unique key on the container so CSS targets only this block
        st.markdown("""
        <style>
        [data-testid="stHorizontalBlock"]:has(.energy-mix-anchor) {
            background: #f5f4f2;
            border-radius: 8px;
            padding: 12px 8px 8px 8px;
            margin-bottom: 8px;
        }
        </style>
        """, unsafe_allow_html=True)

        # ── Single subplot figure: TIP mix | blank legend col | Company mix ──
        # Using make_subplots with shared x-axis so zoom/pan syncs both charts
        from plotly.subplots import make_subplots as _msp_e
        fig_emix = _msp_e(
            rows=1, cols=3,
            column_widths=[0.44, 0.12, 0.44],
            shared_xaxes=False,
            horizontal_spacing=0.04,
        )

        # Add TIP traces to col 1
        for (vals, lbl, col) in tip_traces:
            fig_emix.add_trace(go.Bar(
                x=_ys_str, y=vals, name=lbl,
                marker=dict(color=col, line=dict(width=0)),
                text=[f"{v:.1f}%" if v and v > 4 else "" for v in vals],
                textposition="inside",
                textfont=dict(size=10, color="white", family="Arial"),
                hovertemplate=f"TIP — {lbl}: %{{y:.1f}}%<extra></extra>",
                showlegend=False,
            ), row=1, col=1)

        # Add Company traces to col 3 (same colors, same names, showlegend=False)
        for (vals, lbl, col) in co_traces:
            fig_emix.add_trace(go.Bar(
                x=_ys_str, y=vals, name=lbl,
                marker=dict(color=col, line=dict(width=0)),
                text=[f"{v:.1f}%" if v and v > 4 else "" for v in vals],
                textposition="inside",
                textfont=dict(size=10, color="white", family="Arial"),
                hovertemplate=f"{company.split()[0]} — {lbl}: %{{y:.1f}}%<extra></extra>",
                showlegend=False,
            ), row=1, col=3)

        # ── Layout ────────────────────────────────────────────────────────────
        fig_emix.update_layout(
            barmode="stack",
            height=520,
            margin=dict(l=50, r=30, t=60, b=50),
            plot_bgcolor="#f5f4f2", paper_bgcolor="#f5f4f2",
            showlegend=False,
            hovermode="x unified",
            font=dict(family="Arial", size=11, color="#6f7882"),
        )

        # X-axes styling
        for col_n in [1, 3]:
            fig_emix.update_xaxes(
                showgrid=False, linecolor="#9aa1a9", linewidth=1.2,
                showline=True, tickfont=dict(size=11, color="#6f7882"),
                row=1, col=col_n,
            )

        # Y-axes: % range 0-100
        for col_n in [1, 3]:
            fig_emix.update_yaxes(
                range=[0, 100], ticksuffix="%",
                showgrid=True, gridcolor="#e6eaed",
                showline=True, linecolor="#9aa1a9", linewidth=1.2,
                zeroline=False, tickfont=dict(size=11, color="#6f7882"),
                row=1, col=col_n,
            )
        # Hide middle column axes entirely
        fig_emix.update_xaxes(visible=False, row=1, col=2)
        fig_emix.update_yaxes(visible=False, row=1, col=2)

        # Subplot labels (TIP MEMBERS / Company name) using paper coords
        # Col 1 center ≈ 0.22, Col 3 center ≈ 0.78 in paper space
        fig_emix.add_annotation(
            text="TIP MEMBERS",
            xref="paper", yref="paper", x=0.22, y=1.04,
            xanchor="center", showarrow=False,
            font=dict(size=11, color="#6f7882", family="Arial"),
        )
        fig_emix.add_annotation(
            text=company.upper(),
            xref="paper", yref="paper", x=0.78, y=1.04,
            xanchor="center", showarrow=False,
            font=dict(size=11, color="#6f7882", family="Arial"),
        )

        # Chart titles — paper coords, left-aligned within each subplot
        fig_emix.add_annotation(
            text="<b>Energy mix — TIP sector</b>",
            xref="paper", yref="paper",
            x=0.0, y=1.10, xanchor="left", showarrow=False,
            font=dict(size=13, color="#2a2825", family="Arial"),
        )
        fig_emix.add_annotation(
            text=f"<b>Energy mix — {company}</b>",
            xref="paper", yref="paper",
            x=0.56, y=1.10, xanchor="left", showarrow=False,
            font=dict(size=13, color="#2a2825", family="Arial"),
        )

        # Legend in middle column — paper x≈0.5 (middle of col 2)
        legend_ann_text = "<br>".join([
            f'<span style="color:{col}">■</span> {lbl}'
            for _, lbl, col in FUEL_DEFS
        ])
        fig_emix.add_annotation(
            text=legend_ann_text,
            xref="paper", yref="paper",
            x=0.5, y=0.55, xanchor="center", yanchor="middle",
            showarrow=False, align="left",
            font=dict(size=10, color="#374151", family="Arial"),
        )

        st.plotly_chart(fig_emix, use_container_width=True,
                        key=_chart_key(company, rep_year, "5mix"))


        # ── Row 2: Total Energy TIP vs Company  |  ISO Certification ───────
        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
        col_e, col_iso = st.columns(2, gap="medium")

        with col_e:
            # Total energy TIP vs Company bars + intensity lines
            # Same pattern as CO₂ / Water left charts
            tip_energy_abs, _, _ = _sector_series("Total energy")
            tip_energy_kpi, _, _ = _sector_series("Total energy - KPI")

            eng_tip = [tip_energy_abs.get(y, 0) / 1e6 for y in ys]   # PJ
            eng_co  = [trend[y].get("energy_kpi", 0) * trend[y].get("waste_total", 0)
                       / 1e6 for y in ys]   # proxy absolute from KPI * production
            # Better: use total_energy directly from trend if available
            eng_co  = [sum([
                trend[y].get("nat_gas", 0), trend[y].get("coal", 0),
                trend[y].get("diesel", 0), trend[y].get("renew_gj", 0),
                trend[y].get("nonrenew_gj", 0),
            ]) / 1e6 for y in ys]  # PJ

            int_tip_e = [tip_energy_kpi.get(y, 0) for y in ys]   # GJ/t
            int_co_e  = [trend[y]["energy_kpi"]    for y in ys]   # GJ/t

            n_e   = len(ys)
            x_e   = list(range(n_e))

            from plotly.subplots import make_subplots as _msp2
            fig_eng = _msp2(specs=[[{"secondary_y": True}]])

            fig_eng.add_trace(go.Bar(
                x=x_e, y=eng_tip, name="Total Energy (TIP)",
                marker=dict(color="#3DBDB5", line=dict(width=0)), width=0.32,
                hovertemplate="TIP Energy: %{y:,.1f} PJ<extra></extra>",
                cliponaxis=False,
            ), secondary_y=False)

            fig_eng.add_trace(go.Bar(
                x=x_e, y=eng_co, name="Total Energy (Company)",
                marker=dict(color="#1A1A2E", line=dict(width=0)), width=0.32,
                hovertemplate="Company Energy: %{y:,.1f} PJ<extra></extra>",
                cliponaxis=False,
            ), secondary_y=False)

            fig_eng.add_trace(go.Scatter(
                x=x_e, y=int_tip_e, name="Energy Intensity (TIP)",
                mode="lines",
                line=dict(color="#2a2825", width=2.2),
                hovertemplate="TIP Intensity: %{y:.2f} GJ/t<extra></extra>",
                cliponaxis=False,
            ), secondary_y=True)

            fig_eng.add_trace(go.Scatter(
                x=x_e, y=int_co_e, name="Energy Intensity (Company)",
                mode="lines",
                line=dict(color="#F5A623", width=2.2, dash="dash"),
                hovertemplate="Company Intensity: %{y:.2f} GJ/t<extra></extra>",
                cliponaxis=False,
            ), secondary_y=True)

            lay_eng = _blt("Total energy consumption and intensity", 530, r=80)
            lay_eng["barmode"]    = "group"
            lay_eng["showlegend"] = False
            lay_eng["hovermode"]  = "x unified"
            lay_eng["margin"]     = dict(l=120, r=80, t=60, b=30)
            lay_eng["yaxis"]["domain"] = [0.42, 1.0]
            lay_eng["yaxis"]["title"]  = dict(
                text="<b>Total Energy (PJ)</b>",
                font=dict(size=11, color="#6f7882", family="Arial"),
            )
            lay_eng["yaxis"]["tickfont"] = dict(size=11, color="#6f7882", family="Arial")
            lay_eng["yaxis2"] = dict(
                overlaying="y", side="right",
                showgrid=False, zeroline=False,
                showline=True, linecolor="#9aa1a9", linewidth=1.2,
                tickfont=dict(size=11, color="#6f7882", family="Arial"),
                showticklabels=True, autorange=True,
                domain=[0.42, 1.0],
                title=dict(
                    text="<b>Energy Intensity (GJ/t)</b>",
                    font=dict(size=11, color="#6f7882", family="Arial"),
                ),
            )
            lay_eng["xaxis"].update(dict(
                domain=[0.0, 1.0], tickmode="array",
                tickvals=x_e, ticktext=[str(y) for y in ys], type="linear",
            ))
            fig_eng.update_layout(**lay_eng)
            fig_eng.update_yaxes(showticklabels=True, showline=True, linecolor="#9aa1a9")

            rows_e = [
                (0.34, "#3DBDB5", "■",   "Total Energy (TIP)",     eng_tip,  "{:.1f}"),
                (0.24, "#1A1A2E", "■",   "Total Energy (Company)", eng_co,   "{:.1f}"),
                (0.14, "#2a2825", "—●—", "Intensity (TIP)",        int_tip_e,"{:.1f}"),
                (0.04, "#F5A623", "—◉—", "Intensity (Company)",    int_co_e, "{:.1f}"),
            ]
            for (y_pos, color, sym, label, vals, fmt) in rows_e:
                fig_eng.add_annotation(
                    text=f"<span style=\'color:{color}\'>{sym}</span> {label}",
                    xref="paper", yref="paper",
                    x=-0.0042, y=y_pos, xanchor="right", yanchor="middle",
                    showarrow=False,
                    font=dict(size=8.5, color="#374151", family="Arial"),
                )
                for xi, val in zip(x_e, vals):
                    if val is not None:
                        fig_eng.add_annotation(
                            text=fmt.format(val),
                            xref="x", yref="paper",
                            x=xi, y=y_pos,
                            xanchor="center", yanchor="middle",
                            showarrow=False,
                            font=dict(size=9, color="#374151", family="Arial"),
                        )
            st.plotly_chart(fig_eng, use_container_width=True,
                            key=_chart_key(company, rep_year, "5b"))

        with col_iso:
            # ISO 14001 certification rate — TIP vs Company lines
            tip_iso_raw, _, _ = _sector_series("ISO_Certification_%")
            tip_iso = [tip_iso_raw.get(y, 0) for y in ys]

            # Company ISO %
            co_iso_sites = [sum(1 for _ in range(1))  # placeholder
                            for y in ys]
            # Use consolidated data directly
            iso_col = state.CONSOLIDATED_DF
            def _co_iso(yr):
                row = iso_col[(iso_col["Company"] == company) &
                              (iso_col["Year"] == yr)]
                if row.empty: return None
                cert = row["ISO_Certification_%"].values[0] if "ISO_Certification_%" in row else None
                if cert is not None and cert == cert: return float(cert)
                # Compute from sites
                sites = row["ISO 14001 sites"].values[0] if "ISO 14001 sites" in row else None
                tot   = row["Total no. of sites"].values[0] if "Total no. of sites" in row else None
                if sites and tot and float(tot) > 0: return float(sites) / float(tot) * 100
                return None
            co_iso = [_co_iso(y) for y in ys]

            fig_iso = go.Figure()
            fig_iso.add_trace(go.Scatter(
                x=_ys_str, y=tip_iso, name="Weighted avg (TIP)",
                mode="lines+markers+text",
                line=dict(color="#2a2825", width=2.5),
                marker=dict(size=7, color="#2a2825", symbol="circle"),
                text=[f"{v:.0f}%" if v else "" for v in tip_iso],
                textposition="top center",
                textfont=dict(size=9, color="#2a2825", family="Arial"),
                hovertemplate="TIP ISO: %{y:.1f}%<extra></extra>",
            ))
            fig_iso.add_trace(go.Scatter(
                x=_ys_str, y=co_iso, name=f"Weighted avg ({company.split()[0]})",
                mode="lines+markers+text",
                line=dict(color="#F5A623", width=2.5, dash="dash"),
                marker=dict(size=7, color="#F5A623", symbol="circle-open"),
                text=[f"{v:.0f}%" if v else "" for v in co_iso],
                textposition="top center",
                textfont=dict(size=9, color="#F5A623", family="Arial"),
                hovertemplate="Company ISO: %{y:.1f}%<extra></extra>",
            ))
            lay_iso = _blt("ISO 14001 certification rate (%)", 530)
            lay_iso["yaxis"]["title"]     = dict(
                text="ISO 14001 certification rate (%)",
                font=dict(size=11, color="#6f7882", family="Arial"),
            )
            lay_iso["yaxis"]["ticksuffix"] = "%"
            lay_iso["legend"] = dict(
                orientation="h", x=0.5, xanchor="center", y=-0.12,
                font=dict(size=10, color="#6f7882"), bgcolor="rgba(0,0,0,0)",
            )
            lay_iso["margin"] = dict(l=70, r=40, t=60, b=80)
            fig_iso.update_layout(**lay_iso)
            st.plotly_chart(fig_iso, use_container_width=True,
                            key=_chart_key(company, rep_year, "5c"))


        # ── Electricity from renewable sources — TIP vs Company (single chart) ─
        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
        elec_col, _ = st.columns(2, gap="medium")
        with elec_col:
            # Data
            total_e2      = [max(trend[y]["renew_gj"] + trend[y]["nonrenew_gj"], 1) for y in ys]
            renew_pct_co  = [trend[y]["renew_gj"] / t * 100 for y, t in zip(ys, total_e2)]
            nonren_pct_co = [100 - v for v in renew_pct_co]

            tip_renew_abs, _, _  = _sector_series("Renewable Electricity Purchased")
            tip_nonren_abs, _, _ = _sector_series("Non-Renewable Electricity Purchased")
            tip_renew_pct, tip_nonren_pct = [], []
            for y in ys:
                r = tip_renew_abs.get(y, 0)
                n = tip_nonren_abs.get(y, 0)
                tot = max(r + n, 1)
                tip_renew_pct.append(r / tot * 100)
                tip_nonren_pct.append(100 - r / tot * 100)

            # Use string years as x-axis + offsetgroup to stack TIP and Company
            # separately while grouping side-by-side per year
            # Colors: TIP = dark navy (renew) / beige (nonrenew)
            #         Company = teal (renew) / light blue (nonrenew)
            fig_elec = go.Figure()

            # TIP renewable (base)
            fig_elec.add_trace(go.Bar(
                x=_ys_str, y=tip_renew_pct,
                name="Renewable (TIP)",
                marker=dict(color="#2D4A5A", line=dict(width=0)),
                offsetgroup="tip", base=0,
                text=[f"{v:.1f}%" if v > 3 else "" for v in tip_renew_pct],
                textposition="inside", textfont=dict(size=10, color="white", family="Arial"),
                hovertemplate="TIP Renewable: %{y:.1f}%<extra></extra>",
            ))
            # TIP non-renewable (stacked on top of TIP renewable)
            fig_elec.add_trace(go.Bar(
                x=_ys_str, y=tip_nonren_pct,
                name="Non-renewable (TIP)",
                marker=dict(color="#D4C5A9", line=dict(width=0)),
                offsetgroup="tip", base=tip_renew_pct,
                text=[f"{v:.1f}%" if v > 3 else "" for v in tip_nonren_pct],
                textposition="inside", textfont=dict(size=10, color="#2a2825", family="Arial"),
                hovertemplate="TIP Non-renewable: %{y:.1f}%<extra></extra>",
            ))
            # Company renewable (base)
            fig_elec.add_trace(go.Bar(
                x=_ys_str, y=renew_pct_co,
                name="Renewable (Company)",
                marker=dict(color="#3DBDB5", line=dict(width=0)),
                offsetgroup="co", base=0,
                text=[f"{v:.1f}%" if v > 3 else "" for v in renew_pct_co],
                textposition="inside", textfont=dict(size=10, color="white", family="Arial"),
                hovertemplate="Company Renewable: %{y:.1f}%<extra></extra>",
            ))
            # Company non-renewable (stacked on top of Company renewable)
            fig_elec.add_trace(go.Bar(
                x=_ys_str, y=nonren_pct_co,
                name="Non-renewable (Company)",
                marker=dict(color="#B8CDD9", line=dict(width=0)),
                offsetgroup="co", base=renew_pct_co,
                text=[f"{v:.1f}%" if v > 3 else "" for v in nonren_pct_co],
                textposition="inside", textfont=dict(size=10, color="#2a2825", family="Arial"),
                hovertemplate="Company Non-renewable: %{y:.1f}%<extra></extra>",
            ))

            lay_elec = _blt("Electricity from renewable sources (%)", 480)
            lay_elec["barmode"]    = "group"   # offsetgroup handles stacking
            lay_elec["showlegend"] = True
            lay_elec["legend"]     = dict(
                orientation="h", x=0.5, xanchor="center", y=-0.18,
                font=dict(size=10, color="#6f7882"), bgcolor="rgba(0,0,0,0)",
            )
            lay_elec["yaxis"]["ticksuffix"] = "%"
            lay_elec["yaxis"]["range"]      = [0, 100]
            lay_elec["margin"] = dict(l=60, r=40, t=60, b=90)
            lay_elec["hovermode"] = "x unified"
            fig_elec.update_layout(**lay_elec)
            st.plotly_chart(fig_elec, use_container_width=True,
                            key=_chart_key(company, rep_year, "elec_mix"))

    with tab_co2:
        c1, c2 = st.columns(2, gap="medium")
        c1, c2 = st.columns(2, gap="medium")
        with c1:
            # ── Data ──────────────────────────────────────────────────────────
            tip_co2_abs, _, _ = _sector_series("Total CO2")
            tip_co2_kpi, _, _ = _sector_series("Total CO2 - KPI")

            co2_tip = [tip_co2_abs.get(y, 0) for y in ys]
            co2_co  = [trend[y]["scope1"] + trend[y]["scope2"] for y in ys]
            int_tip = [tip_co2_kpi.get(y, 0) for y in ys]
            int_co  = [trend[y]["co2_kpi"] for y in ys]

            n      = len(ys)
            x_idx  = list(range(n))          # numeric indices, same as _b_dbline

            # ── Figure (secondary_y for intensity lines) ───────────────────────
            from plotly.subplots import make_subplots as _msp2
            fig_co2 = _msp2(specs=[[{"secondary_y": True}]])

            # TIP bars
            fig_co2.add_trace(go.Bar(
                x=x_idx, y=co2_tip, name="Total CO₂ (TIP)",
                marker=dict(color="#3DBDB5", line=dict(width=0)), width=0.32,
                hovertemplate="TIP CO₂: %{y:,.0f}<extra></extra>",
                cliponaxis=False,
            ), secondary_y=False)

            # Company bars
            fig_co2.add_trace(go.Bar(
                x=x_idx, y=co2_co, name="Total CO₂ (Company)",
                marker=dict(color="#1A1A2E", line=dict(width=0)), width=0.32,
                hovertemplate="Company CO₂: %{y:,.0f}<extra></extra>",
                cliponaxis=False,
            ), secondary_y=False)

            # TIP intensity line
            fig_co2.add_trace(go.Scatter(
                x=x_idx, y=int_tip, name="CO₂ Intensity (TIP)",
                mode="lines",
                line=dict(color="#2a2825", width=2.2),
                hovertemplate="TIP Intensity: %{y:.2f}<extra></extra>",
                cliponaxis=False,
            ), secondary_y=True)

            # Company intensity line (dashed)
            fig_co2.add_trace(go.Scatter(
                x=x_idx, y=int_co, name="CO₂ Intensity (Company)",
                mode="lines",
                line=dict(color="#F5A623", width=2.2, dash="dash"),
                hovertemplate="Company Intensity: %{y:.2f}<extra></extra>",
                cliponaxis=False,
            ), secondary_y=True)

            # ── Layout — follows _b_dbline pattern exactly ────────────────────
            lay_co2 = _blt("Total CO₂ emissions and CO₂ intensity", 560, r=80)
            lay_co2["barmode"]    = "group"
            lay_co2["showlegend"] = False
            lay_co2["hovermode"]  = "x unified"
            lay_co2["margin"]     = dict(l=120, r=80, t=60, b=30)

            # Chart domain: top 60% for bars+lines, bottom 40% for annotation table
            lay_co2["yaxis"]["domain"] = [0.42, 1.0]
            lay_co2["yaxis"]["title"]  = dict(
                text="<b>Total CO₂ (tCO₂)</b>",
                font=dict(size=11, color="#6f7882", family="Arial"),
            )
            lay_co2["yaxis"]["tickfont"] = dict(size=11, color="#6f7882", family="Arial")

            # Right y-axis: same grey styling as _b_dbline
            lay_co2["yaxis2"] = dict(
                overlaying="y", side="right",
                showgrid=False, zeroline=False,
                showline=True, linecolor="#9aa1a9", linewidth=1.2,
                tickfont=dict(size=11, color="#6f7882", family="Arial"),
                showticklabels=True, autorange=True,
                domain=[0.42, 1.0],
                title=dict(
                    text="<b>CO₂ Intensity (tCO₂/t)</b>",
                    font=dict(size=11, color="#6f7882", family="Arial"),
                ),
            )

            # X-axis: numeric indices mapped to year labels
            lay_co2["xaxis"].update(dict(
                domain=[0.0, 1.0],
                tickmode="array",
                tickvals=x_idx,
                ticktext=[str(y) for y in ys],
                type="linear",
            ))

            fig_co2.update_layout(**lay_co2)
            fig_co2.update_yaxes(showticklabels=True, showline=True, linecolor="#9aa1a9")

            # ── Annotation table below x-axis ─────────────────────────────────
            # Row y-positions in paper coords (within bottom 40% domain)
            rows = [
                (0.34, "#3DBDB5", "■",   "Total CO₂ (TIP)",     co2_tip, "{:,.0f}"),
                (0.24, "#1A1A2E", "■",   "Total CO₂ (Company)", co2_co,  "{:,.0f}"),
                (0.14, "#2a2825", "—●—", "Intensity (TIP)",     int_tip, "{:.2f}"),
                (0.04, "#F5A623", "—◉—", "Intensity (Company)", int_co,  "{:.2f}"),
            ]

            for (y_pos, color, sym, label, vals, fmt) in rows:
                # Label with colored symbol — positioned left with right-anchor to avoid overlap
                label_x = -0.0042
                label_anchor = "right"
                fig_co2.add_annotation(
                    text=f"<span style=\'color:{color}\'>{sym}</span> {label}",
                    xref="paper", yref="paper",
                    x=label_x, y=y_pos, xanchor=label_anchor, yanchor="middle",
                    showarrow=False,
                    font=dict(size=8.5, color="#374151", family="Arial"),
                )
                # Per-year values under each year tick
                for xi, val in zip(x_idx, vals):
                    if val is not None:
                        fig_co2.add_annotation(
                            text=fmt.format(val),
                            xref="x", yref="paper",
                            x=xi, y=y_pos,
                            xanchor="center", yanchor="middle",
                            showarrow=False,
                            font=dict(size=9, color="#374151", family="Arial"),
                        )

            st.plotly_chart(fig_co2, use_container_width=True,
                            key=_chart_key(company, rep_year, "co2t"))

        with c2:
            # ── Data: live from _sector_series + trend (no hardcoding) ───────
            tip_s1_raw, _, _ = _sector_series("Total CO2 Scope 1")
            tip_s2_raw, _, _ = _sector_series("Total CO2 Scope 2")
            tip_total_raw, _, _ = _sector_series("Total CO2")

            # If Scope1/2 columns exist use them; else split total proportionally
            # using the company's own scope1/scope2 ratio as proxy for TIP split
            s1_co = [trend[y]["scope1"] for y in ys]
            s2_co = [trend[y]["scope2"] for y in ys]

            def _tip_scope(raw_dict, fallback_dict, ratio_vals, total_vals):
                """Return per-year TIP values from sector data or proportional fallback."""
                result = []
                for y, rv, tv in zip(ys, ratio_vals, total_vals):
                    if raw_dict.get(y):
                        result.append(raw_dict[y])
                    elif tv and tv > 0:
                        # Proportional split: use company ratio as TIP proxy
                        co_total = trend[y]["scope1"] + trend[y]["scope2"]
                        ratio = rv / co_total if co_total else 0.6
                        result.append(tip_total_raw.get(y, 0) * ratio)
                    else:
                        result.append(0)
                return result

            co_totals = [trend[y]["scope1"] + trend[y]["scope2"] for y in ys]
            tip_totals = [tip_total_raw.get(y, 0) for y in ys]
            s1_tip = _tip_scope(tip_s1_raw, {}, s1_co, tip_totals)
            s2_tip = _tip_scope(tip_s2_raw, {}, s2_co, tip_totals)

            n_sc = len(ys)
            x_sc = list(range(n_sc))

            # Colors: TIP = teal family, Company = blue-grey family
            TIP_S1_COL = "#3DBDB5"
            TIP_S2_COL = "#0F7F78"
            CO_S1_COL  = "#B8CDD9"
            CO_S2_COL  = "#2D4A5A"

            fig_sc = go.Figure()

            # TIP Scope 1 (base)
            fig_sc.add_trace(go.Bar(
                x=x_sc, y=s1_tip, name="Scope 1 — TIP",
                marker=dict(color=TIP_S1_COL, line=dict(width=0)),
                offsetgroup="tip", base=0,
                text=[f"{v:,.0f}" if v else "" for v in s1_tip],
                textposition="inside",
                textfont=dict(size=9, color="white", family="Arial"),
                hovertemplate="TIP Scope 1: %{y:,.0f} tCO₂<extra></extra>",
            ))
            # TIP Scope 2 (stacked on top of S1)
            fig_sc.add_trace(go.Bar(
                x=x_sc, y=s2_tip, name="Scope 2 — TIP",
                marker=dict(color=TIP_S2_COL, line=dict(width=0)),
                offsetgroup="tip", base=s1_tip,
                text=[f"{v:,.0f}" if v else "" for v in s2_tip],
                textposition="inside",
                textfont=dict(size=9, color="white", family="Arial"),
                hovertemplate="TIP Scope 2: %{y:,.0f} tCO₂<extra></extra>",
            ))
            # Company Scope 1 (base)
            fig_sc.add_trace(go.Bar(
                x=x_sc, y=s1_co, name="Scope 1 — Company",
                marker=dict(color=CO_S1_COL, line=dict(width=0)),
                offsetgroup="co", base=0,
                text=[f"{v:,.0f}" if v else "" for v in s1_co],
                textposition="inside",
                textfont=dict(size=9, color="#2D4A5A", family="Arial"),
                hovertemplate="Company Scope 1: %{y:,.0f} tCO₂<extra></extra>",
            ))
            # Company Scope 2 (stacked on top of S1)
            fig_sc.add_trace(go.Bar(
                x=x_sc, y=s2_co, name="Scope 2 — Company",
                marker=dict(color=CO_S2_COL, line=dict(width=0)),
                offsetgroup="co", base=s1_co,
                text=[f"{v:,.0f}" if v else "" for v in s2_co],
                textposition="inside",
                textfont=dict(size=9, color="white", family="Arial"),
                hovertemplate="Company Scope 2: %{y:,.0f} tCO₂<extra></extra>",
            ))

            # Layout — same height as left chart (560)
            lay_sc = _blt("CO₂ Scope 1 vs Scope 2 — TIP vs Company (tCO₂)", 560, r=40)
            lay_sc["barmode"]    = "group"
            lay_sc["showlegend"] = True
            lay_sc["legend"]     = dict(
                orientation="h", x=0.5, xanchor="center", y=-0.12,
                font=dict(size=10, color="#6f7882"), bgcolor="rgba(0,0,0,0)",
            )
            lay_sc["hovermode"]  = "x unified"
            lay_sc["margin"]     = dict(l=60, r=40, t=50, b=80)
            lay_sc["yaxis"]["title"] = dict(
                text="tCO₂", font=dict(size=11, color="#6f7882"),
            )
            lay_sc["xaxis"].update(dict(
                tickmode="array", tickvals=x_sc,
                ticktext=[str(y) for y in ys],
                type="linear",
            ))
            fig_sc.update_layout(**lay_sc)
            st.plotly_chart(fig_sc, use_container_width=True,
                            key=_chart_key(company, rep_year, "4"))

    with tab_water:
        c1, _ = st.columns(2, gap="medium")
        with c1:
            # ── Water withdrawals and intensity — TIP vs Company ─────────────
            tip_water_abs, _, _ = _sector_series("Water intake")
            tip_water_kpi, _, _ = _sector_series("Water intake - KPI")

            wat_tip = [tip_water_abs.get(y, 0) / 1e6 for y in ys]   # M m³
            wat_co  = [trend[y]["water_m3"] / 1e6   for y in ys]    # M m³
            int_tip = [tip_water_kpi.get(y, 0)      for y in ys]    # m³/t
            int_co  = [trend[y]["water_kpi"]         for y in ys]    # m³/t

            n_w    = len(ys)
            x_w    = list(range(n_w))

            from plotly.subplots import make_subplots as _msp2
            fig_wat = _msp2(specs=[[{"secondary_y": True}]])

            # TIP bars (teal — matches CO₂ TIP bar)
            fig_wat.add_trace(go.Bar(
                x=x_w, y=wat_tip, name="Water withdrawal (TIP)",
                marker=dict(color="#3DBDB5", line=dict(width=0)), width=0.32,
                hovertemplate="TIP Water: %{y:,.2f} M m³<extra></extra>",
                cliponaxis=False,
            ), secondary_y=False)

            # Company bars (dark navy — matches CO₂ Company bar)
            fig_wat.add_trace(go.Bar(
                x=x_w, y=wat_co, name="Water withdrawal (Company)",
                marker=dict(color="#1A1A2E", line=dict(width=0)), width=0.32,
                hovertemplate="Company Water: %{y:,.2f} M m³<extra></extra>",
                cliponaxis=False,
            ), secondary_y=False)

            # TIP intensity line (dark — matches CO₂ TIP intensity)
            fig_wat.add_trace(go.Scatter(
                x=x_w, y=int_tip, name="Water Intensity (TIP)",
                mode="lines",
                line=dict(color="#2a2825", width=2.2),
                hovertemplate="TIP Intensity: %{y:.2f} m³/t<extra></extra>",
                cliponaxis=False,
            ), secondary_y=True)

            # Company intensity line (dashed gold — matches CO₂ Company intensity)
            fig_wat.add_trace(go.Scatter(
                x=x_w, y=int_co, name="Water Intensity (Company)",
                mode="lines",
                line=dict(color="#F5A623", width=2.2, dash="dash"),
                hovertemplate="Company Intensity: %{y:.2f} m³/t<extra></extra>",
                cliponaxis=False,
            ), secondary_y=True)

            # ── Layout — exact same as CO₂ chart ──────────────────────────────
            lay_wat = _blt("Water withdrawals and intensity", 560, r=80)
            lay_wat["barmode"]    = "group"
            lay_wat["showlegend"] = False
            lay_wat["hovermode"]  = "x unified"
            lay_wat["margin"]     = dict(l=120, r=80, t=60, b=30)

            lay_wat["yaxis"]["domain"] = [0.42, 1.0]
            lay_wat["yaxis"]["title"]  = dict(
                text="<b>Water withdrawal (M m³)</b>",
                font=dict(size=11, color="#6f7882", family="Arial"),
            )
            lay_wat["yaxis"]["tickfont"] = dict(size=11, color="#6f7882", family="Arial")

            lay_wat["yaxis2"] = dict(
                overlaying="y", side="right",
                showgrid=False, zeroline=False,
                showline=True, linecolor="#9aa1a9", linewidth=1.2,
                tickfont=dict(size=11, color="#6f7882", family="Arial"),
                showticklabels=True, autorange=True,
                domain=[0.42, 1.0],
                title=dict(
                    text="<b>Water Intensity (m³/t)</b>",
                    font=dict(size=11, color="#6f7882", family="Arial"),
                ),
            )

            lay_wat["xaxis"].update(dict(
                domain=[0.0, 1.0],
                tickmode="array", tickvals=x_w,
                ticktext=[str(y) for y in ys],
                type="linear",
            ))

            fig_wat.update_layout(**lay_wat)
            fig_wat.update_yaxes(showticklabels=True, showline=True, linecolor="#9aa1a9")

            # ── Annotation table below x-axis ─────────────────────────────────
            rows_w = [
                (0.34, "#3DBDB5", "■",   "Withdrawal (TIP)",     wat_tip, "{:,.2f}"),
                (0.24, "#1A1A2E", "■",   "Withdrawal (Company)", wat_co,  "{:,.2f}"),
                (0.14, "#2a2825", "—●—", "Intensity (TIP)",      int_tip, "{:.2f}"),
                (0.04, "#F5A623", "—◉—", "Intensity (Company)",  int_co,  "{:.2f}"),
            ]

            for (y_pos, color, sym, label, vals, fmt) in rows_w:
                fig_wat.add_annotation(
                    text=f"<span style=\'color:{color}\'>{sym}</span> {label}",
                    xref="paper", yref="paper",
                    x=-0.0042, y=y_pos, xanchor="right", yanchor="middle",
                    showarrow=False,
                    font=dict(size=8.5, color="#374151", family="Arial"),
                )
                for xi, val in zip(x_w, vals):
                    if val is not None:
                        fig_wat.add_annotation(
                            text=fmt.format(val),
                            xref="x", yref="paper",
                            x=xi, y=y_pos,
                            xanchor="center", yanchor="middle",
                            showarrow=False,
                            font=dict(size=9, color="#374151", family="Arial"),
                        )

            st.plotly_chart(fig_wat, use_container_width=True,
                            key=_chart_key(company, rep_year, "10"))

    with tab_waste:
        # ════════════════════════════════════════════════════════════════
        # ROW 1
        # ════════════════════════════════════════════════════════════════
        row1_l, row1_r = st.columns(2, gap="medium")

        with row1_l:
            # ── NEW: Total waste generated + waste intensity TIP vs Company ──
            # Exact same pattern as CO₂ / Water / Energy charts
            tip_wgen_abs, _, _ = _sector_series("Total Waste")
            tip_wint_kpi, _, _ = _sector_series("Waste_Intensity_kg_t")
            # Fallback intensity: derive from total waste / production
            tip_prod_abs, _, _ = _sector_series("Production")

            wgen_tip = [tip_wgen_abs.get(y, 0) for y in ys]
            wgen_co  = [trend[y]["waste_total"] for y in ys]

            # Waste intensity kg/t = waste_total(kg) / production(t)
            # trend stores waste_total in T, convert to kg (*1000)
            def _wint(waste_t, prod_t):
                return waste_t * 1000 / prod_t if prod_t else 0

            # TIP intensity from sector: if column exists use it, else derive
            if any(tip_wint_kpi.values()):
                wint_tip = [tip_wint_kpi.get(y, 0) for y in ys]
            else:
                tip_prod = tip_prod_abs
                wint_tip = [_wint(tip_wgen_abs.get(y, 0),
                                  tip_prod.get(y, 1)) for y in ys]

            wint_co = [_wint(trend[y]["waste_total"],
                             trend[y].get("waste_total", 1) /
                             max(trend[y].get("waste_pct", 0.01) / 100, 0.001))
                       for y in ys]
            # Simpler: use waste_total / production from trend
            from formula_engine import TemplateInputs as _TI2, calculate as _calc2
            def _co_wint(yr):
                sd = dl.get_step_data(dl.get_company_hist(state.CONSOLIDATED_DF, company), yr)
                sc = {k: v for k, v in sd.items() if k in {f.name for f in _TI2.__dataclass_fields__.values()}}
                if not sc: return 0
                inp2 = _TI2(company=company, year=yr, **sc)
                prod = inp2.production
                wst  = inp2.waste_total
                return wst * 1000 / prod if prod else 0
            wint_co = [_co_wint(y) for y in ys]

            n_wg = len(ys)
            x_wg = list(range(n_wg))

            from plotly.subplots import make_subplots as _msp2
            fig_wgen = _msp2(specs=[[{"secondary_y": True}]])

            fig_wgen.add_trace(go.Bar(
                x=x_wg, y=wgen_tip, name="Total Waste (TIP)",
                marker=dict(color="#3DBDB5", line=dict(width=0)), width=0.32,
                hovertemplate="TIP Waste: %{y:,.0f} T<extra></extra>",
                cliponaxis=False,
            ), secondary_y=False)
            fig_wgen.add_trace(go.Bar(
                x=x_wg, y=wgen_co, name="Total Waste (Company)",
                marker=dict(color="#1A1A2E", line=dict(width=0)), width=0.32,
                hovertemplate="Company Waste: %{y:,.0f} T<extra></extra>",
                cliponaxis=False,
            ), secondary_y=False)
            fig_wgen.add_trace(go.Scatter(
                x=x_wg, y=wint_tip, name="Waste Intensity (TIP)",
                mode="lines",
                line=dict(color="#2a2825", width=2.2),
                hovertemplate="TIP Intensity: %{y:.1f} kg/t<extra></extra>",
                cliponaxis=False,
            ), secondary_y=True)
            fig_wgen.add_trace(go.Scatter(
                x=x_wg, y=wint_co, name="Waste Intensity (Company)",
                mode="lines",
                line=dict(color="#F5A623", width=2.2, dash="dash"),
                hovertemplate="Company Intensity: %{y:.1f} kg/t<extra></extra>",
                cliponaxis=False,
            ), secondary_y=True)

            lay_wgen = _blt("Total waste generated and intensity", 560, r=80)
            lay_wgen["barmode"]    = "group"
            lay_wgen["showlegend"] = False
            lay_wgen["hovermode"]  = "x unified"
            lay_wgen["margin"]     = dict(l=120, r=80, t=60, b=30)
            lay_wgen["yaxis"]["domain"] = [0.42, 1.0]
            lay_wgen["yaxis"]["title"]  = dict(
                text="<b>Total Waste (metric T)</b>",
                font=dict(size=11, color="#6f7882", family="Arial"),
            )
            lay_wgen["yaxis"]["tickfont"] = dict(size=11, color="#6f7882", family="Arial")
            lay_wgen["yaxis2"] = dict(
                overlaying="y", side="right",
                showgrid=False, zeroline=False,
                showline=True, linecolor="#9aa1a9", linewidth=1.2,
                tickfont=dict(size=11, color="#6f7882", family="Arial"),
                showticklabels=True, autorange=True,
                domain=[0.42, 1.0],
                title=dict(
                    text="<b>Waste Intensity (kg/t)</b>",
                    font=dict(size=11, color="#6f7882", family="Arial"),
                ),
            )
            lay_wgen["xaxis"].update(dict(
                domain=[0.0, 1.0], tickmode="array",
                tickvals=x_wg, ticktext=[str(y) for y in ys], type="linear",
            ))
            fig_wgen.update_layout(**lay_wgen)
            fig_wgen.update_yaxes(showticklabels=True, showline=True, linecolor="#9aa1a9")

            rows_wgen = [
                (0.34, "#3DBDB5", "■",   "Total Waste (TIP)",     wgen_tip, "{:,.0f}"),
                (0.24, "#1A1A2E", "■",   "Total Waste (Company)", wgen_co,  "{:,.0f}"),
                (0.14, "#2a2825", "—●—", "Intensity (TIP)",       wint_tip, "{:.1f}"),
                (0.04, "#F5A623", "—◉—", "Intensity (Company)",   wint_co,  "{:.1f}"),
            ]
            for (y_pos, color, sym, label, vals, fmt) in rows_wgen:
                fig_wgen.add_annotation(
                    text=f"<span style=\'color:{color}\'>{sym}</span> {label}",
                    xref="paper", yref="paper",
                    x=-0.0042, y=y_pos, xanchor="right", yanchor="middle",
                    showarrow=False,
                    font=dict(size=8.5, color="#374151", family="Arial"),
                )
                for xi, val in zip(x_wg, vals):
                    if val is not None:
                        fig_wgen.add_annotation(
                            text=fmt.format(val),
                            xref="x", yref="paper",
                            x=xi, y=y_pos,
                            xanchor="center", yanchor="middle",
                            showarrow=False,
                            font=dict(size=9, color="#374151", family="Arial"),
                        )
            st.plotly_chart(fig_wgen, use_container_width=True,
                            key=_chart_key(company, rep_year, "wgen"))

        with row1_r:
            # ── Waste sent to elimination and recovery (absolute metric T) ───
            tip_waste_tot, _, _ = _sector_series("Total Waste")
            tip_waste_rec, _, _ = _sector_series("Waste Recovered")
            co_wt  = [trend[y]["waste_total"] for y in ys]
            co_wr  = [trend[y]["waste_rec"]   for y in ys]
            co_we  = [max(t - r, 0) for t, r in zip(co_wt, co_wr)]
            tip_wt = [tip_waste_tot.get(y, 0) for y in ys]
            tip_wr = [tip_waste_rec.get(y, 0) for y in ys]
            tip_we = [max(t - r, 0) for t, r in zip(tip_wt, tip_wr)]

            def _pct_lbl(part, total, fmt="{:.0f}%"):
                return [fmt.format(p / max(t, 1) * 100) if p > 0 else ""
                        for p, t in zip(part, total)]

            x_wr = list(range(len(ys)))
            fig_wr = go.Figure()
            fig_wr.add_trace(go.Bar(
                x=x_wr, y=tip_wr, name="Waste to recovery (TIP)",
                marker=dict(color="#3DBDB5", line=dict(width=0)),
                offsetgroup="tip", base=0,
                text=_pct_lbl(tip_wr, tip_wt),
                textposition="inside",
                textfont=dict(size=9, color="white", family="Arial"),
                hovertemplate="TIP Recovery: %{y:,.0f} T<extra></extra>",
            ))
            fig_wr.add_trace(go.Bar(
                x=x_wr, y=tip_we, name="Waste to elimination (TIP)",
                marker=dict(color="#0F7F78", line=dict(width=0)),
                offsetgroup="tip", base=tip_wr,
                text=_pct_lbl(tip_we, tip_wt),
                textposition="inside",
                textfont=dict(size=9, color="white", family="Arial"),
                hovertemplate="TIP Elimination: %{y:,.0f} T<extra></extra>",
            ))
            fig_wr.add_trace(go.Bar(
                x=x_wr, y=co_wr, name="Waste to recovery (Company)",
                marker=dict(color="#F5A623", line=dict(width=0)),
                offsetgroup="co", base=0,
                text=_pct_lbl(co_wr, co_wt),
                textposition="inside",
                textfont=dict(size=9, color="white", family="Arial"),
                hovertemplate="Company Recovery: %{y:,.0f} T<extra></extra>",
            ))
            fig_wr.add_trace(go.Bar(
                x=x_wr, y=co_we, name="Waste to elimination (Company)",
                marker=dict(color=_TC["bar_blue2"], line=dict(width=0)),
                offsetgroup="co", base=co_wr,
                text=_pct_lbl(co_we, co_wt),
                textposition="inside",
                textfont=dict(size=9, color="white", family="Arial"),
                hovertemplate="Company Elimination: %{y:,.0f} T<extra></extra>",
            ))
            lay_wr = _blt("Waste sent to elimination and recovery (Metric T)", 560, r=40)
            lay_wr["barmode"]    = "group"
            lay_wr["showlegend"] = True
            lay_wr["legend"]     = dict(
                orientation="h", x=0.5, xanchor="center", y=-0.12,
                font=dict(size=10, color="#6f7882"), bgcolor="rgba(0,0,0,0)",
            )
            lay_wr["hovermode"]  = "x unified"
            lay_wr["margin"]     = dict(l=60, r=40, t=50, b=80)
            lay_wr["yaxis"]["title"] = dict(
                text="Amount of waste (Metric T)",
                font=dict(size=11, color="#6f7882", family="Arial"),
            )
            lay_wr["xaxis"].update(dict(
                tickmode="array", tickvals=x_wr,
                ticktext=[str(y) for y in ys], type="linear",
            ))
            fig_wr.update_layout(**lay_wr)
            st.plotly_chart(fig_wr, use_container_width=True,
                            key=_chart_key(company, rep_year, "12"))

        # ════════════════════════════════════════════════════════════════
        # ROW 2
        # ════════════════════════════════════════════════════════════════
        st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)
        row2_l, _ = st.columns(2, gap="medium")

        with row2_l:
            # ── Waste generated and recovery rate (TIP vs Company) ───────────
            tip_waste_abs2, _, _ = _sector_series("Total Waste")
            tip_waste_kpi2, _, _ = _sector_series("Waste_Recovery_Rate_%")

            wst_tip2 = [tip_waste_abs2.get(y, 0) for y in ys]
            wst_co2  = [trend[y]["waste_total"]   for y in ys]
            int_tip2 = [tip_waste_kpi2.get(y, 0)  for y in ys]
            int_co2  = [trend[y]["waste_pct"]      for y in ys]

            x_wst2 = list(range(len(ys)))
            fig_wst = _msp2(specs=[[{"secondary_y": True}]])

            fig_wst.add_trace(go.Bar(
                x=x_wst2, y=wst_tip2, name="Total Waste (TIP)",
                marker=dict(color="#3DBDB5", line=dict(width=0)), width=0.32,
                hovertemplate="TIP Waste: %{y:,.0f} T<extra></extra>",
                cliponaxis=False,
            ), secondary_y=False)
            fig_wst.add_trace(go.Bar(
                x=x_wst2, y=wst_co2, name="Total Waste (Company)",
                marker=dict(color="#1A1A2E", line=dict(width=0)), width=0.32,
                hovertemplate="Company Waste: %{y:,.0f} T<extra></extra>",
                cliponaxis=False,
            ), secondary_y=False)
            fig_wst.add_trace(go.Scatter(
                x=x_wst2, y=int_tip2, name="Recovery Rate (TIP)",
                mode="lines",
                line=dict(color="#2a2825", width=2.2),
                hovertemplate="TIP Recovery: %{y:.1f}%<extra></extra>",
                cliponaxis=False,
            ), secondary_y=True)
            fig_wst.add_trace(go.Scatter(
                x=x_wst2, y=int_co2, name="Recovery Rate (Company)",
                mode="lines",
                line=dict(color="#F5A623", width=2.2, dash="dash"),
                hovertemplate="Company Recovery: %{y:.1f}%<extra></extra>",
                cliponaxis=False,
            ), secondary_y=True)

            lay_wst2 = _blt("Waste generated and recovery rate", 560, r=80)
            lay_wst2["barmode"]    = "group"
            lay_wst2["showlegend"] = False
            lay_wst2["hovermode"]  = "x unified"
            lay_wst2["margin"]     = dict(l=120, r=80, t=60, b=30)
            lay_wst2["yaxis"]["domain"] = [0.42, 1.0]
            lay_wst2["yaxis"]["title"]  = dict(
                text="<b>Total Waste (metric T)</b>",
                font=dict(size=11, color="#6f7882", family="Arial"),
            )
            lay_wst2["yaxis"]["tickfont"] = dict(size=11, color="#6f7882", family="Arial")
            lay_wst2["yaxis2"] = dict(
                overlaying="y", side="right",
                showgrid=False, zeroline=False,
                showline=True, linecolor="#9aa1a9", linewidth=1.2,
                tickfont=dict(size=11, color="#6f7882", family="Arial"),
                showticklabels=True, autorange=True,
                domain=[0.42, 1.0],
                title=dict(
                    text="<b>Recovery Rate (%)</b>",
                    font=dict(size=11, color="#6f7882", family="Arial"),
                ),
            )
            lay_wst2["xaxis"].update(dict(
                domain=[0.0, 1.0], tickmode="array",
                tickvals=x_wst2, ticktext=[str(y) for y in ys], type="linear",
            ))
            fig_wst.update_layout(**lay_wst2)
            fig_wst.update_yaxes(showticklabels=True, showline=True, linecolor="#9aa1a9")

            rows_wst2 = [
                (0.34, "#3DBDB5", "■",   "Total Waste (TIP)",     wst_tip2, "{:,.0f}"),
                (0.24, "#1A1A2E", "■",   "Total Waste (Company)", wst_co2,  "{:,.0f}"),
                (0.14, "#2a2825", "—●—", "Recovery Rate (TIP)",   int_tip2, "{:.1f}%"),
                (0.04, "#F5A623", "—◉—", "Recovery Rate (Co.)",   int_co2,  "{:.1f}%"),
            ]
            for (y_pos, color, sym, label, vals, fmt) in rows_wst2:
                fig_wst.add_annotation(
                    text=f"<span style=\'color:{color}\'>{sym}</span> {label}",
                    xref="paper", yref="paper",
                    x=-0.0042, y=y_pos, xanchor="right", yanchor="middle",
                    showarrow=False,
                    font=dict(size=8.5, color="#374151", family="Arial"),
                )
                for xi, val in zip(x_wst2, vals):
                    if val is not None:
                        fig_wst.add_annotation(
                            text=fmt.format(val),
                            xref="x", yref="paper",
                            x=xi, y=y_pos,
                            xanchor="center", yanchor="middle",
                            showarrow=False,
                            font=dict(size=9, color="#374151", family="Arial"),
                        )
            st.plotly_chart(fig_wst, use_container_width=True,
                            key=_chart_key(company, rep_year, "11"))

    with tab_people:
        p1, p2 = st.columns(2, gap="medium")

        # Helper to safely get a value from CONSOLIDATED_DF for this company+year
        def _co_people(col_options, yr, multiply100=False):
            """Try multiple column name variants, return float or 0."""
            row = state.CONSOLIDATED_DF[
                (state.CONSOLIDATED_DF["Company"] == company) &
                (state.CONSOLIDATED_DF["Year"] == yr)]
            if row.empty: return 0
            for col in col_options:
                if col in row.columns:
                    v = row[col].values[0]
                    if v is not None and v == v:  # not NaN
                        val = float(v)
                        return val * 100 if multiply100 and val <= 1.0 else val
            return 0

        # Load TIP static benchmark data (H&S and diversity are static arrays)
        _tip_graph = dl.get_tip_graph_data(state.SECTOR_DF)
        _tip_all_years = _tip_graph.get("years", [])

        def _tip_people_val(key, yr):
            """Get TIP value for a given year from static graph data."""
            vals = _tip_graph.get(key, [])
            if yr in _tip_all_years:
                idx = _tip_all_years.index(yr)
                return vals[idx] if idx < len(vals) else 0
            return 0

        # Load supplementary data which has H&S and diversity fields
        # _load_supplementary requires (company, year) — load per-year in loop

        with p1:
            # ── H&S Audit: external + internal — TIP static + Company supplementary ─
            hs_ext_tip = [_tip_people_val("hs_external", y) for y in ys]
            hs_int_tip = [_tip_people_val("hs_internal", y) for y in ys]

            # Company: load from supplementary data per year using exact field names
            hs_ext_co, hs_int_co = [], []
            for y in ys:
                sy = _load_supplementary(company, y) or {}
                # hs_external_audit and hs_internal_audit are stored as fractions (0-1) or %
                def _pct(v):
                    if v is None: return 0
                    f = float(v)
                    return f * 100 if f <= 1.0 else f
                hs_ext_co.append(_pct(sy.get("hs_external_audit")))
                hs_int_co.append(_pct(sy.get("hs_internal_audit")))

            x_hs = list(range(len(ys)))
            from plotly.subplots import make_subplots as _msp3
            fig_hs = _msp3(specs=[[{"secondary_y": True}]])

            fig_hs.add_trace(go.Bar(
                x=x_hs, y=hs_ext_tip, name="Externally audited (TIP)",
                marker=dict(color="#3DBDB5", line=dict(width=0)), width=0.32,
                hovertemplate="TIP External: %{y:.1f}%<extra></extra>",
                cliponaxis=False,
            ), secondary_y=False)
            fig_hs.add_trace(go.Bar(
                x=x_hs, y=hs_ext_co, name="Externally audited (Company)",
                marker=dict(color="#1A1A2E", line=dict(width=0)), width=0.32,
                hovertemplate="Company External: %{y:.1f}%<extra></extra>",
                cliponaxis=False,
            ), secondary_y=False)
            fig_hs.add_trace(go.Scatter(
                x=x_hs, y=hs_int_tip, name="Internally audited (TIP)",
                mode="lines",
                line=dict(color="#2a2825", width=2.2),
                hovertemplate="TIP Internal: %{y:.1f}%<extra></extra>",
                cliponaxis=False,
            ), secondary_y=True)
            fig_hs.add_trace(go.Scatter(
                x=x_hs, y=hs_int_co, name="Internally audited (Company)",
                mode="lines",
                line=dict(color="#F5A623", width=2.2, dash="dash"),
                hovertemplate="Company Internal: %{y:.1f}%<extra></extra>",
                cliponaxis=False,
            ), secondary_y=True)

            lay_hs = _blt("H&S audited sites — TIP vs Company (%)", 530, r=80)
            lay_hs["barmode"]    = "group"
            lay_hs["showlegend"] = False
            lay_hs["hovermode"]  = "x unified"
            lay_hs["margin"]     = dict(l=120, r=80, t=60, b=30)
            lay_hs["yaxis"]["domain"] = [0.38, 1.0]
            lay_hs["yaxis"]["title"]  = dict(
                text="<b>Externally audited sites (%)</b>",
                font=dict(size=11, color="#6f7882", family="Arial"),
            )
            lay_hs["yaxis"]["tickfont"] = dict(size=11, color="#6f7882", family="Arial")
            lay_hs["yaxis2"] = dict(
                overlaying="y", side="right",
                showgrid=False, zeroline=False,
                showline=True, linecolor="#9aa1a9", linewidth=1.2,
                tickfont=dict(size=11, color="#6f7882", family="Arial"),
                showticklabels=True, autorange=True,
                domain=[0.38, 1.0],
                title=dict(text="<b>Internally audited sites (%)</b>",
                           font=dict(size=11, color="#6f7882", family="Arial")),
            )
            lay_hs["xaxis"].update(dict(
                domain=[0.0, 1.0], tickmode="array",
                tickvals=x_hs, ticktext=[str(y) for y in ys], type="linear",
            ))
            fig_hs.update_layout(**lay_hs)
            fig_hs.update_yaxes(showticklabels=True, showline=True, linecolor="#9aa1a9")

            rows_hs = [
                (0.30, "#3DBDB5", "■",   "External (TIP)",     hs_ext_tip, "{:.1f}%"),
                (0.20, "#1A1A2E", "■",   "External (Company)", hs_ext_co,  "{:.1f}%"),
                (0.10, "#2a2825", "—●—", "Internal (TIP)",     hs_int_tip, "{:.1f}%"),
                (0.02, "#F5A623", "—◉—", "Internal (Company)", hs_int_co,  "{:.1f}%"),
            ]
            for (y_pos, color, sym, label, vals, fmt) in rows_hs:
                fig_hs.add_annotation(
                    text=f"<span style=\'color:{color}\'>{sym}</span> {label}",
                    xref="paper", yref="paper",
                    x=-0.0042, y=y_pos, xanchor="right", yanchor="middle",
                    showarrow=False, font=dict(size=8.5, color="#374151", family="Arial"),
                )
                for xi, val in zip(x_hs, vals):
                    if val is not None:
                        fig_hs.add_annotation(
                            text=fmt.format(val),
                            xref="x", yref="paper",
                            x=xi, y=y_pos, xanchor="center", yanchor="middle",
                            showarrow=False, font=dict(size=9, color="#374151", family="Arial"),
                        )
            st.plotly_chart(fig_hs, use_container_width=True,
                            key=_chart_key(company, rep_year, "hs1"))

        with p2:
            # ── Female representation: employees + board — TIP static + Company ──
            fem_emp_tip = [_tip_people_val("women_total", y) for y in ys]
            fem_brd_tip = [_tip_people_val("women_board", y) for y in ys]

            # Company: compute from raw counts in supplementary data
            fem_emp_co, fem_brd_co = [], []
            for y in ys:
                sy = _load_supplementary(company, y) or {}
                # female_employees / total_employees
                fe = sy.get("female_employees")
                te = sy.get("total_employees")
                fem_emp_co.append(float(fe) / float(te) * 100
                                  if fe is not None and te and float(te) > 0 else 0)
                # female_board / board_total
                fb = sy.get("female_board")
                tb = sy.get("board_total")
                fem_brd_co.append(float(fb) / float(tb) * 100
                                  if fb is not None and tb and float(tb) > 0 else 0)

            x_fem = list(range(len(ys)))
            fig_fem = _msp3(specs=[[{"secondary_y": True}]])

            fig_fem.add_trace(go.Bar(
                x=x_fem, y=fem_emp_tip, name="% Women employees (TIP)",
                marker=dict(color="#3DBDB5", line=dict(width=0)), width=0.32,
                hovertemplate="TIP Women emp: %{y:.1f}%<extra></extra>",
                cliponaxis=False,
            ), secondary_y=False)
            fig_fem.add_trace(go.Bar(
                x=x_fem, y=fem_emp_co, name="% Women employees (Company)",
                marker=dict(color="#1A1A2E", line=dict(width=0)), width=0.32,
                hovertemplate="Company Women emp: %{y:.1f}%<extra></extra>",
                cliponaxis=False,
            ), secondary_y=False)
            fig_fem.add_trace(go.Scatter(
                x=x_fem, y=fem_brd_tip, name="% Women on board (TIP)",
                mode="lines",
                line=dict(color="#2a2825", width=2.2),
                hovertemplate="TIP Women board: %{y:.1f}%<extra></extra>",
                cliponaxis=False,
            ), secondary_y=True)
            fig_fem.add_trace(go.Scatter(
                x=x_fem, y=fem_brd_co, name="% Women on board (Company)",
                mode="lines",
                line=dict(color="#F5A623", width=2.2, dash="dash"),
                hovertemplate="Company Women board: %{y:.1f}%<extra></extra>",
                cliponaxis=False,
            ), secondary_y=True)

            lay_fem = _blt("Female representation — TIP vs Company (%)", 530, r=80)
            lay_fem["barmode"]    = "group"
            lay_fem["showlegend"] = False
            lay_fem["hovermode"]  = "x unified"
            lay_fem["margin"]     = dict(l=120, r=80, t=60, b=30)
            lay_fem["yaxis"]["domain"] = [0.38, 1.0]
            lay_fem["yaxis"]["title"]  = dict(
                text="<b>Women employees (%)</b>",
                font=dict(size=11, color="#6f7882", family="Arial"),
            )
            lay_fem["yaxis"]["tickfont"] = dict(size=11, color="#6f7882", family="Arial")
            lay_fem["yaxis2"] = dict(
                overlaying="y", side="right",
                showgrid=False, zeroline=False,
                showline=True, linecolor="#9aa1a9", linewidth=1.2,
                tickfont=dict(size=11, color="#6f7882", family="Arial"),
                showticklabels=True, autorange=True,
                domain=[0.38, 1.0],
                title=dict(text="<b>Women on board (%)</b>",
                           font=dict(size=11, color="#6f7882", family="Arial")),
            )
            lay_fem["xaxis"].update(dict(
                domain=[0.0, 1.0], tickmode="array",
                tickvals=x_fem, ticktext=[str(y) for y in ys], type="linear",
            ))
            fig_fem.update_layout(**lay_fem)
            fig_fem.update_yaxes(showticklabels=True, showline=True, linecolor="#9aa1a9")

            rows_fem = [
                (0.30, "#3DBDB5", "■",   "Women emp. (TIP)",    fem_emp_tip, "{:.1f}%"),
                (0.20, "#1A1A2E", "■",   "Women emp. (Company)",fem_emp_co,  "{:.1f}%"),
                (0.10, "#2a2825", "—●—", "Women board (TIP)",   fem_brd_tip, "{:.1f}%"),
                (0.02, "#F5A623", "—◉—", "Women board (Co.)",   fem_brd_co,  "{:.1f}%"),
            ]
            for (y_pos, color, sym, label, vals, fmt) in rows_fem:
                fig_fem.add_annotation(
                    text=f"<span style=\'color:{color}\'>{sym}</span> {label}",
                    xref="paper", yref="paper",
                    x=-0.0042, y=y_pos, xanchor="right", yanchor="middle",
                    showarrow=False, font=dict(size=8.5, color="#374151", family="Arial"),
                )
                for xi, val in zip(x_fem, [v for v in vals]):
                    if val is not None:
                        fig_fem.add_annotation(
                            text=fmt.format(val),
                            xref="x", yref="paper",
                            x=xi, y=y_pos, xanchor="center", yanchor="middle",
                            showarrow=False, font=dict(size=9, color="#374151", family="Arial"),
                        )
            st.plotly_chart(fig_fem, use_container_width=True,
                            key=_chart_key(company, rep_year, "fem1"))

    # ── Full Benchmarking Report Download (replaces per-section buttons) ──────
    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
    _pdf_col2, _ = st.columns([2, 4])
    with _pdf_col2:
        _pdf_all2 = _full_bench_pdf()
        if _pdf_all2:
            st.download_button(
                "⬇  Download Full Benchmarking Report (PDF)",
                data=_pdf_all2,
                file_name=f"{company.replace(' ','_')}_Benchmarking_{rep_year}.pdf",
                mime="application/pdf", key="dl_full_bench_bottom",
                use_container_width=True, type="primary",
            )
        else:
            _pdf_err2 = st.session_state.pop("_pdf_bench_error", "")
            if _pdf_err2:
                st.error(
                    f"⚠ PDF generation failed: {_pdf_err2}\n\n"
                    f"Install with `pip install reportlab matplotlib`",
                    icon=None,
                )