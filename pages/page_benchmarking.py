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

    st.markdown(section_header_html("Benchmarking",
        "Industry peer comparison · TIP sector quartiles"), unsafe_allow_html=True)

    companies_in_db = dl.get_companies(state.CONSOLIDATED_DF) or state.COMPANIES
    is_dss = st.session_state.get("is_dss", False)

    # ── Selectors: Company | Time range  (no Year — auto from most recent data) ──
    _b_range_opts = {
        "Last 3 years":  3,  "Last 5 years":  5,  "Last 7 years":  7,
        "Last 8 years":  8,  "Last 10 years": 10, "Last 12 years": 12, "All": 0,
    }
    if is_dss:
        default_co = (st.session_state.get("reporting_company") or
                      st.session_state.get("user_company") or companies_in_db[0])
        if default_co not in companies_in_db: default_co = companies_in_db[0]
        bc1, bc2 = st.columns([3, 1])
        with bc1:
            company = st.selectbox("Company", companies_in_db,
                                   index=companies_in_db.index(default_co),
                                   key="bench_company_dss")
        with bc2:
            _b_range_lbl = st.selectbox("Time range", list(_b_range_opts.keys()),
                                        index=1, key="bench_year_range")
    else:
        company  = st.session_state.user_company
        bc2, _   = st.columns([1, 3])
        with bc2:
            _b_range_lbl = st.selectbox("Time range", list(_b_range_opts.keys()),
                                        index=1, key="bench_year_range")

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

    # ── Enhanced KPI summary boxes with position bar ──────────────────────────
    chip_cols = st.columns(5)
    for i, (b, color) in enumerate(zip(BM, KPI_COLORS)):
        # Position within sector range as 0–100
        rng = max(b._hi - b._lo, 0.001)
        pos = (b.company_value - b._lo) / rng   # 0=best for lb, 1=worst
        pos_pct = (1 - pos) * 100 if b.lower_is_better else pos * 100  # 100=best always
        pos_pct = max(0, min(100, pos_pct))
        rank_col = GREEN if pos_pct >= 70 else (AMBER if pos_pct >= 40 else RED)
        rank_lbl = ("Top quartile" if pos_pct >= 75 else
                    "Above median" if pos_pct >= 50 else
                    "Below median" if pos_pct >= 25 else "Bottom quartile")
        with chip_cols[i]:
            st.markdown(f"""
            <div style="background:#fff;border:1px solid {BORDER};border-radius:8px;
                padding:12px;animation:tipFadeIn 400ms ease-out {i*60}ms both">
              <div style="font-size:9.5px;color:{MUTED};font-weight:600;text-transform:uppercase;
                  letter-spacing:.5px;margin-bottom:6px">{b.kpi_name}</div>
              <div style="font-size:22px;font-weight:700;color:{color};
                  font-variant-numeric:tabular-nums;line-height:1">{b.company_value:.2f}</div>
              <div style="font-size:9px;color:{MUTED};margin-bottom:8px">{b.unit}</div>
              <div style="background:#F1F5F9;border-radius:4px;height:5px;overflow:hidden;margin-bottom:5px">
                <div style="background:{rank_col};width:{pos_pct:.0f}%;height:100%;border-radius:4px;
                    transition:width 1s ease"></div>
              </div>
              <div style="display:flex;justify-content:space-between;font-size:9px;color:{MUTED}">
                <span>{"Worst" if b.lower_is_better else "Low"}</span>
                <span style="color:{rank_col};font-weight:600">{rank_lbl}</span>
                <span>{"Best" if b.lower_is_better else "High"}</span>
              </div>
            </div>""", unsafe_allow_html=True)

    st.markdown('<div style="height:10px"></div>', unsafe_allow_html=True)

    # ── Helpers ────────────────────────────────────────────────────────────────
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

            # ── General ──────────────────────────────────────────────────────
            cursor = _section_title(cv, "General — ESG Performance Overview", cursor)
            dims = ["CO₂ Intensity","Energy Intensity","Water Intensity","Renewable Elec.","Waste Recovery"]
            co_scores = []
            for b in BM:
                rng = max(b._hi - b._lo, 0.001)
                raw = (b.company_value - b._lo) / rng
                co_scores.append(max(0, min(100, (1-raw)*100 if b.lower_is_better else raw*100)))
            sec_sc = _compute_industry_scores(state.CONSOLIDATED_DF, rep_year)
            cursor = _embed(cv, pc.radar_chart(dims, co_scores, sec_sc, company.split()[0]),
                            cursor, "ESG Radar Profile — company vs sector median")
            positions = [max(0,min(100,(1-(b.company_value-b._lo)/max(b._hi-b._lo,0.001))*100)) if b.lower_is_better
                         else max(0,min(100,((b.company_value-b._lo)/max(b._hi-b._lo,0.001))*100)) for b in BM]
            cursor = _embed(cv, pc.position_bar(
                ["CO₂ Intensity","Energy Intensity","Water Intensity","Renewable Elec.","Waste Recovery"],
                positions, [CAT_CO2, CAT_ENERGY, CAT_WATER, CAT_RENEW, CAT_WASTE]),
                cursor, "Sector Percentile Position (100 = best)", h=45*mm)

            # ── CO₂ ──────────────────────────────────────────────────────────
            cursor = _section_title(cv, "CO₂ — Carbon Emissions & Intensity", cursor)
            sm,sq25,sq75 = _ss("Total CO2 - KPI")
            cursor = _embed(cv, pc.line_vs_sector(ys, [trend.get(y,{}).get("co2_kpi") for y in ys],
                sm,sq25,sq75,company.split()[0],"CO₂ Intensity vs Sector (tCO₂/t)",color=pc.C["co2"]),
                cursor, "Company line vs sector IQR band · Q1/Median/Q3 shown")
            cursor = _embed(cv, pc.stacked_area(ys,
                {"Scope 1":[trend.get(y,{}).get("scope1",0) for y in ys],
                 "Scope 2":[trend.get(y,{}).get("scope2",0) for y in ys]},
                "Scope 1 vs Scope 2 (tCO₂)",
                color_dict={"Scope 1":pc.C["co2"],"Scope 2":"#94A3B8"}),
                cursor, "Scope 1 = fuel combustion · Scope 2 = purchased energy")

            # ── Energy ────────────────────────────────────────────────────────
            cursor = _section_title(cv, "Energy — Intensity & Fuel Mix", cursor)
            sm,sq25,sq75 = _ss("Total energy - KPI")
            cursor = _embed(cv, pc.line_vs_sector(ys, [trend.get(y,{}).get("energy_kpi") for y in ys],
                sm,sq25,sq75,company.split()[0],"Energy Intensity vs Sector (GJ/t)",color=pc.C["energy"]),
                cursor)
            cursor = _embed(cv, pc.stacked_bar(ys,
                {"Nat. Gas":[trend.get(y,{}).get("nat_gas",0) for y in ys],
                 "Renew. Elec":[trend.get(y,{}).get("renew_gj",0) for y in ys],
                 "Diesel":[trend.get(y,{}).get("diesel",0) for y in ys],
                 "Coal":[trend.get(y,{}).get("coal",0) for y in ys]},
                "Energy Mix by Source (GJ)",
                color_dict={"Nat. Gas":pc.C["energy"],"Renew. Elec":pc.C["green"],
                            "Diesel":"#78716C","Coal":"#475569"}),
                cursor, "Fuel mix evolution over all available years")

            # ── Electricity ───────────────────────────────────────────────────
            cursor = _section_title(cv, "Electricity — Renewable vs Non-Renewable", cursor)
            total_e = [max(trend.get(y,{}).get("renew_gj",0)+trend.get(y,{}).get("nonrenew_gj",0),1) for y in ys]
            cursor = _embed(cv, pc.stacked_bar(ys,
                {"Renewable":[trend.get(y,{}).get("renew_gj",0)/t*100 for y,t in zip(ys,total_e)],
                 "Non-Renewable":[trend.get(y,{}).get("nonrenew_gj",0)/t*100 for y,t in zip(ys,total_e)]},
                "Electricity Mix (%)", pct_mode=True,
                color_dict={"Renewable":pc.C["green"],"Non-Renewable":"#94A3B8"}), cursor)
            sm,sq25,sq75 = _ss("Renewable_Electricity_Share_%")
            cursor = _embed(cv, pc.line_vs_sector(ys,
                [trend.get(y,{}).get("renew_pct") for y in ys],
                sm,sq25,sq75,company.split()[0],"Renewable Electricity Share vs Sector (%)",color=pc.C["green"]),
                cursor, "Share of electricity from renewable sources vs TIP sector quartiles")

            # ── Water ─────────────────────────────────────────────────────────
            cursor = _section_title(cv, "Water — Intensity & Withdrawals", cursor)
            sm,sq25,sq75 = _ss("Water intake - KPI")
            cursor = _embed(cv, pc.line_vs_sector(ys,
                [trend.get(y,{}).get("water_kpi") for y in ys],
                sm,sq25,sq75,company.split()[0],"Water Intensity vs Sector (m³/t)",color=pc.C["water"]),
                cursor)
            cursor = _embed(cv, pc.bar_chart(ys,
                [trend.get(y,{}).get("water_m3",0)/1e6 for y in ys],
                "Water Withdrawals (M m³)","M m³",color=pc.C["water"]), cursor)

            # ── Waste ─────────────────────────────────────────────────────────
            cursor = _section_title(cv, "Waste — Recovery Rate & Volumes", cursor)
            sm,sq25,sq75 = _ss("Waste_Recovery_Rate_%")
            cursor = _embed(cv, pc.area_with_target(ys,
                [trend.get(y,{}).get("waste_pct",0) for y in ys],
                "Waste Recovery Rate vs Sector (%)","% recovered",color=pc.C["waste"]),
                cursor, "Target 90% shown · TIP sector IQR band")
            cursor = _embed(cv, pc.stacked_bar(ys,
                {"Total Waste":[trend.get(y,{}).get("waste_total",0) for y in ys],
                 "Recovered":[trend.get(y,{}).get("waste_rec",0) for y in ys]},
                "Total Waste vs Recovered (T)",
                color_dict={"Total Waste":"#E2E8F0","Recovered":pc.C["waste"]}), cursor)

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


    # ── KPI Tabs ──────────────────────────────────────────────────────────────
    tab_co2, tab_energy, tab_elec, tab_water, tab_waste = st.tabs([
        "CO₂ Emissions", "Energy", "Electricity", "Water", "Waste"
    ])

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

    with tab_co2:
        st.caption("CO₂ intensity vs TIP sector peers — with Q1/Median/Q3 reference bands")
        c1, c2 = st.columns(2, gap="medium")
        with c1:
            st.plotly_chart(
                _trend_vs_sector("co2_kpi","Total CO2 - KPI",
                    "CO₂ Intensity vs Sector (tCO₂/t)", _TC["bar_blue2"]),
                use_container_width=True, key=_chart_key(company, rep_year, "co2t"))
        with c2:
            # Scope 1 vs Scope 2 stacked bar (TIP Fig 7 style)
            s1v = [trend[y]["scope1"] for y in ys]
            s2v = [trend[y]["scope2"] for y in ys]
            tot = [s1+s2 for s1,s2 in zip(s1v,s2v)]
            fig_sc = go.Figure()
            fig_sc.add_trace(go.Bar(x=_ys_str, y=s1v, name="Scope 1 (direct)",
                marker_color=_TC["bar_blue"], marker_line_width=0,
                text=[f"{v:.2f}" if v else "" for v in s1v],
                textposition="inside", textfont=dict(size=13, color="white", family="Arial")))
            fig_sc.add_trace(go.Bar(x=_ys_str, y=s2v, name="Scope 2 (indirect)",
                marker_color=_TC["bar_blue2"], marker_line_width=0,
                text=[f"{v:.2f}" if v else "" for v in s2v],
                textposition="inside", textfont=dict(size=13, color="white", family="Arial")))
            lay_sc = _blt("CO₂ Scope 1 vs Scope 2 trend (tCO₂)", 430)
            lay_sc["barmode"] = "stack"
            lay_sc["yaxis"]["title"] = dict(text="tCO₂", font=dict(size=11))
            fig_sc.update_layout(**lay_sc)
            st.plotly_chart(fig_sc, use_container_width=True, key=_chart_key(company, rep_year, "4"))


    with tab_energy:
        st.caption("Energy intensity & consumption mix — Q1/Median/Q3 reference bands shown")
        c1, c2 = st.columns(2, gap="medium")
        with c1:
            st.plotly_chart(
                _trend_vs_sector("energy_kpi","Total energy - KPI",
                    "Energy Intensity vs Sector (GJ/t)", _TC["bar_blue2"]),
                use_container_width=True, key=_chart_key(company, rep_year, "5"))
        with c2:
            # Fig 5 style energy mix 100% stacked
            fuel_keys = [
                ("nat_gas",    "Natural Gas",                              "#8FA5B5"),
                ("renew_gj",   "Renewable Electricity (purchased+self-gen)", _TC["bar_green"]),
                ("nonrenew_gj","Non-renewable Electricity",                 _TC["bar_sand"]),
                ("coal",       "Coal",                                      "#666"),
                ("diesel",     "Diesel/LPG/Other",                         _TC["bar_orange"]),
            ]
            totals_e = [max(sum(trend[y].get(k,0) for k,_,_ in fuel_keys), 1) for y in ys]
            traces_e = []
            for fkey, flbl, fcol in fuel_keys:
                pcts = [trend[y].get(fkey,0)/tot*100 for y,tot in zip(ys,totals_e)]
                if any(p>0 for p in pcts):
                    traces_e.append((pcts, flbl, fcol))
            st.plotly_chart(_b_stack100(_ys_str, traces_e,
                "Energy mix (%)", 430),
                use_container_width=True, key=_chart_key(company, rep_year, "6"))


    with tab_elec:
        st.caption("Electricity from renewable sources — company trend vs sector")
        c1, c2 = st.columns(2, gap="medium")
        with c1:
            # Fig 6 style — renewable vs non-renewable stacked %
            total_e2 = [max(trend[y]["renew_gj"]+trend[y]["nonrenew_gj"], 1) for y in ys]
            renew_pct_co  = [trend[y]["renew_gj"]/t*100 for y,t in zip(ys,total_e2)]
            nonren_pct_co = [100-v for v in renew_pct_co]
            fig_e6 = go.Figure()
            fig_e6.add_trace(go.Bar(x=_ys_str, y=renew_pct_co,
                name="Renewable electricity (GJ)", marker_color=_TC["bar_blue2"],
                marker_line_width=0,
                text=[f"{v:.1f}%" if v else "" for v in renew_pct_co],
                textposition="inside", textfont=dict(size=13, color="white", family="Arial")))
            fig_e6.add_trace(go.Bar(x=_ys_str, y=nonren_pct_co,
                name="Non-renewable electricity (GJ)", marker_color=_TC["bar_sand"],
                marker_line_width=0,
                text=[f"{v:.1f}%" if v else "" for v in nonren_pct_co],
                textposition="inside", textfont=dict(size=13, color="#2a2825", family="Arial")))
            lay_e6 = _blt("Electricity from renewable sources (%)", 430)
            lay_e6["barmode"] = "stack"
            lay_e6["yaxis"]["ticksuffix"] = "%"
            lay_e6["yaxis"]["range"] = [0,100]
            fig_e6.update_layout(**lay_e6)
            st.plotly_chart(fig_e6, use_container_width=True, key=_chart_key(company, rep_year, "7"))
        with c2:
            st.plotly_chart(
                _trend_vs_sector("renew_pct","Renewable_Electricity_Share_%",
                    "Renewable Electricity Share vs Sector (%)", _TC["bar_green"]),
                use_container_width=True, key=_chart_key(company, rep_year, "8"))


    with tab_water:
        st.caption("Water withdrawals & intensity — company trend vs sector Q1/Median/Q3")
        c1, c2 = st.columns(2, gap="medium")
        with c1:
            st.plotly_chart(
                _trend_vs_sector("water_kpi","Water intake - KPI",
                    "Water Intensity vs Sector (m³/t)", _TC["bar_blue2"]),
                use_container_width=True, key=_chart_key(company, rep_year, "9"))
        with c2:
            # Fig 9 style — water withdrawals bar + intensity line
            st.plotly_chart(_b_dbline(
                _ys_str,
                [trend[y]["water_m3"]/1e6 for y in ys],
                "Water withdrawals (M m³)", _TC["bar_beige"],
                [trend[y]["water_kpi"] for y in ys],
                "Water intensity (m³/t)", _TC["line_dark"],
                title="Water withdrawals & intensity",
                byt="Million m³", lyt="m³/t", bfmt=".2f", lfmt=".2f",
            ), use_container_width=True, key=_chart_key(company, rep_year, "10"))


    with tab_waste:
        st.caption("Waste recovery rate & volumes — company trend vs sector Q1/Median/Q3")
        c1, c2 = st.columns(2, gap="medium")
        with c1:
            st.plotly_chart(
                _trend_vs_sector("waste_pct","Waste_Recovery_Rate_%",
                    "Waste Recovery Rate vs Sector (%)", _TC["bar_blue2"]),
                use_container_width=True, key=_chart_key(company, rep_year, "11"))
        with c2:
            # Fig 10/11 style — waste total bar + recovery % stacked
            wt_vals = [trend[y]["waste_total"] for y in ys]
            wr_vals = [trend[y]["waste_rec"]   for y in ys]
            we_vals = [max(t-r,0) for t,r in zip(wt_vals,wr_vals)]
            wt_safe = [max(t,1) for t in wt_vals]
            wr_pct  = [r/t*100 for r,t in zip(wr_vals,wt_safe)]
            we_pct  = [100-v for v in wr_pct]
            st.plotly_chart(_b_stack100(
                _ys_str,
                [(wr_pct, "Sent for recovery (%)",  _TC["bar_beige"]),
                 (we_pct, "Sent for disposal (%)",  _TC["bar_blue2"])],
                title="Waste recovery vs disposal (%)", h=430,
            ), use_container_width=True, key=_chart_key(company, rep_year, "12"))


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