"""
pages/page_analysis.py — DSS cross-company analysis charts (CO₂, Energy, Water, Waste, Advanced).
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
import html as _html
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


def page_analysis():
    import plotly.graph_objects as go

    data_src = "live consolidated data" if not state.CONSOLIDATED_DF.empty else "built-in demo data"
    st.markdown("## Analysis & Trends")
    st.caption(f"Sector aggregated across all TIP member companies · Source: {data_src}")

    if state.USING_FALLBACK:
        st.warning("⚠️ No consolidated master CSV found — charts show illustrative fallback data.", icon=None)

    # ── Selectors: Company | Time range  (no Year — auto from range) ─────────────
    overlay_company = None
    overlay_year    = None
    _range_opts = {
        "Last 3 years":  3,  "Last 5 years":  5,  "Last 7 years":  7,
        "Last 8 years":  8,  "Last 10 years": 10, "Last 12 years": 12, "All": 0,
    }

    if st.session_state.get("is_dss", False) and not state.CONSOLIDATED_DF.empty:
        companies_in_db = dl.get_companies(state.CONSOLIDATED_DF) or state.COMPANIES
        co_options  = ["All Companies"] + companies_in_db
        sel_co_col, sel_rng_col = st.columns([3, 1])
        with sel_co_col:
            overlay_sel = st.selectbox("Company", co_options, key="analysis_overlay_co")
        with sel_rng_col:
            _range_label = st.selectbox("Time range", list(_range_opts.keys()),
                                        index=1, key="analysis_year_range")
        if overlay_sel != "All Companies":
            overlay_company = overlay_sel
    else:
        _range_label = st.selectbox("Time range", list(_range_opts.keys()),
                                    index=1, key="analysis_year_range")

    _n = _range_opts[_range_label]
    yrs_int = state.LONG_YEARS[-_n:] if _n else state.LONG_YEARS
    yrs     = [str(y) for y in yrs_int]
    # Auto-derive overlay_year as most recent year with data for selected company
    if overlay_company:
        _co_avail_yrs = dl.get_years(state.CONSOLIDATED_DF, overlay_company) or [state.CURR_YEAR]
        _co_in_range  = [y for y in _co_avail_yrs if y in yrs_int]
        overlay_year  = max(_co_in_range) if _co_in_range else max(_co_avail_yrs)
    else:
        overlay_year = yrs_int[-1] if yrs_int else state.CURR_YEAR

    C = {
        "navy":"#0A2240","red":"#C8102E","green":"#00916E","blue":"#1D4ED8",
        "teal":"#0891B2","amber":"#D97706","purple":"#7C3AED","coral":"#EA580C",
        "gray":"#6B7280","grid":"#e6eaed","bg":"#f5f4f2",
    }
    PALETTE_10 = ["#C8102E","#0A2240","#00916E","#1D4ED8","#D97706",
                  "#7C3AED","#0891B2","#EA580C","#059669","#DB2777"]

    def _layout(title="", height=300, legend_h=True, **kw):
        base = dict(
            title=dict(text=title, font=dict(size=13, color=C["navy"])),
            height=height, margin=dict(l=10,r=10,t=40,b=30),
            plot_bgcolor=C["bg"], paper_bgcolor=C["bg"],
            xaxis=dict(gridcolor=C["grid"], showline=True, linecolor="#9aa1a9", tickfont=dict(size=12, color="#6f7882")),
            yaxis=dict(gridcolor=C["grid"], showline=True, linecolor="#9aa1a9", tickfont=dict(size=12, color="#6f7882")),
            legend=dict(orientation="h" if legend_h else "v",
                        y=-0.22 if legend_h else 1, font=dict(size=12, color="#6f7882")),
            hovermode="x unified",
        )
        base.update(kw)
        return base

    def _line(x, y, name, color, dash="solid", width=2, fill=None, fill_color=None, marker_size=4):
        kw = dict(x=x, y=y, name=name, mode="lines+markers",
                  line=dict(color=color, width=width, dash=dash),
                  marker=dict(size=marker_size, color=color),
                  hovertemplate="%{y:.2f}<extra>" + name + "</extra>")
        if fill:
            kw["fill"] = fill
            kw["fillcolor"] = fill_color or "rgba(128,128,128,.08)"
        return go.Scatter(**kw)

    df = state.CONSOLIDATED_DF
    has_wide = (not df.empty and "Row_Label" not in df.columns)

    def _sector(col, divisor=1):
        if has_wide and col in df.columns:
            return (df.groupby("Year")[col].sum() / divisor).reindex(yrs_int)
        return None

    def _sector_mean(col):
        if has_wide and col in df.columns:
            return df.groupby("Year")[col].mean().reindex(yrs_int)
        return None

    def _co_series(company, col, divisor=1):
        if has_wide and col in df.columns:
            s = df[df["Company"]==company].set_index("Year")[col] / divisor
            return s.reindex(yrs_int)
        return None

    def _safe(series, fallback):
        if series is None:
            return fallback
        result = []
        for i, v in enumerate(series.values):
            fb = fallback[i] if i < len(fallback) else (fallback[-1] if fallback else 0.0)
            try:   result.append(float(v) if (v == v and v is not None) else fb)
            except: result.append(fb)
        return result

    companies = sorted(df["Company"].unique().tolist()) if has_wide else []

    energy_total  = _safe(_sector("Total energy", 1e6),            state.LONG_DATA["energy"])
    co2_total     = _safe(_sector("Total CO2", 1e6),               state.LONG_DATA["co2"])
    scope1_total  = _safe(_sector("Total CO2 - Scope 1", 1e6),     state.LONG_DATA["scope1"])
    scope2_total  = _safe(_sector("Total CO2 - Scope 2", 1e6),     state.LONG_DATA["scope2"])
    water_total   = _safe(_sector("Water intake", 1e6),            state.LONG_DATA["water"])
    energy_kpi    = _safe(_sector_mean("Total energy - KPI"),      state.LONG_DATA["energy_kpi"])
    co2_kpi       = _safe(_sector_mean("Total CO2 - KPI"),         state.LONG_DATA["co2_kpi"])
    water_kpi_v   = _safe(_sector_mean("Water intake - KPI"),      [None]*len(yrs_int))
    renew_pct     = _safe(_sector_mean("Renewable_Electricity_Share_%"), state.LONG_DATA["renew_pct"])
    waste_recov   = _safe(_sector_mean("Waste_Recovery_Rate_%"),   state.LONG_DATA["waste_recov"])
    iso_cert      = _safe(_sector_mean("ISO_Certification_%"),     [93.0]*len(yrs_int))
    waste_total_v = _safe(_sector("Total Waste"),                  [v*330000 for v in state.LONG_DATA["prod"]])
    waste_recov_a = _safe(_sector("Waste Recovered"),              [v*280000 for v in state.LONG_DATA["prod"]])

    # ── Headline KPI strip — dynamic: company data or sector totals ──────────────
    def _delta(cur, prv, good_if_down=True):
        if prv and prv != 0:
            pct = (cur - prv) / abs(prv) * 100
            good = (pct < 0) == good_if_down
            arrow = "▼" if pct < 0 else "▲"
            col = "#00916E" if good else "#C8102E"
            return f'<span style="color:{col};font-size:11px">{arrow} {abs(pct):.1f}%</span>'
        return '<span style="font-size:11px;color:#9CA3AF">—</span>'

    latest_yr = yrs_int[-1] if yrs_int else state.CURR_YEAR
    _first_yr = yrs_int[0]  if yrs_int else state.CURR_YEAR - 10
    _last_yr  = yrs_int[-1] if yrs_int else state.CURR_YEAR

    if overlay_company:
        # Company-specific KPI boxes
        ov_inp, ov_out = _load_company_year_outputs(overlay_company, overlay_year)
        ov_rt = max(ov_inp.renew_elec_purchased + ov_inp.nonrenew_elec_purchased
                    + ov_inp.self_gen_elec, 1)
        ov_renew = ov_inp.renew_elec_purchased / ov_rt * 100

        # Prior year for delta
        ov_hist   = dl.get_company_hist(state.CONSOLIDATED_DF, overlay_company)
        ov_prev_out = None
        if overlay_year - 1 in dl.get_years(state.CONSOLIDATED_DF, overlay_company):
            _, ov_prev_out = _load_company_year_outputs(overlay_company, overlay_year - 1)

        def _co_delta(cur, prev_val, good_if_down=True):
            return _delta(cur, prev_val, good_if_down) if prev_val else _delta(cur, None)

        kpi_items = [
            (f"Total Energy {overlay_year}", f"{ov_inp.nat_gas + ov_inp.nonrenew_elec_purchased + ov_inp.renew_elec_purchased:.0f}",
             "GJ",
             _co_delta(ov_out.total_energy, ov_prev_out.total_energy if ov_prev_out else None)),
            (f"Total CO₂ {overlay_year}", f"{ov_out.total_co2:,.0f}", "tCO₂",
             _co_delta(ov_out.total_co2, ov_prev_out.total_co2 if ov_prev_out else None)),
            ("CO₂ Intensity",  f"{ov_out.co2_kpi:.3f}", "tCO₂/t",
             _co_delta(ov_out.co2_kpi, ov_prev_out.co2_kpi if ov_prev_out else None)),
            ("Renewable Electricity", f"{ov_renew:.1f}%", "of elec",
             _co_delta(ov_renew, None, False)),
            ("Waste Recovery", f"{ov_out.waste_recovery_pct*100:.1f}%", "of waste",
             _co_delta(ov_out.waste_recovery_pct, ov_prev_out.waste_recovery_pct if ov_prev_out else None, False)),
        ]
    else:
        # Sector aggregate KPI boxes (dynamic from real data)
        kpi_items = [
            (f"Total Energy {latest_yr}", f"{energy_total[-1]:.1f}M", "GJ",
             _delta(energy_total[-1], energy_total[-2] if len(energy_total) > 1 else None, True)),
            (f"Total CO₂ {latest_yr}", f"{co2_total[-1]:.2f}M", "tCO₂",
             _delta(co2_total[-1], co2_total[-2] if len(co2_total) > 1 else None, True)),
            ("CO₂ Intensity", f"{co2_kpi[-1]:.3f}", "tCO₂/t",
             _delta(co2_kpi[-1], co2_kpi[-2] if len(co2_kpi) > 1 else None, True)),
            ("Renewable Electricity", f"{renew_pct[-1]:.1f}%", "of elec",
             _delta(renew_pct[-1], renew_pct[-2] if len(renew_pct) > 1 else None, False)),
            ("Waste Recovery", f"{waste_recov[-1]:.1f}%", "of waste",
             _delta(waste_recov[-1], waste_recov[-2] if len(waste_recov) > 1 else None, False)),
        ]
    kpi_cols = st.columns(5)
    for i, (label, val, unit, delta_html) in enumerate(kpi_items):
        kpi_cols[i].markdown(
            f'''<div style="border:0.5px solid #E5E7EB;border-radius:8px;
                padding:12px 14px;background:#fff">
            <div style="font-size:11px;color:#6B7280;margin-bottom:3px">{label}</div>
            <div style="font-size:21px;font-weight:600;color:#0A2240;line-height:1.1">{val}</div>
            <div style="font-size:11px;color:#9CA3AF">{unit}</div>
            <div style="margin-top:3px">{delta_html}</div>
            </div>''', unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Tabs — client sees own-company tabs; DSS sees all tabs ───────────────
    is_dss_user = st.session_state.get("is_dss", False)

    if is_dss_user:
        tab_gen, tab_energy, tab_co2, tab_p3, tab_p4, tab_people = st.tabs([
            "Overview",
            "Energy",
            "CO₂ Emissions",
            "Water",
            "Waste & Environment",
            "People & Governance",
        ])
        tab_p12 = tab_energy   # keep backward compat alias
    else:
        tab_gen, tab_energy, tab_co2, tab_p3, tab_p4, tab_people = st.tabs([
            "Overview",
            "Energy",
            "CO₂ Emissions",
            "Water",
            "Waste & Environment",
            "People & Governance",
        ])
        tab_p12 = tab_energy

    # ══════════════════════════════════════════════════════════════════════════
    # TIP CHART DESIGN SYSTEM — matches official TIP ESG report (2021-2024)
    # ══════════════════════════════════════════════════════════════════════════
    from plotly.subplots import make_subplots

    # TIP colours (official report palette)
    TC = {
        "bar_blue":   "#B8CDD9",   # light blue bars  (energy, CO2 absolute)
        "bar_blue2":  "#2D4A5A",   # dark teal bars   (scope 2, steam, SBT-none)
        "bar_beige":  "#C8B49A",   # beige bars       (water, waste)
        "bar_green":  "#7BAF74",   # green            (renewable, SBT-validated)
        "bar_orange": "#E0935A",   # orange           (other fuels)
        "bar_sand":   "#D4C5A9",   # sand             (non-renew elec background)
        "bar_commit": "#9FB8C5",   # soft blue        (SBT-committed)
        "line_dark":  "#2D4A5A",   # primary line
        "line_light": "#8FA5B5",   # secondary line
    }
    # Text colours: white on dark bars, near-black on light bars
    TXT = {
        "bar_blue":   "#2C3E50",
        "bar_blue2":  "white",
        "bar_beige":  "#2C3E50",
        "bar_green":  "white",
        "bar_orange": "white",
        "bar_sand":   "#2C3E50",
        "bar_commit": "#2C3E50",
    }

    def _tlayout(title="", h=330, r=65, show_legend=True, leg_y=-0.24):
        return dict(
            title=dict(text=f"<b>{title}</b>",
                       font=dict(size=14, color="#2a2825", family="Arial, sans-serif"), x=0),
            height=h, margin=dict(l=55, r=r, t=50, b=60),
            plot_bgcolor="#f5f4f2", paper_bgcolor="#f5f4f2",
            xaxis=dict(
                showgrid=False, linecolor="#9aa1a9", linewidth=1.2,
                showline=True, mirror=False,
                tickfont=dict(size=12, color="#6f7882", family="Arial"),
                tickangle=0,
                type="category",
            ),
            yaxis=dict(
                showgrid=True, gridcolor="#e6eaed", zeroline=False,
                showline=True, linecolor="#9aa1a9", linewidth=1.2,
                tickfont=dict(size=12, color="#6f7882", family="Arial"),
                showticklabels=True,
                autorange=True,
            ),
            legend=dict(orientation="h", x=0.5, xanchor="center", y=leg_y,
                        font=dict(size=12, color="#6f7882"), bgcolor="rgba(0,0,0,0)"),
            hovermode="x unified", showlegend=show_legend,
        )

    def _y2(label=""):
        """Right Y-axis — TIP report styling."""
        return dict(
            tickfont=dict(size=12, color="#6f7882", family="Arial"),
            showgrid=False, zeroline=False,
            showline=True, linecolor="#9aa1a9", linewidth=1.2,
            showticklabels=True,
            autorange=True,
            title=dict(text=f"<b>{label}</b>" if label else "",
                       font=dict(size=12, color="#6f7882", family="Arial")),
        )

    def _omk(col, sz=9):
        """Open-circle marker."""
        return dict(symbol="circle", size=sz, color="white",
                    line=dict(color=col, width=2))


    def _dual(xs, bv, bl, bc, lv, ll, lc, title="", h=430,
              bfmt=".1f", lfmt=".2f", byt="", lyt=""):
        """Dual-axis bar (left y) + line (right y).
        TIP Annual Report style: values printed in two rows BELOW the x-axis.
        Row 1 (paper y≈0.21): bar label (left) + bar values per year
        Row 2 (paper y≈0.10): line label (left) + line values per year
        Plot area occupies the top 68% of the figure (domain [0.42, 1.0]).
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

        fig = make_subplots(specs=[[{"secondary_y": True}]])

        # ── Bar trace (no inline text — values go below x-axis) ──────────────
        fig.add_trace(go.Bar(
            x=x_idx, y=bv, name=bl,
            marker_color=bc, marker_line_width=0, width=0.52,
            hovertemplate=f"{bl}: %{{y:{bfmt}}}<extra></extra>",
            cliponaxis=False,
        ), secondary_y=False)

        # ── Line trace (no inline text) ───────────────────────────────────────
        fig.add_trace(go.Scatter(
            x=x_idx, y=lv, name=ll,
            mode="lines",                      # no markers — removes top-left circle
            line=dict(color=lc, width=2.2),
            hovertemplate=f"{ll}: %{{y:{lfmt}}}<extra></extra>",
            cliponaxis=False,
        ), secondary_y=True)

        lay = _tlayout(title, h, r=115)
        lay["showlegend"] = False   # annotations serve as legend

        # Headroom above max bar
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
        lay["yaxis2"] = _y2(lyt)
        lay["yaxis2"]["domain"] = [0.42, 1.0]

        # x-axis: numeric indices + year text labels, 18% left gap for y-label
        lay["xaxis"].update(dict(
            domain=[0.18, 1.0],
            tickmode="array",
            tickvals=x_idx,
            ticktext=[str(x) for x in xs],
            type="linear",
        ))
        lay["margin"]["t"] = 55
        lay["margin"]["b"] = 30

        fig.update_layout(**lay)
        fig.update_yaxes(showticklabels=True, showline=True, linecolor="#9aa1a9")

        # ── Annotation rows below x-axis ─────────────────────────────────────
        fig.add_annotation(x=0.01, y=0.28, xref="paper", yref="paper",
            text=f"■ {bl}", showarrow=False,
            font=dict(size=12, color=bc, family="Arial"),
            align="left", xanchor="left")
        fig.add_annotation(x=0.01, y=0.13, xref="paper", yref="paper",
            text=f"—○— {ll}", showarrow=False,
            font=dict(size=12, color=lc, family="Arial"),
            align="left", xanchor="left")
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

    def _stack100(xs, traces, title="", h=430):
        """100% stacked bar. Text colour chosen per bar colour. Larger, bold labels."""
        fig = go.Figure()
        _dark = ("#2D4A5A", "#7BAF74", "#E0935A", "#9FB8C5")
        for (vals, lbl, bc) in traces:
            tc_col = "white" if bc in _dark else "#1C2E3F"
            fig.add_trace(go.Bar(
                x=xs, y=vals, name=lbl, marker_color=bc, marker_line_width=0,
                text=[f"<b>{v:.1f}%</b>" if v and v > 6 else "" for v in vals],
                textposition="inside",
                insidetextanchor="middle",
                textfont=dict(size=13, color=tc_col, family="Arial, sans-serif"),
                hovertemplate=f"{lbl}: %{{y:.1f}}%<extra></extra>",
            ))
        lay = _tlayout(title, h)
        lay["barmode"] = "stack"
        lay["yaxis"]["ticksuffix"] = "%"
        lay["yaxis"]["range"] = [0, 100]
        fig.update_layout(**lay)
        return fig

    def _stackabs(xs, traces, title="", h=330):
        """Absolute stacked bar expressed as % (Fig 6 style). Larger, bold labels."""
        fig = go.Figure()
        for (pct_vals, lbl, bc, txt_vals) in traces:
            tc_col = "white" if bc in ("#2D4A5A","#7BAF74","#E0935A") else "#1C2E3F"
            # Make text bold
            bold_txts = [f"<b>{t}</b>" if t else "" for t in txt_vals]
            fig.add_trace(go.Bar(
                x=xs, y=pct_vals, name=lbl, marker_color=bc, marker_line_width=0,
                text=bold_txts, textposition="inside",
                insidetextanchor="middle",
                textfont=dict(size=13, color=tc_col, family="Arial, sans-serif"),
                hovertemplate=f"{lbl}: %{{y:.1f}}%<extra></extra>",
            ))
        lay = _tlayout(title, h)
        lay["barmode"] = "stack"
        lay["yaxis"]["ticksuffix"] = "%"
        lay["yaxis"]["range"] = [0, 100]
        fig.update_layout(**lay)
        return fig

    def _dline(xs, s1v, s1l, s1c, s2v, s2l, s2c, title="", h=430,
               s1f=".1f", s2f=".1f", yt="", s2yt="", right_y=False):
        """Dual-line chart with open-circle markers. Larger labels, alternating positions."""
        def _line_txt(vals, fmt):
            return [f"{v:{fmt}}" if v is not None and v == v else "" for v in vals]

        def _alt_pos(n):
            return ["top center" if i % 2 == 0 else "bottom center" for i in range(n)]

        n = len(xs)
        if right_y:
            fig = make_subplots(specs=[[{"secondary_y": True}]])
            fig.add_trace(go.Scatter(x=xs, y=s1v, name=s1l,
                mode="lines+text",
                line=dict(color=s1c, width=2.5),
                text=_line_txt(s1v, s1f),
                textposition=_alt_pos(n),
                textfont=dict(size=12, color="#1C2E3F", family="Arial, sans-serif"),
            ), secondary_y=False)
            fig.add_trace(go.Scatter(x=xs, y=s2v, name=s2l,
                mode="lines+text",
                line=dict(color=s2c, width=2.5),
                text=_line_txt(s2v, s2f),
                textposition=_alt_pos(n),
                textfont=dict(size=12, color="#1C2E3F", family="Arial, sans-serif"),
            ), secondary_y=True)
            lay = _tlayout(title, h)
            lay["yaxis"]["title"]  = dict(text=yt, font=dict(size=10, color="#666"))
            lay["yaxis"]["ticksuffix"] = "%"
            lay["yaxis2"] = _y2(s2yt)
            fig.update_layout(**lay)
        else:
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=xs, y=s1v, name=s1l,
                mode="lines+text",
                line=dict(color=s1c, width=2.5),
                text=_line_txt(s1v, s1f),
                textposition=_alt_pos(n),
                textfont=dict(size=12, color="#1C2E3F", family="Arial, sans-serif"),
            ))
            fig.add_trace(go.Scatter(x=xs, y=s2v, name=s2l,
                mode="lines+text",
                line=dict(color=s2c, width=2.5),
                text=_line_txt(s2v, s2f),
                textposition=_alt_pos(n),
                textfont=dict(size=12, color="#1C2E3F", family="Arial, sans-serif"),
            ))
            lay = _tlayout(title, h)
            lay["yaxis"]["title"] = dict(text=yt, font=dict(size=10, color="#666"))
            lay["yaxis"]["ticksuffix"] = "%"
            fig.update_layout(**lay)
        return fig

    def _ck(suf): return _chart_key(overlay_company or "sector", overlay_year or 0, suf)

    # ── Sector series ──────────────────────────────────────────────────────────
    prod_total   = _safe(_sector("Production", 1e6),               state.LONG_DATA["prod"])
    sites_total  = _safe(_sector("Total no. of sites"),            [None]*len(yrs_int))
    iso_cert     = _safe(_sector_mean("ISO_Certification_%"),      [97.0]*len(yrs_int))

    # Energy mix components (absolute GJ, then computed as %)
    _sg          = _safe(_sector("Purchased Steam"),               [1.5e7]*len(yrs_int))
    _rg          = _safe(_sector("Renewable Electricity Purchased"),[2e7]*len(yrs_int))
    _nrg         = _safe(_sector("Non-Renewable Electricity Purchased"),[1.4e8]*len(yrs_int))
    _natg        = _safe(_sector("Natural Gas"),                   [2.3e8]*len(yrs_int))
    _coal        = _safe(_sector("Coal"),                          [5e5]*len(yrs_int))
    _diesel      = _safe(_sector("Diesel"),                        [2e6]*len(yrs_int))
    _lpg         = _safe(_sector("LPG"),                           [1.5e7]*len(yrs_int))
    _bio         = _safe(_sector("Biomass"),                       [1e5]*len(yrs_int))
    _other_sum   = [c+d+l+b for c,d,l,b in zip(_coal,_diesel,_lpg,_bio)]

    # Electricity renewable % (per year)
    _te          = [max(r+n,1) for r,n in zip(_rg,_nrg)]
    _renew_pct_v = [r/t*100  for r,t in zip(_rg,_te)]
    _nonrw_pct_v = [100-v    for v in _renew_pct_v]

    # Energy mix as % of total energy
    def _fp(vals): return [v/(max(e,1)*1e6)*100 for v,e in zip(vals, energy_total)]
    _steam_pct   = _fp(_sg)
    _renew_pct2  = _fp(_rg)
    _nonrw_pct2  = _fp(_nrg)
    _natg_pct    = _fp(_natg)
    _other_pct   = _fp(_other_sum)

    # Waste
    waste_recov_pct = [r/max(t,1)*100 for r,t in zip(waste_recov_a, waste_total_v)]
    waste_elim_pct  = [100-v          for v in waste_recov_pct]
    waste_intensity = [wt/max(p*1e6,1)*1000
                       for wt,p in zip(waste_total_v, prod_total)]  # kg/t

    # Production index relative to first year
    _p0 = max(prod_total[0], 1)
    prod_idx = [v/_p0*100 for v in prod_total]

    # Social / People metrics — sourced from live data where columns exist,
    # else display an info panel (do NOT hardcode)
    _HS_EXT_COL   = "HS_External_Audit_%"   # not yet in schema
    _HS_INT_COL   = "HS_Internal_Audit_%"   # not yet in schema
    _WOMEN_BD_COL = "Women_Board_%"         # not yet in schema
    _WOMEN_TT_COL = "Women_Total_%"         # not yet in schema
    _SBT_VAL_COL  = "SBT_Validated"         # not yet in schema
    _SBT_COM_COL  = "SBT_Committed"         # not yet in schema
    _SBT_NON_COL  = "SBT_Not_Committed"     # not yet in schema
    _social_available = has_wide and all(
        c in df.columns for c in [_HS_EXT_COL, _HS_INT_COL, _WOMEN_BD_COL, _WOMEN_TT_COL])

    def _social_series(col):
        if has_wide and col in df.columns:
            return _safe(_sector_mean(col), [None]*len(yrs_int))
        return None

    _hs_ext  = _social_series(_HS_EXT_COL)
    _hs_int  = _social_series(_HS_INT_COL)
    _wb      = _social_series(_WOMEN_BD_COL)
    _wt      = _social_series(_WOMEN_TT_COL)

    def _sbt_series(col):
        if has_wide and col in df.columns:
            return _safe(_sector(""+col), [None]*len(yrs_int))
        return None

    _sbt_v = _sbt_series(_SBT_VAL_COL)
    _sbt_c = _sbt_series(_SBT_COM_COL)
    _sbt_n = _sbt_series(_SBT_NON_COL)
    _sbt_available = _sbt_v is not None and any(v is not None for v in _sbt_v)

    def _no_data_msg(metric, pathway):
        st.info(
            f"**{metric}** data is tracked in the TIP annual report under **{pathway}**. "
            "To enable this chart, add the corresponding fields to the KPI submission form "
            "and rebuild the master database.",
            icon="📊"
        )

    # ── Overview Tab ────────────────────────────────────────────────────────────
    with tab_gen:
        lbl_pfx = f"({overlay_company.split()[0]})" if overlay_company else "(Sector)"
        st.caption(f"KPI headline summary · {lbl_pfx} · {yrs_int[0]}–{yrs_int[-1]}")

        def _ov(col, divisor=1):
            if overlay_company and has_wide and col in df.columns:
                s = df[df["Company"]==overlay_company].set_index("Year")[col]/divisor
                return _safe(s.reindex(yrs_int), [None]*len(yrs_int))
            return None

        plot_energy = _ov("Total energy", 1e6) or energy_total
        plot_co2    = _ov("Total CO2",    1e6) or co2_total
        plot_water  = _ov("Water intake", 1e6) or water_total
        plot_ekpi   = _ov("Total energy - KPI") or energy_kpi
        plot_c2kpi  = _ov("Total CO2 - KPI")    or co2_kpi
        plot_wkpi   = _ov("Water intake - KPI") or water_kpi_v

        # 5 KPI cards
        def _delta(cur, prv, good_if_down=True):
            if prv and prv != 0:
                pct = (cur - prv)/abs(prv)*100
                good = (pct < 0) == good_if_down
                arrow = "▼" if pct < 0 else "▲"
                col2 = "#00916E" if good else "#C8102E"
                return f'<span style="color:{col2};font-size:11px">{arrow} {abs(pct):.1f}%</span>'
            return '<span style="font-size:11px;color:#9CA3AF">—</span>'

        latest_yr = yrs_int[-1] if yrs_int else state.CURR_YEAR
        _first_yr = yrs_int[0]  if yrs_int else state.CURR_YEAR - 10
        _last_yr  = yrs_int[-1] if yrs_int else state.CURR_YEAR

        def _sfmt(v, fmt, fallback="—"):
            """Safe format — returns fallback if v is None or NaN."""
            try:
                if v is None or v != v: return fallback
                return format(float(v), fmt)
            except Exception:
                return fallback

        kpi_items = [
            (f"Total Energy {latest_yr}", _sfmt(plot_energy[-1], ".1f") + "M", "GJ",
             _delta(plot_energy[-1], plot_energy[-2] if len(plot_energy)>1 else None, True)),
            (f"Total CO₂ {latest_yr}", _sfmt(plot_co2[-1], ".2f") + "M", "tCO₂",
             _delta(plot_co2[-1], plot_co2[-2] if len(plot_co2)>1 else None, True)),
            ("CO₂ Intensity", _sfmt(plot_c2kpi[-1], ".3f"), "tCO₂/t",
             _delta(plot_c2kpi[-1], plot_c2kpi[-2] if len(plot_c2kpi)>1 else None, True)),
            ("Renewable Electricity", _sfmt(renew_pct[-1], ".1f") + "%", "of elec",
             _delta(renew_pct[-1], renew_pct[-2] if len(renew_pct)>1 else None, False)),
            ("Waste Recovery", _sfmt(waste_recov[-1], ".1f") + "%", "of waste",
             _delta(waste_recov[-1], waste_recov[-2] if len(waste_recov)>1 else None, False)),
        ]
        st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)
        st.caption("Select a pathway tab above to view TIP ESG report charts for that KPI category.")

        # Mini overview — 2 summary charts
        c1, c2 = st.columns(2)
        with c1:
            st.plotly_chart(_dual(
                yrs, plot_energy, "Energy (M GJ)", TC["bar_blue"],
                plot_ekpi, "Energy intensity (GJ/t)", TC["line_dark"],
                title="Energy consumption & intensity",
                byt="M GJ", lyt="GJ/t", bfmt=".1f", lfmt=".1f",
            ), use_container_width=True, key=_ck("ov01"))
        with c2:
            st.plotly_chart(_dual(
                yrs, plot_co2, "CO₂ (Mt)", TC["bar_blue"],
                plot_c2kpi, "CO₂ intensity (tCO₂/ton)", TC["line_dark"],
                title="CO₂ emissions & intensity",
                byt="Mt CO₂e", lyt="tCO₂/ton", bfmt=".1f", lfmt=".2f",
            ), use_container_width=True, key=_ck("ov02"))

        # Client vs sector comparison (own company only)
        if not is_dss_user:
            client_co = st.session_state.get("user_company", "")
            if has_wide and client_co and client_co in df["Company"].values:
                st.markdown("---")
                st.markdown(f"##### {client_co} — your performance vs TIP sector")
                _c1, _c2 = st.columns(2)
                with _c1:
                    _s = _co_series(client_co, "Total energy - KPI") if has_wide and "Total energy - KPI" in df.columns else None
                    if _s is not None:
                        _cv = [float(v) if not np.isnan(float(v)) else None for v in _s.values]
                        _f = go.Figure()
                        _f.add_trace(go.Scatter(x=yrs, y=energy_kpi, name="TIP sector avg",
                            mode="lines+markers", line=dict(color=TC["line_light"], width=1.8, dash="dot"),
                            marker=_omk(TC["line_light"], 7)))
                        _f.add_trace(go.Scatter(x=yrs, y=_cv, name=client_co.split()[0],
                            mode="lines+markers+text", line=dict(color=TC["line_dark"], width=2.5),
                            marker=_omk(TC["line_dark"], 5),
                            text=[f"{v:.2f}" if v else "" for v in _cv],
                            textposition="top center", textfont=dict(size=13, color="#2a2825", family="Arial")))
                        lay = _tlayout("Energy intensity vs sector (GJ/t)", 280)
                        _f.update_layout(**lay)
                        st.plotly_chart(_f, use_container_width=True, key=_ck("ov03"))
                with _c2:
                    _s2 = _co_series(client_co, "Total CO2 - KPI") if has_wide and "Total CO2 - KPI" in df.columns else None
                    if _s2 is not None:
                        _cv2 = [float(v) if not np.isnan(float(v)) else None for v in _s2.values]
                        _f2 = go.Figure()
                        _f2.add_trace(go.Scatter(x=yrs, y=co2_kpi, name="TIP sector avg",
                            mode="lines+markers", line=dict(color=TC["line_light"], width=1.8, dash="dot"),
                            marker=_omk(TC["line_light"], 7)))
                        _f2.add_trace(go.Scatter(x=yrs, y=_cv2, name=client_co.split()[0],
                            mode="lines+markers+text", line=dict(color=TC["line_dark"], width=2.5),
                            marker=_omk(TC["line_dark"], 5),
                            text=[f"{v:.3f}" if v else "" for v in _cv2],
                            textposition="top center", textfont=dict(size=13, color="#2a2825", family="Arial")))
                        lay2 = _tlayout("CO₂ intensity vs sector (tCO₂/t)", 280)
                        _f2.update_layout(**lay2)
                        st.plotly_chart(_f2, use_container_width=True, key=_ck("ov04"))

    # helper: company overlay
    def _ov_series(col, divisor=1):
        if overlay_company and has_wide and col in df.columns:
            s = df[df["Company"]==overlay_company].set_index("Year")[col]/divisor
            return _safe(s.reindex(yrs_int), [None]*len(yrs_int))
        return None

    # ── Energy Tab ──────────────────────────────────────────────────────────────
    with tab_energy:
        st.markdown("##### Energy consumption & intensity")
        st.caption("Total energy (PJNCV) · Energy intensity (GJ/t) · Energy mix · Renewable electricity share")

        c1, c2 = st.columns(2)
        with c1:
            # Dual-axis: total energy bar + energy intensity line
            plot_e = _ov_series("Total energy", 1e6) or energy_total
            _raw_ei = _ov_series("Total energy - KPI")
            plot_ei = _raw_ei if (_raw_ei and any(v is not None for v in _raw_ei)) else energy_kpi
            st.plotly_chart(_dual(
                yrs, plot_e, "Energy consumption (M GJ)", TC["bar_blue"],
                plot_ei, "Energy intensity (GJ/t)", TC["line_dark"],
                title="Total energy consumption & intensity",
                byt="M GJ (PJNCV)", lyt="GJ/t", bfmt=".1f", lfmt=".1f",
            ), use_container_width=True, key=_ck("e01"))
        with c2:
            # Production + sites (Fig 3)
            _raw_pi = _ov_series("Production", 1e6)
            plot_pi  = _raw_pi if (_raw_pi and any(v is not None for v in _raw_pi)) else prod_total
            _p0v_raw = next((v for v in plot_pi if v is not None and v == v), 1)
            _p0v = max(_p0v_raw, 1) if _p0v_raw else 1
            plot_pidx = [v/_p0v*100 if (v is not None and v == v) else None for v in plot_pi]
            st.plotly_chart(_dual(
                yrs, plot_pidx, "Production level (% rel. to first year)", TC["bar_blue"],
                sites_total, "Number of sites", TC["line_light"],
                title="Production levels & number of sites",
                byt="Production (%)", lyt="Number of sites", bfmt=".2f", lfmt=".0f",
            ), use_container_width=True, key=_ck("e02"))

        c3, c4 = st.columns(2)
        with c3:
            # Fig 5 — Energy mix 5-category stacked 100%
            traces5 = [
                (_steam_pct,   "Purchased steam",                          TC["bar_blue2"]),
                (_renew_pct2,  "Renewable electricity (purchased+self-gen)",TC["bar_green"]),
                (_nonrw_pct2,  "Non-renewable electricity purchased",       TC["bar_sand"]),
                (_natg_pct,    "Natural gas",                              "#8FA5B5"),
                (_other_pct,   "Other (LPG, fuel oil, coal, diesel, etc.)",TC["bar_orange"]),
            ]
            st.plotly_chart(_stack100(yrs, traces5, "Energy mix (%)"), use_container_width=True, key=_ck("e03"))
        with c4:
            # Fig 6 — Electricity from renewable sources
            r_texts  = [f"{v:.1f}%" if v else "" for v in _renew_pct_v]
            nr_texts = [f"{v:.1f}%" if v else "" for v in _nonrw_pct_v]
            st.plotly_chart(_stackabs(
                yrs,
                [(_renew_pct_v, "Renewable electricity (GJ)", TC["bar_blue2"], r_texts),
                 (_nonrw_pct_v, "Non-renewable electricity (GJ)", TC["bar_sand"], nr_texts)],
                "Electricity from renewable sources (%)",
            ), use_container_width=True, key=_ck("e04"))

        # Energy intensity trend vs sector — only show when a company is selected
        if has_wide and overlay_company:
            st.markdown("---")
            st.markdown(f"##### {overlay_company} — energy intensity trend vs sector")

            f_co = go.Figure()

            if overlay_company:
                # ── Selected company: show company line (bold) + sector avg (dotted) ──
                _s_co = _co_series(overlay_company, "Total energy - KPI")
                _co_vals = ([float(v) if (v == v and v is not None) else None
                              for v in _s_co.reindex(yrs_int).values]
                             if _s_co is not None else [None]*len(yrs))

                # Sector avg (dotted, behind)
                f_co.add_trace(go.Scatter(
                    x=yrs, y=energy_kpi, name="TIP Sector Avg",
                    mode="lines+markers",
                    line=dict(color=TC["line_light"], width=1.6, dash="dot"),
                    marker=_omk(TC["line_light"], 6),
                ))
                # Company line (bold, with value labels)
                _alt = ["top center" if i % 2 == 0 else "bottom center"
                        for i in range(len(yrs))]
                f_co.add_trace(go.Scatter(
                    x=yrs, y=_co_vals, name=overlay_company.split()[0],
                    mode="lines+markers+text",
                    line=dict(color=TC["line_dark"], width=2.5),
                    marker=_omk(TC["line_dark"], 5),
                    text=[f"{v:.1f}" if v is not None else "" for v in _co_vals],
                    textposition=_alt,
                    textfont=dict(size=12, color="#2a2825", family="Arial"),
                ))
                _e_title = (f"Energy intensity (GJ/t) — "
                            f"{overlay_company.split()[0]} vs sector avg")
            else:
                # ── All Companies: one light line per company + sector avg ──────────
                _COMPANY_PALETTE = [
                    "#B8CDD9","#7BAF74","#C8B49A","#E0935A","#9FB8C5",
                    "#2D4A5A","#D4C5A9","#8FA5B5","#465c66","#cab6a5",
                ]
                for _ci, _co in enumerate(companies):
                    _s = _co_series(_co, "Total energy - KPI")
                    if _s is None: continue
                    _v = [float(x) if (x == x and x is not None) else None
                          for x in _s.reindex(yrs_int).values]
                    f_co.add_trace(go.Scatter(
                        x=yrs, y=_v, name=_co.split()[0],
                        mode="lines+markers",
                        line=dict(color=_COMPANY_PALETTE[_ci % len(_COMPANY_PALETTE)],
                                  width=1.4),
                        marker=_omk(_COMPANY_PALETTE[_ci % len(_COMPANY_PALETTE)], 5),
                        opacity=0.7,
                    ))
                # Sector avg on top
                f_co.add_trace(go.Scatter(
                    x=yrs, y=energy_kpi, name="TIP Sector Avg",
                    mode="lines+markers",
                    line=dict(color=TC["line_dark"], width=2.4, dash="dot"),
                    marker=_omk(TC["line_dark"], 7),
                ))
                _e_title = "Energy intensity (GJ/t) — all TIP companies"

            lay_co = _tlayout(_e_title, 320)
            lay_co["legend"] = dict(orientation="h", x=0.5, xanchor="center",
                                    y=-0.22, font=dict(size=12, color="#6f7882"),
                                    bgcolor="rgba(0,0,0,0)")
            f_co.update_layout(**lay_co)
            st.plotly_chart(f_co, use_container_width=True, key=_ck("e05"))

    # ── CO₂ Tab ─────────────────────────────────────────────────────────────────
    with tab_co2:
        st.markdown("##### CO₂ emissions & decarbonisation")
        st.caption("Total CO₂ (Mt CO₂e) · CO₂ intensity (tCO₂/t) · Scope 1 vs Scope 2 · Science-based targets")

        c1, c2 = st.columns(2)
        with c1:
            # Fig 7 — CO₂ dual-axis
            plot_c = _ov_series("Total CO2", 1e6) or co2_total
            plot_ck = _ov_series("Total CO2 - KPI") or co2_kpi
            st.plotly_chart(_dual(
                yrs, plot_c, "CO₂ emissions (Mt CO₂e)", TC["bar_blue"],
                plot_ck, "CO₂ intensity (tCO₂/ton)", TC["line_dark"],
                title="Total CO₂ emissions & intensity",
                byt="Mt CO₂e", lyt="tCO₂/ton", bfmt=".1f", lfmt=".2f",
            ), use_container_width=True, key=_ck("c01"))
        with c2:
            # Scope 1 vs Scope 2 stacked bar
            plot_s1 = _ov_series("Total CO2 - Scope 1", 1e6) or scope1_total
            plot_s2 = _ov_series("Total CO2 - Scope 2", 1e6) or scope2_total
            f_sc = go.Figure()
            f_sc.add_trace(go.Bar(x=yrs, y=plot_s1, name="Scope 1 — direct emissions",
                marker_color=TC["bar_blue"], marker_line_width=0,
                text=[f"{v:.2f}" if v else "" for v in plot_s1],
                textposition="inside", insidetextanchor="middle", textfont=dict(size=13, color="#2a2825", family="Arial")))
            f_sc.add_trace(go.Bar(x=yrs, y=plot_s2, name="Scope 2 — indirect emissions",
                marker_color=TC["bar_blue2"], marker_line_width=0,
                text=[f"{v:.2f}" if v else "" for v in plot_s2],
                textposition="inside", insidetextanchor="middle", textfont=dict(size=13, color="white", family="Arial")))
            lay_sc = _tlayout("CO₂ Scope 1 vs Scope 2 (Mt CO₂e)", 430)
            lay_sc["barmode"] = "stack"
            lay_sc["yaxis"]["title"] = dict(text="Mt CO₂e", font=dict(size=11))
            f_sc.update_layout(**lay_sc)
            st.plotly_chart(f_sc, use_container_width=True, key=_ck("c02"))



        # CO₂ intensity trend vs sector — only show when a company is selected
        if has_wide and overlay_company:
            st.markdown("---")
            st.markdown(f"##### {overlay_company} — CO₂ intensity trend vs sector")

            f_cr = go.Figure()

            if overlay_company:
                # Selected company: company line (bold) + sector avg (dotted)
                _s_co2 = _co_series(overlay_company, "Total CO2 - KPI")
                _co2_vals = ([float(v) if (v == v and v is not None) else None
                               for v in _s_co2.reindex(yrs_int).values]
                              if _s_co2 is not None else [None]*len(yrs))
                f_cr.add_trace(go.Scatter(
                    x=yrs, y=co2_kpi, name="TIP Sector Avg",
                    mode="lines+markers",
                    line=dict(color=TC["line_light"], width=1.6, dash="dot"),
                    marker=_omk(TC["line_light"], 6),
                ))
                _alt2 = ["top center" if i % 2 == 0 else "bottom center"
                         for i in range(len(yrs))]
                f_cr.add_trace(go.Scatter(
                    x=yrs, y=_co2_vals, name=overlay_company.split()[0],
                    mode="lines+markers+text",
                    line=dict(color=TC["line_dark"], width=2.5),
                    marker=_omk(TC["line_dark"], 5),
                    text=[f"{v:.3f}" if v is not None else "" for v in _co2_vals],
                    textposition=_alt2,
                    textfont=dict(size=12, color="#2a2825", family="Arial"),
                ))
                _c_title = (f"CO₂ intensity (tCO₂/t) — "
                            f"{overlay_company.split()[0]} vs sector avg")

            lay_cr = _tlayout(_c_title, 320)
            lay_cr["legend"] = dict(orientation="h", x=0.5, xanchor="center",
                                    y=-0.22, font=dict(size=12, color="#6f7882"),
                                    bgcolor="rgba(0,0,0,0)")
            f_cr.update_layout(**lay_cr)
            st.plotly_chart(f_cr, use_container_width=True, key=_ck("c04"))

    # ── Water Tab ───────────────────────────────────────────────────────────────
    with tab_p3:
        st.markdown("##### Water withdrawals & intensity")
        st.caption("Total water withdrawals (M m³) · Water intensity (m³/metric t of production)")

        plot_w  = _ov_series("Water intake", 1e6) or water_total
        plot_wk = _ov_series("Water intake - KPI") or water_kpi_v

        c1, c2 = st.columns(2)
        with c1:
            st.plotly_chart(_dual(
                yrs, plot_w, "Water withdrawals (M m³)", TC["bar_beige"],
                plot_wk, "Water intensity (m³/t)", TC["line_dark"],
                title="Water withdrawals & intensity",
                byt="Million m³", lyt="m³/t", bfmt=".1f", lfmt=".1f",
            ), use_container_width=True, key=_ck("w01"))
        with c2:
            if is_dss_user and overlay_company and has_wide and companies:
                # Show selected company vs sector avg when a company is chosen
                f_wt = go.Figure()
                for i, co in enumerate(companies):
                    s = _co_series(co, "Water intake - KPI")
                    if s is not None:
                        # reindex to exactly yrs_int to avoid float x interpolation
                        vals_s = s.reindex(yrs_int)
                        vals = [float(v) if (v == v and v is not None) else None
                                for v in vals_s.values]
                        is_selected = (co == overlay_company)
                        f_wt.add_trace(go.Scatter(
                            x=yrs, y=vals, name=co.split()[0],
                            mode="lines+markers",
                            line=dict(color=PALETTE_10[i%10],
                                      width=2.5 if is_selected else 1.2,
                                      dash="solid" if is_selected else "solid"),
                            marker=dict(size=6 if is_selected else 3),
                            opacity=1.0 if is_selected else 0.45,
                        ))
                f_wt.add_trace(go.Scatter(x=yrs, y=water_kpi_v, name="Sector avg",
                    mode="lines", line=dict(color="#000", width=2, dash="dot")))
                lay_wt = _tlayout("Water intensity by company vs sector avg (m³/t)", 430, r=12)
                lay_wt["xaxis"]["type"] = "category"
                f_wt.update_layout(**lay_wt)
                st.plotly_chart(f_wt, use_container_width=True, key=_ck("w02"))
            else:
                # No company selected: show sector trend only
                f_wt2 = go.Figure()
                f_wt2.add_trace(go.Scatter(x=yrs, y=water_kpi_v, name="Sector avg water intensity",
                    mode="lines+text",
                    line=dict(color=TC["line_dark"], width=2.5),
                    text=[f"{v:.1f}" if v else "" for v in water_kpi_v],
                    textposition="top center", textfont=dict(size=12, color="#2a2825", family="Arial"),
                ))
                lay_wt2 = _tlayout("Sector avg water intensity (m³/t)", 430, r=12)
                lay_wt2["xaxis"]["type"] = "category"
                lay_wt2["showlegend"] = False
                f_wt2.update_layout(**lay_wt2)
                st.plotly_chart(f_wt2, use_container_width=True, key=_ck("w02"))

    # ── Waste & Environment Tab ──────────────────────────────────────────────────
    with tab_p4:
        st.markdown("##### Waste management & ISO 14001 certification")
        st.caption("Total waste generated · Waste recovery vs disposal · ISO 14001 site certification")

        c1, c2 = st.columns(2)
        with c1:
            # Waste total (bar) + intensity (line)
            st.plotly_chart(_dual(
                yrs, [wt/1e6 for wt in waste_total_v], "Waste generated (Mt)", TC["bar_beige"],
                waste_intensity, "Waste intensity (kg/t)", TC["line_dark"],
                title="Total waste generated & intensity",
                byt="Mt", lyt="kg/t", bfmt=".2f", lfmt=".1f",
            ), use_container_width=True, key=_ck("wst01"))
        with c2:
            # Waste recovery vs disposal stacked 100% — percentages inside bars
            st.plotly_chart(_stack100(
                yrs,
                [(waste_recov_pct, "Sent for recovery (%)",  TC["bar_beige"]),
                 (waste_elim_pct,  "Sent for disposal (%)",  TC["bar_blue2"])],
                "Waste sent for recovery vs disposal (%)",
            ), use_container_width=True, key=_ck("wst02"))

        # ── 5th chart: grouped bar — recovery vs disposal absolute tonnage ──────
        _wt_xi   = list(range(len(yrs)))
        _dis_abs = [int(max(t - r, 0)) if (t and r) else 0
                    for t, r in zip(waste_total_v, waste_recov_a)]
        fig_wabs = go.Figure()
        fig_wabs.add_trace(go.Bar(
            x=_wt_xi, y=waste_recov_a, name="Sent for recovery (t)",
            marker_color="#7BAF74", marker_line_width=0, width=0.38,
            customdata=[str(y) for y in yrs],
            text=[f"{int(v):,}" if v else "" for v in waste_recov_a],
            textposition="outside",
            textfont=dict(size=11, color="#2a2825", family="Arial"),
            hovertemplate="<b>%{customdata}</b><br>Recovery: %{y:,.0f} t<extra></extra>",
        ))
        fig_wabs.add_trace(go.Bar(
            x=_wt_xi, y=_dis_abs, name="Sent for disposal (t)",
            marker_color="#2D4A5A", marker_line_width=0, width=0.38,
            customdata=[str(y) for y in yrs],
            text=[f"{int(v):,}" if v else "" for v in _dis_abs],
            textposition="outside",
            textfont=dict(size=11, color="#2a2825", family="Arial"),
            hovertemplate="<b>%{customdata}</b><br>Disposal: %{y:,.0f} t<extra></extra>",
        ))
        fig_wabs.update_layout(
            barmode="group",
            plot_bgcolor="#f5f4f2", paper_bgcolor="#f5f4f2",
            height=370,
            bargap=0.20, bargroupgap=0.06,
            margin=dict(l=60, r=50, t=50, b=55),
            title=dict(text="<b>Waste sent for recovery vs disposal (absolute tonnes)</b>",
                       font=dict(size=14, color="#2a2825"), x=0),
            xaxis=dict(tickmode="array", tickvals=_wt_xi, ticktext=[str(y) for y in yrs],
                       showgrid=False, showline=True, linecolor="#9aa1a9", linewidth=1.2,
                       tickfont=dict(size=12, color="#6f7882"), zeroline=False),
            yaxis=dict(title=dict(text="Tonnes", font=dict(size=12, color="#6f7882")),
                       showgrid=True, gridcolor="#e6eaed", showline=True, linecolor="#9aa1a9",
                       tickfont=dict(size=12, color="#6f7882"), zeroline=False),
            legend=dict(orientation="h", x=0.5, xanchor="center", y=-0.22,
                        font=dict(size=12, color="#6f7882"), bgcolor="rgba(0,0,0,0)"),
            hovermode="x unified",
        )
        st.plotly_chart(fig_wabs, use_container_width=True, key=_ck("wabs"))

        c3, c4 = st.columns(2)
        with c3:
            # ISO 14001 — dual line: % certified + site count
            st.plotly_chart(_dline(
                yrs, iso_cert, "ISO 14001 certified sites (%)", TC["line_dark"],
                sites_total,   "Number of sites",               TC["line_light"],
                title="ISO 14001 certification & site count",
                yt="% certified sites", s2yt="Number of sites",
                right_y=True, s1f=".0f", s2f=".0f", h=330,
            ), use_container_width=True, key=_ck("wst03"))
        with c4:
            # Waste recovery trend — multi-year progress lines per company
            f_wr = go.Figure()
            if has_wide and companies:
                for i, co in enumerate(companies):
                    s = _co_series(co, "Waste_Recovery_Rate_%")
                    if s is None: s = _co_series(co, "Recovery Rate")
                    if s is not None:
                        vals = [float(v) if (v == v and v is not None) else None
                                for v in s.reindex(yrs_int).values]
                        # Highlight selected company if one is chosen
                        is_sel = (overlay_company and co == overlay_company)
                        f_wr.add_trace(go.Scatter(
                            x=yrs, y=vals, name=co.split()[0],
                            mode="lines+markers",
                            line=dict(color=PALETTE_10[i%10],
                                      width=2.5 if is_sel else 1.2),
                            marker=dict(size=6 if is_sel else 3),
                            opacity=1.0 if (is_sel or not overlay_company) else 0.4,
                            hovertemplate=f"{co.split()[0]}: %{{y:.1f}}%<extra></extra>",
                        ))
            # Sector average
            f_wr.add_trace(go.Scatter(
                x=yrs, y=waste_recov, name="Sector avg",
                mode="lines", line=dict(color="#000", width=2, dash="dot"),
            ))
            f_wr.add_hline(y=80, line_dash="dot", line_color=TC["line_dark"],
                annotation_text="80% target", annotation_font_size=9)
            lay_wr = _tlayout("Waste recovery rate — company progress (%)", 330, r=12)
            lay_wr["yaxis"]["ticksuffix"] = "%"
            lay_wr["yaxis"]["range"] = [0, 105]
            f_wr.update_layout(**lay_wr)
            st.plotly_chart(f_wr, use_container_width=True, key=_ck("wst04"))

    # ── People & Governance Tab (Analysis) — sector aggregate charts ──────────
    with tab_people:
        st.markdown("#### People & Governance")
        st.caption("Sector aggregate or selected company trend · read from live master data")

        # ── Read live columns from master CSV (promoted from supplementary) ──
        def _pg_live(col):
            """Sector mean or company series for a master CSV column."""
            if state.CONSOLIDATED_DF.empty or col not in state.CONSOLIDATED_DF.columns:
                return [None] * len(yrs_int)
            out_vals = []
            for y in yrs_int:
                sub = state.CONSOLIDATED_DF[state.CONSOLIDATED_DF["Year"] == y]
                if overlay_company and overlay_company != "All Companies":
                    sub = sub[sub["Company"] == overlay_company]
                if sub.empty or sub[col].isna().all():
                    out_vals.append(None)
                else:
                    out_vals.append(round(float(sub[col].mean()), 2))
            return out_vals

        _hs_ext_live = _pg_live("HS External Audit %")
        _hs_int_live = _pg_live("HS Internal Audit %")
        _wb_live     = _pg_live("Female Board %")
        _wt_live     = _pg_live("Female Employees %")
        _sbt_val_v   = _pg_live("SBT Validated")
        _sbt_com_v   = _pg_live("SBT Committed")
        _sbt_tot_v   = _pg_live("SBT Total")

        _has_hs  = any(v and v > 0 for v in _hs_ext_live)
        _has_div = any(v and v > 0 for v in _wb_live)
        _has_sbt = any(v and v > 0 for v in _sbt_tot_v)

        c1, c2 = st.columns(2)
        with c1:
            if _has_hs:
                st.plotly_chart(_dline(
                    yrs, _hs_ext_live, "External H&S audit (%)", TC["line_dark"],
                    _hs_int_live,      "Internal H&S audit (%)", TC["line_light"],
                    title="H&S system audit coverage (%)", yt="Sites audited (%)",
                    h=430, s1f=".1f", s2f=".1f",
                ), use_container_width=True, key=_ck("pp01"))
            else:
                st.info("H&S data not yet submitted (Submit Data → Section 7).", icon="📊")

        with c2:
            if _has_div:
                st.plotly_chart(_dline(
                    yrs, _wb_live, "Women on Board (%)", TC["line_dark"],
                    _wt_live,      "Women in workforce (%)", TC["line_light"],
                    title="Women's representation (%)", yt="Women (%)",
                    h=430, s1f=".1f", s2f=".1f",
                ), use_container_width=True, key=_ck("pp02"))
            else:
                st.info("Diversity data not yet submitted (Submit Data → Section 8).", icon="📊")

        if _has_sbt:
            st.markdown("---")
            _sbt_v_c = [v or 0 for v in _sbt_val_v]
            _sbt_c_c = [v or 0 for v in _sbt_com_v]
            st.plotly_chart(_stack100(
                yrs,
                [(_sbt_v_c, "Validated",  TC["bar_green"]),
                 (_sbt_c_c, "Committed",  TC["bar_blue"])],
                title="Science-Based Targets — Validated vs Committed",
            ), use_container_width=True, key=_ck("pp03"))
        else:
            st.markdown("---")
            st.info("Science-Based Target data not yet submitted (Submit Data → Section 9).", icon="📊")

    # dummy placeholder to avoid the incorrectly-injected table below being executed
    if False:
        pass   # end of page_analysis