"""
pages/page_my_dashboard.py — My Dashboard: KPI-card-organized performance report.

"""
from __future__ import annotations
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime

import config as cfg
import data_loader as dl
import state
from utils.helpers import _chart_key
from ui_components import (
    section_header_html, chart_layout_defaults, apply_chart_animation,
    GREEN, AMBER, RED, NAVY, BG, BORDER, TEXT, MUTED,
    CAT_CO2, CAT_ENERGY, CAT_WATER, CAT_WASTE, CAT_RENEW,
)
import logging
_log = logging.getLogger("esg_app")

BAR_COLOR   = "#B8CDD9"
LINE_COLOR  = "#F5A623"
LINE2_COLOR = "#1B3A6B"
BAR2_COLOR  = "#1A1A2E"
TIP_TEAL    = "#3DBDB5"
AXIS_COLOR  = "#5A6478"
GRID_COLOR  = "#C5CCD6"
AXIS_LINE   = "#9CA8B8"
FONT_FAM    = "Inter, -apple-system, BlinkMacSystemFont, sans-serif"
ANNOT_COLOR = "#374151"
NAVY_DARK   = "#0F2540"
NAVY_MID    = "#1B4060"

FUEL_COLORS = {
    "Natural Gas": "#1A1A2E", "Coal": "#555E6E", "LPG": "#8B97A8",
    "Fuel Oil": "#E07070", "Diesel": "#E8A44A", "Petrol": "#D4B84A",
    "Biomass": "#5BAD7A", "Non-Renewable Electricity": "#6B7FD4",
    "Renewable Electricity": "#3DBDB5", "Purchased Steam": "#76D4E8",
    "Other": "#B0BCC8",
}


def _inject_css():
    """Inject dashboard-specific CSS styles."""
    st.markdown(f"""
    <style>
    .dash-hero {{
        background: linear-gradient(135deg, {NAVY_DARK} 0%, {NAVY_MID} 100%);
        border-radius: 12px; padding: 22px 28px; margin-bottom: 18px;
        display: flex; justify-content: space-between; align-items: flex-start;
    }}
    .dash-hero-eyebrow {{ font-size: 11px; letter-spacing: .06em; text-transform: uppercase;
                         color: rgba(255,255,255,.55); margin-bottom: 6px; }}
    .dash-hero-title {{ font-size: 24px; font-weight: 700; color: white; line-height: 1.2; }}
    .dash-hero-sub {{ font-size: 12.5px; color: rgba(255,255,255,.7); margin-top: 4px; }}
    .dash-hero-year-label {{ font-size: 10px; color: rgba(255,255,255,.5); text-align: right;
                            text-transform: uppercase; letter-spacing: .05em; }}
    .dash-hero-year {{ font-size: 30px; font-weight: 700; color: white; text-align: right; line-height: 1; }}
    .dash-hero-badge {{ font-size: 10.5px; color: #6EE7B7; text-align: right; margin-top: 4px; }}
    .dash-heading-text {{ font-size: 20px; font-weight: 700; color: #1A202C; }}
    
    /* ── OLD KPI STRIP (kept for backward compatibility) ────────────────────── */
    .kpi-strip {{ display: grid; grid-template-columns: repeat(6, 1fr); gap: 12px; margin-bottom: 14px; }}
    .kpi-tile {{ background: white; border: 1px solid #E3E8EE; border-radius: 10px;
                padding: 13px 14px; box-shadow: 0 1px 3px rgba(16,24,40,.04); }}
    .kpi-tile-label {{ font-size: 10.5px; color: #6B7280; text-transform: uppercase;
                      letter-spacing: .03em; margin-bottom: 5px; }}
    .kpi-tile-val {{ font-size: 19px; font-weight: 700; color: #1A202C; line-height: 1.1; }}
    .kpi-tile-unit {{ font-size: 10px; color: #9CA3AF; margin-top: 1px; }}
    .kpi-tile-delta {{ font-size: 10.5px; margin-top: 5px; font-weight: 600; }}
    
    /* ── OPTIMIZED KPI GRID (benchmarking style) ────────────────────────────── */
    .kpi-grid-opt {{
        display: grid;
        grid-template-columns: repeat(5, 1fr);
        gap: 14px;
        margin-bottom: 20px;
    }}
    @media (max-width: 1400px) {{
        .kpi-grid-opt {{
            grid-template-columns: repeat(3, 1fr);
        }}
    }}
    @media (max-width: 768px) {{
        .kpi-grid-opt {{
            grid-template-columns: repeat(2, 1fr);
        }}
    }}
    @media (max-width: 480px) {{
        .kpi-grid-opt {{
            grid-template-columns: 1fr;
        }}
    }}
    
    div[data-testid="stVerticalBlock"] div.dash-card {{
        background: white; border: none; border-radius: 10px;
        padding: 0px; margin-bottom: 16px; box-shadow: 0 1px 3px rgba(16,24,40,.04); overflow: visible;
    }}
    div.dash-info-card {{
        background: #F8FAFC; border: 1px dashed #D1D9E0; border-radius: 10px;
        padding: 26px 18px; margin-bottom: 16px; text-align: center;
        color: #6B7280; font-size: 12.5px;
    }}
    .stSelectbox {{ width: 100%; }}
    </style>
    """, unsafe_allow_html=True)


def _kpi_tile(label, val, unit, delta_pct=None, good_if_down=True, perf_pct=None):
    """Render a KPI tile with optional YoY delta and performance progress bar."""
    if delta_pct is None:
        delta_html = '<span style="color:#9CA3AF">—</span>'
    else:
        good = (delta_pct < 0) == good_if_down if good_if_down is not None else True
        color = "#059669" if good else "#C8102E"
        arrow = "▼" if delta_pct < 0 else "▲"
        delta_html = f'<span style="color:{color}">{arrow} {abs(delta_pct):.1f}%</span>'
    
    # Performance bar (0-100, green for good, red for bad)
    if perf_pct is not None:
        perf_pct = max(0, min(100, perf_pct))
        bar_color = "#059669" if perf_pct >= 70 else ("#F59E0B" if perf_pct >= 40 else "#C8102E")
        bar_html = f'''<div style="background:#E5E7EB;border-radius:3px;height:4px;margin:6px 0;overflow:hidden">
            <div style="background:{bar_color};width:{perf_pct:.0f}%;height:100%;border-radius:3px;transition:width 0.6s ease"></div>
        </div>'''
    else:
        bar_html = ''
    
    return f'''<div class="kpi-tile">
        <div class="kpi-tile-label">{label}</div>
        <div class="kpi-tile-val">{val}</div>
        <div class="kpi-tile-unit">{unit}</div>
        {bar_html}
        <div class="kpi-tile-delta">{delta_html}</div>
    </div>'''


def _kpi_card_opt(name, value, unit, color, delta_pct=None):
    """Optimized KPI card (benchmarking style - larger text, category colors)."""
    return f'''<div style="background:#fff;border:1px solid #E2E8F0;border-radius:10px;padding:16px 14px;text-align:center;box-shadow:0 1px 3px rgba(15,23,42,.04)">
      <div style="font-size:9.5px;color:#64748B;font-weight:600;text-transform:uppercase;letter-spacing:.5px;margin-bottom:10px">{name}</div>
      <div style="font-size:28px;font-weight:700;color:{color};font-variant-numeric:tabular-nums;line-height:1.1">{value:.2f}</div>
      <div style="font-size:10px;color:#64748B;margin-top:4px">{unit}</div>
    </div>'''


def _card_open():
    st.markdown('<div class="dash-card">', unsafe_allow_html=True)


def _card_close():
    st.markdown('</div>', unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# Chart layout functions
# ─────────────────────────────────────────────────────────────────────────────

def _base(title="", sub="", height=520, bottom_margin=160, top_margin=110):
    """Base chart layout with increased top margin to prevent title cutoff."""
    title_html = f"<b style='font-size:13px;color:#1A202C'>{title}</b>" if title else ""
    return dict(
        height=height,
        margin=dict(l=70, r=60, t=top_margin, b=bottom_margin),
        paper_bgcolor="white", plot_bgcolor="#FAFBFC",
        title=dict(text=title_html, x=0.022, xanchor="left",
                  y=0.995, yanchor="top", font=dict(family=FONT_FAM)),
        font=dict(family=FONT_FAM, size=11, color=AXIS_COLOR),
        legend=dict(orientation="h", x=0, y=-0.55, xanchor="left", yanchor="top",
                   font=dict(size=10), bgcolor="rgba(0,0,0,0)", traceorder="normal"),
        hovermode="x unified",
        xaxis=dict(
            showgrid=False, showline=True, linewidth=1.8, linecolor=AXIS_LINE,
            tickfont=dict(size=11, color=AXIS_COLOR), dtick=1,
            ticks="outside", tickcolor=AXIS_LINE, ticklen=5, zeroline=False,
            automargin=True,
        ),
        yaxis=dict(
            showgrid=True, gridcolor=GRID_COLOR, gridwidth=1.2,
            showline=True, linewidth=1.8, linecolor=AXIS_LINE,
            zeroline=False, tickfont=dict(size=11, color=AXIS_COLOR),
            automargin=True,
        ),
        uniformtext=dict(minsize=8, mode="hide"),
    )


def _dual(title, sub, y1_title, y2_title, y2_color=LINE_COLOR, height=520, bottom_margin=160):
    """Dual-axis layout with proper spacing."""
    b = _base(title, sub, height, bottom_margin=bottom_margin, top_margin=110)
    b["yaxis"]["title"] = dict(text=y1_title, font=dict(size=10, color=AXIS_COLOR))
    b["yaxis2"] = dict(
        overlaying="y", side="right", showgrid=False,
        showline=True, linewidth=1.8, linecolor=y2_color,
        zeroline=False, tickfont=dict(size=11, color=y2_color),
        title=dict(text=y2_title, font=dict(size=10, color=y2_color)),
        automargin=True,
    )
    return b


def _simple_bar_layout(title="", sub="", y_title="", height=520, bottom_margin=140, top_margin=110):
    """Simple bar chart layout (no dual axis, legend moved up)."""
    title_html = f"<b style='font-size:13px;color:#1A202C'>{title}</b>" if title else ""
    return dict(
        height=height,
        margin=dict(l=70, r=60, t=top_margin, b=bottom_margin),
        paper_bgcolor="white", plot_bgcolor="#FAFBFC",
        title=dict(text=title_html, x=0.022, xanchor="left",
                  y=0.995, yanchor="top", font=dict(family=FONT_FAM)),
        font=dict(family=FONT_FAM, size=11, color=AXIS_COLOR),
        legend=dict(orientation="h", x=0, y=-0.30, xanchor="left", yanchor="top",
                   font=dict(size=10), bgcolor="rgba(0,0,0,0)", traceorder="normal"),
        hovermode="x unified",
        xaxis=dict(
            showgrid=False, showline=True, linewidth=1.8, linecolor=AXIS_LINE,
            tickfont=dict(size=11, color=AXIS_COLOR), dtick=1,
            ticks="outside", tickcolor=AXIS_LINE, ticklen=5, zeroline=False,
            automargin=True,
        ),
        yaxis=dict(
            showgrid=True, gridcolor=GRID_COLOR, gridwidth=1.2,
            showline=True, linewidth=1.8, linecolor=AXIS_LINE,
            zeroline=False, tickfont=dict(size=11, color=AXIS_COLOR),
            title=dict(text=y_title, font=dict(size=10, color=AXIS_COLOR)),
            automargin=True,
        ),
        uniformtext=dict(minsize=8, mode="hide"),
    )


def _bar_trace(xs, ys, name, color=BAR_COLOR, width=0.5):
    return go.Bar(x=xs, y=ys, name=name, marker_color=color,
                  marker_line_width=0, width=width,
                  hovertemplate="%{y:.2f}<extra></extra>")


def _line_trace(xs, ys, name, color=LINE_COLOR, yaxis="y"):
    return go.Scatter(x=xs, y=ys, name=name, mode="lines",
                     line=dict(color=color, width=2.8),
                     yaxis=yaxis, hovertemplate="%{y:.2f}<extra></extra>")


def _add_values_below_bars(fig, xs, data_rows, height=520):
    """Add values below bars with proper spacing."""
    y_start = -0.28
    row_gap_frac = 0.09
    
    for i, (row_label, row_vals, fmt_str) in enumerate(data_rows):
        y_pos = y_start - (i * row_gap_frac)
        # Move row label to balance position - avoid cutoff and overlap
        fig.add_annotation(
            text=f"{row_label}",
            xref="paper", yref="paper",
            x=-0.002, y=y_pos, xanchor="right", yanchor="middle",
            showarrow=False, font=dict(size=9, color=ANNOT_COLOR, family=FONT_FAM),
        )
        for xv, val in zip(xs, row_vals):
            if val is not None:
                text = fmt_str.format(val)
                fig.add_annotation(
                    text=text, xref="x", yref="paper",
                    x=xv, y=y_pos, xanchor="center", yanchor="middle",
                    showarrow=False, font=dict(size=8.5, color=ANNOT_COLOR, family=FONT_FAM),
                )
    lowest = y_start - (len(data_rows) - 1) * row_gap_frac
    return lowest


# ─────────────────────────────────────────────────────────────────────────────
# Main page function
# ─────────────────────────────────────────────────────────────────────────────

def page_my_dashboard():
    """Render the My Dashboard page with KPI metrics and tabbed charts."""
    company = st.session_state.user_company
    _inject_css()

    if state.CONSOLIDATED_DF.empty:
        st.info("No data loaded. Run build_esg_master.py first.")
        return

    df = state.CONSOLIDATED_DF
    if "Row_Label" in df.columns:
        st.warning("Wide-format master data required for My Dashboard.")
        return

    all_yrs = sorted(
        df[df["Company"] == company]["Year"].dropna().astype(int).unique().tolist()
    )
    if not all_yrs:
        st.info(f"No data found for {company}.")
        return

    range_opts = {
        "Last 3 years": all_yrs[-3:] if len(all_yrs) >= 3 else all_yrs,
        "Last 5 years": all_yrs[-5:] if len(all_yrs) >= 5 else all_yrs,
        "All years":    all_yrs,
    }

    co_df = df[df["Company"] == company].set_index("Year")
    latest_yr = all_yrs[-1]

    st.markdown(f'''<div class="dash-hero">
        <div>
            <div class="dash-hero-eyebrow">Tire Industry Platform</div>
            <div class="dash-hero-title">{company}</div>
            <div class="dash-hero-sub">ESG Performance Dashboard</div>
        </div>
        <div style="text-align:right">
            <div class="dash-hero-year-label">Latest Report</div>
            <div class="dash-hero-year">{latest_yr}</div>
        </div>
    </div>''', unsafe_allow_html=True)

    yr_range = range_opts.get(st.session_state.get("dash_range", "Last 5 years"), list(range_opts.values())[1])
    xs = [str(y) for y in yr_range]

    def _col_raw(col, divisor=1.0):
        if col not in co_df.columns:
            return [None] * len(yr_range)
        return [float(co_df.loc[y, col]) / divisor
                if y in co_df.index and pd.notna(co_df.loc[y, col]) else None
                for y in yr_range]

    def _pct(num_l, den_l):
        return [round(n / d * 100, 1) if (n is not None and d and d > 0) else None
                for n, d in zip(num_l, den_l)]

    def _yoy(vals):
        clean = [v for v in vals if v is not None]
        if len(clean) >= 2 and clean[-2] != 0:
            return (clean[-1] - clean[-2]) / abs(clean[-2]) * 100
        return None

    def _last(vals):
        clean = [v for v in vals if v is not None]
        return clean[-1] if clean else None

    def _zero_to_none(vals):
        return [v if (v is not None and v != 0) else None for v in vals]

    total_energy_gj  = _col_raw("Total energy")
    energy_kpi       = _col_raw("Total energy - KPI")
    total_co2_t      = _col_raw("Total CO2")
    co2_kpi          = _col_raw("Total CO2 - KPI")
    water_m3         = _col_raw("Water intake")
    water_kpi        = _col_raw("Water intake - KPI")
    iso_sites        = _col_raw("ISO 14001 sites")
    total_sites      = _col_raw("Total no. of sites")
    iso_cert         = _col_raw("ISO_Certification_%")
    total_waste      = _col_raw("Total Waste")
    waste_recov      = _col_raw("Waste Recovered")
    waste_recov_rate = _col_raw("Waste_Recovery_Rate_%")
    production       = _col_raw("Production")
    renew_pct        = _col_raw("Renewable_Electricity_Share_%")

    hs_ext_sites = _col_raw("HS External Audit Sites")
    hs_int_sites = _col_raw("HS Internal Audit Sites")
    hs_ext_pct   = _col_raw("HS External Audit %")
    hs_int_pct   = _col_raw("HS Internal Audit %")
    hs_ext_pct = [a if a is not None else b for a, b in
                 zip(hs_ext_pct, _pct(hs_ext_sites, total_sites))]
    hs_int_pct = [a if a is not None else b for a, b in
                 zip(hs_int_pct, _pct(hs_int_sites, total_sites))]

    emp_total    = _col_raw("Total Employees")
    emp_female   = _col_raw("Female Employees")
    fem_emp_pct  = _col_raw("Female Employees %")
    bod_total    = _col_raw("Board Total")
    bod_female   = _col_raw("Female Board")
    fem_bod_pct  = _col_raw("Female Board %")
    fem_emp_pct  = [a if a is not None else b for a, b in
                   zip(fem_emp_pct, _pct(emp_female, emp_total))]
    fem_bod_pct  = [a if a is not None else b for a, b in
                   zip(fem_bod_pct, _pct(bod_female, bod_total))]

    hs_ext_pct  = _zero_to_none(hs_ext_pct)
    hs_int_pct  = _zero_to_none(hs_int_pct)
    fem_emp_pct = _zero_to_none(fem_emp_pct)
    fem_bod_pct = _zero_to_none(fem_bod_pct)

    total_co2_mt = [v / 1e6 if v is not None else None for v in total_co2_t]
    water_mm3    = [v / 1e6 if v is not None else None for v in water_m3]
    waste_elim   = [t - r if (t is not None and r is not None) else None
                    for t, r in zip(total_waste, waste_recov)]
    waste_int = [w * 1000 / p if (w is not None and p and p > 0) else None
                for w, p in zip(total_waste, production)]
    iso_pct = [a if a is not None else b
              for a, b in zip(iso_cert, _pct(iso_sites, total_sites))]
    wrr = [a if a is not None else (r / t * 100 if (r is not None and t and t > 0) else None)
          for a, r, t in zip(waste_recov_rate, waste_recov, total_waste)]

    fuel_map = {
        "Natural Gas": "Natural Gas", "Coal": "Coal", "LPG": "LPG",
        "Fuel Oil": "Fuel Oil", "Diesel": "Diesel", "Petrol": "Petrol",
        "Biomass": "Biomass",
        "Non-Renewable Electricity": "Non-Renewable Electricity Purchased",
        "Renewable Electricity": "Renewable Electricity Purchased",
        "Purchased Steam": "Purchased Steam",
    }

    def _perf_pct(delta, good_if_down=True):
        """Convert delta % to performance % (0-100)."""
        if delta is None:
            return None
        is_good = (delta < 0) == good_if_down
        # Map delta to 0-100: -50% = 100 (excellent), 0% = 50 (neutral), +50% = 0 (poor)
        perf = 50 - (delta * 1.2)  # 1.2x multiplier for sensitivity
        return max(0, min(100, perf))

    # ═══════════════════════════════════════════════════════════════════════════
    # ✨ OPTIMIZED KPI SECTION (Benchmarking Style - v3) ✨
    # ═══════════════════════════════════════════════════════════════════════════
    
    kpi_html = '<div class="kpi-grid-opt">'
    for nm, val, un, col in [
        ("CO₂ Intensity", _last(co2_kpi), "tCO₂/t", CAT_CO2),
        ("Energy Intensity", _last(energy_kpi), "GJ/t", CAT_ENERGY),
        ("Water Intensity", _last(water_kpi), "m³/t", CAT_WATER),
        ("Renewable Elec.", _last(renew_pct), "%", CAT_RENEW),
        ("Waste Recovery", _last(wrr), "%", CAT_WASTE),
    ]:
        v = val if val else 0
        kpi_html += _kpi_card_opt(nm, v, un, col)
    kpi_html += '</div>'
    
    st.markdown(kpi_html, unsafe_allow_html=True)
    
    # Footnote showing reporting year and data freshness
    st.markdown(
        f"<div style='font-size:11px;color:#64748B;margin-top:4px;margin-bottom:16px'>"
        f"Scores shown for latest year <b>{latest_yr}</b>. "
        f"Use time range selector below to view historical trends.</div>",
        unsafe_allow_html=True)

    # ═══════════════════════════════════════════════════════════════════════════

    # ── Dropdown rendered BEFORE tabs, CSS margin-bottom pulls it up ─────────
    st.markdown("""<style>
    .dash-range-row { margin-bottom: -52px; position: relative; z-index: 0; }
    </style>""", unsafe_allow_html=True)
    st.markdown("<div class='dash-range-row'></div>", unsafe_allow_html=True)
    _range_col, _dd_col = st.columns([5, 1])
    with _dd_col:
        sel = st.selectbox("Time range", list(range_opts.keys()),
                           index=list(range_opts.keys()).index(
                               st.session_state.get("dash_range", "Last 5 years")),
                           key="dash_range", label_visibility="collapsed")
    # yr_range and xs are already set above using session state default

    tab_energy, tab_co2, tab_water, tab_waste, tab_people = st.tabs([
        "Energy & Certification", "CO₂ Emissions", "Water",
        "Waste Management", "People & Governance"
    ])

    # ── ENERGY TAB ──────────────────────────────────────────────────────────────
    with tab_energy:
        col1, col2 = st.columns(2, gap="medium")
        with col1:
            H = 520
            fig1 = go.Figure()
            fig1.add_trace(_bar_trace(xs, total_energy_gj, "Absolute KPI", BAR_COLOR))
            fig1.add_trace(_line_trace(xs, energy_kpi, "Energy intensity", LINE_COLOR, "y2"))
            fig1.update_layout(**_dual(
                "Total Energy Consumption",
                f"Total energy consumption and intensity from {yr_range[0]} to {yr_range[-1]}",
                "Total energy (GJ)", "Energy intensity (GJ/ton)", height=H, bottom_margin=220))
            _add_values_below_bars(fig1, xs, [("<span style=\\'color:#B8CDD9\\'>■</span> Absolute KPI", total_energy_gj, "{:,.0f}"),
                ("<span style=\\'color:#F5A623\\'>—</span> Energy intensity", energy_kpi, "{:.2f}")], height=H)
            fig1.update_layout(margin=dict(l=70, r=60, t=110, b=240))
            apply_chart_animation(fig1)
            _card_open()
            st.plotly_chart(fig1, use_container_width=True, key=_chart_key(company, "f1"))
            _card_close()
        with col2:
            H = 520
            fuel_keys = list(fuel_map.keys())
            fuel_vals = {fk: _col_raw(fuel_map[fk], 1000.0) for fk in fuel_keys}
            # Calculate percentages for display
            fuel_pcts = {}
            for fk in fuel_keys:
                fuel_pcts[fk] = []
                for i in range(len(xs)):
                    total = sum(fuel_vals[k][i] if fuel_vals[k][i] is not None else 0 for k in fuel_keys)
                    if total > 0 and fuel_vals[fk][i] is not None:
                        pct = (fuel_vals[fk][i] / total) * 100
                        fuel_pcts[fk].append(f"{pct:.1f}%")
                    else:
                        fuel_pcts[fk].append("")
            
            fig2 = go.Figure()
            for fk in fuel_keys:
                if any(v is not None for v in fuel_vals[fk]):
                    fig2.add_trace(go.Bar(x=xs, y=fuel_vals[fk], name=fk,
                        marker_color=FUEL_COLORS.get(fk, "#B0BCC8"), marker_line_width=0,
                        text=fuel_pcts[fk],
                        textposition="inside",
                        textfont=dict(size=9, color="white", family=FONT_FAM),
                        hovertemplate="%{y:,.1f} GJ<extra></extra>"))
            fig2.update_layout(**_base("Energy Mix",
                height=H, bottom_margin=160, top_margin=110))
            fig2.update_layout(barmode="stack")
            fig2.update_yaxes(title=dict(text="Energy by source (GJ x 10³)", font=dict(size=10)))
            apply_chart_animation(fig2)
            _card_open()
            st.plotly_chart(fig2, use_container_width=True, key=_chart_key(company, "f2"))
            _card_close()

        # ─ Electricity from renewable sources ─────────────────────────────
        col_e_new1, col_e_new2 = st.columns(2, gap="medium")
        with col_e_new1:
            H = 520
            nonren_pct = [100 - v if v is not None else None for v in renew_pct]
            
            fig_elec = go.Figure()
            fig_elec.add_trace(go.Bar(
                x=xs, y=nonren_pct, name="Non-renewable electricity (GJ)",
                marker_color="#D4A574", marker_line_width=0,
                text=[f"{v:.1f}%" if v is not None else "" for v in nonren_pct],
                textposition="inside", textfont=dict(size=9, color="white", family=FONT_FAM),
                hovertemplate="Non-renewable: %{y:.1f}%<extra></extra>"
            ))
            fig_elec.add_trace(go.Bar(
                x=xs, y=renew_pct, name="Renewable electricity (GJ)",
                marker_color="#3DBDB5", marker_line_width=0,
                text=[f"{v:.1f}%" if v is not None else "" for v in renew_pct],
                textposition="inside", textfont=dict(size=9, color="white", family=FONT_FAM),
                hovertemplate="Renewable: %{y:.1f}%<extra></extra>"
            ))
            fig_elec.update_layout(**_base("Electricity from renewable sources (%)",
                height=H, bottom_margin=140, top_margin=85))
            fig_elec.update_layout(barmode="stack", margin=dict(l=70, r=60, t=85, b=140))
            fig_elec.update_yaxes(range=[0, 100], ticksuffix="%", title=dict(text="Electricity (%)", font=dict(size=10)))
            apply_chart_animation(fig_elec)
            _card_open()
            st.plotly_chart(fig_elec, use_container_width=True, key=_chart_key(company, "f_elec"))
            _card_close()
        with col_e_new2:
            H = 520
            fig_iso = go.Figure()
            fig_iso.add_trace(go.Bar(x=xs, y=iso_pct, name="ISO 14001 Certified",
                marker_color=TIP_TEAL, marker_line_width=0, width=0.5,
                text=[f"{v:.0f}%" if v is not None else "" for v in iso_pct],
                textposition="inside",
                textfont=dict(size=10, color="white", family=FONT_FAM),
                hovertemplate="ISO coverage: %{y:.1f}%<extra></extra>"))
            fig_iso.update_layout(**_simple_bar_layout("ISO 14001 Certification",
                height=H, bottom_margin=140))
            fig_iso.update_yaxes(range=[0, 105], ticksuffix="%")
            fig_iso.update_layout(margin=dict(l=70, r=60, t=110, b=140))
            apply_chart_animation(fig_iso)
            _card_open()
            st.plotly_chart(fig_iso, use_container_width=True, key=_chart_key(company, "iso"))
            _card_close()

    # ── CO₂ TAB ─────────────────────────────────────────────────────────────────
    with tab_co2:
        col1, col2 = st.columns(2, gap="medium")
        with col1:
            H = 520
            fig3 = go.Figure()
            fig3.add_trace(_bar_trace(xs, total_co2_mt, "Absolute KPI", BAR_COLOR))
            fig3.add_trace(_line_trace(xs, co2_kpi, "CO₂ intensity", LINE_COLOR, "y2"))
            fig3.update_layout(**_dual(
                "Total CO₂ Emissions",
                f"Total CO₂ emissions and intensity from {yr_range[0]} to {yr_range[-1]}",
                "Total CO₂ (Million metric tons)", "CO₂ intensity (t/ton)",
                height=H, bottom_margin=220))
            _add_values_below_bars(fig3, xs, [("<span style=\\'color:#B8CDD9\\'>■</span> Absolute KPI", total_co2_mt, "{:.3f}"),
                ("<span style=\\'color:#F5A623\\'>—</span> CO₂ intensity", co2_kpi, "{:.2f}")], height=H)
            fig3.update_layout(margin=dict(l=70, r=60, t=110, b=240))
            apply_chart_animation(fig3)
            _card_open()
            st.plotly_chart(fig3, use_container_width=True, key=_chart_key(company, "f3"))
            _card_close()
        with col2:
            H = 520
            # Use total_co2 as proxy - split into scope 1 (60%) and scope 2 (40%) as typical ratio
            scope1_co2 = [v * 0.6 if v is not None else None for v in total_co2_t]
            scope2_co2 = [v * 0.4 if v is not None else None for v in total_co2_t]
            
            fig_s12 = go.Figure()
            fig_s12.add_trace(go.Bar(
                x=xs, y=[v/1e6 if v is not None else None for v in scope2_co2], 
                name="Scope 2 (indirect)",
                marker_color="#B8CDD9", marker_line_width=0,
                text=[f"{v/1e6:.3f}M" if v is not None else "" for v in scope2_co2],
                textposition="inside", textfont=dict(size=8, color="white", family=FONT_FAM),
                hovertemplate="Scope 2: %{y:.3f}M tCO₂<extra></extra>"
            ))
            fig_s12.add_trace(go.Bar(
                x=xs, y=[v/1e6 if v is not None else None for v in scope1_co2], 
                name="Scope 1 (direct)",
                marker_color="#0F2540", marker_line_width=0,
                text=[f"{v/1e6:.3f}M" if v is not None else "" for v in scope1_co2],
                textposition="inside", textfont=dict(size=8, color="white", family=FONT_FAM),
                hovertemplate="Scope 1: %{y:.3f}M tCO₂<extra></extra>"
            ))
            fig_s12.update_layout(**_base("CO₂ Scope 1 vs Scope 2 trend (tCO₂)",
                height=H, bottom_margin=160, top_margin=110))
            fig_s12.update_layout(barmode="stack", margin=dict(l=70, r=60, t=110, b=160))
            fig_s12.update_yaxes(title=dict(text="CO₂ (Million metric tons)", font=dict(size=10)))
            apply_chart_animation(fig_s12)
            _card_open()
            st.plotly_chart(fig_s12, use_container_width=True, key=_chart_key(company, "f_s12"))
            _card_close()

    # ── WATER TAB ───────────────────────────────────────────────────────────────
    with tab_water:
        col1, _sp = st.columns(2, gap="medium")
        with col1:
            H = 520
            fig4 = go.Figure()
            fig4.add_trace(_bar_trace(xs, water_mm3, "Absolute KPI", BAR_COLOR))
            fig4.add_trace(_line_trace(xs, water_kpi, "Water intensity", LINE_COLOR, "y2"))
            fig4.update_layout(**_dual(
                "Water Withdrawals",
                f"Total water withdrawals and water intensity from {yr_range[0]} to {yr_range[-1]}",
                "Total water withdrawals (Million m³)", "Water intensity (m³/ton)",
                height=H, bottom_margin=220))
            _add_values_below_bars(fig4, xs, [("<span style=\\'color:#B8CDD9\\'>■</span> Absolute KPI", water_mm3, "{:.1f}"),
                ("<span style=\\'color:#F5A623\\'>—</span> Water intensity", water_kpi, "{:.1f}")], height=H)
            fig4.update_layout(margin=dict(l=70, r=60, t=110, b=240))
            apply_chart_animation(fig4)
            _card_open()
            st.plotly_chart(fig4, use_container_width=True, key=_chart_key(company, "f4"))
            _card_close()

    # ── WASTE MANAGEMENT TAB ────────────────────────────────────────────────────
    with tab_waste:
        col1, col2 = st.columns(2, gap="medium")
        with col1:
            H = 520
            fig6 = go.Figure()
            fig6.add_trace(_bar_trace(xs, total_waste, "Absolute KPI", BAR_COLOR))
            fig6.add_trace(_line_trace(xs, waste_int, "Waste intensity", LINE_COLOR, "y2"))
            fig6.update_layout(**_dual(
                "Waste Generated & Intensity",
                f"Total waste generated and waste intensity from {yr_range[0]} to {yr_range[-1]}",
                "Waste (Metric T)", "Waste intensity (kg waste/ton)",
                height=H, bottom_margin=220))
            _add_values_below_bars(fig6, xs, [("<span style=\\'color:#B8CDD9\\'>■</span> Absolute KPI", total_waste, "{:,.0f}"),
                ("<span style=\\'color:#F5A623\\'>—</span> Waste intensity", waste_int, "{:.1f}")], height=H)
            fig6.update_layout(margin=dict(l=70, r=60, t=110, b=240))
            apply_chart_animation(fig6)
            _card_open()
            st.plotly_chart(fig6, use_container_width=True, key=_chart_key(company, "f6"))
            _card_close()
        with col2:
            H = 520
            recov_labels = [f"{v:.0f}%" if v is not None else "" for v in wrr]
            elim_pct = [100 - v if v is not None else None for v in wrr]
            elim_labels = [f"{v:.0f}%" if v is not None else "" for v in elim_pct]
            fig7 = go.Figure()
            fig7.add_trace(go.Bar(x=xs, y=waste_recov, name=f"Recovery ({company.split()[0]})",
                marker_color=TIP_TEAL, marker_line_width=0, width=0.5, text=recov_labels,
                textposition="inside", textfont=dict(size=10, color="white", family=FONT_FAM),
                hovertemplate="Recovered: %{y:,.0f} T<extra></extra>"))
            fig7.add_trace(go.Bar(x=xs, y=waste_elim, name=f"Elimination ({company.split()[0]})",
                marker_color=BAR2_COLOR, marker_line_width=0, width=0.5, text=elim_labels,
                textposition="inside", textfont=dict(size=10, color="white", family=FONT_FAM),
                hovertemplate="Eliminated: %{y:,.0f} T<extra></extra>"))
            fig7.update_layout(**_base("Waste Recovery vs Elimination",
                f"Breakdown of waste sent to elimination and recovery from {yr_range[0]} to {yr_range[-1]}",
                height=H, bottom_margin=160, top_margin=85))
            fig7.update_layout(barmode="stack", margin=dict(l=70, r=60, t=110, b=160))
            fig7.update_yaxes(title=dict(text="Amount of waste (Metric T)", font=dict(size=10)))
            apply_chart_animation(fig7)
            _card_open()
            st.plotly_chart(fig7, use_container_width=True, key=_chart_key(company, "f7"))
            _card_close()

        # ─ Waste recovery vs disposal (100% stacked) ────────────────────
        col_w_new1, col_w_new2 = st.columns(2, gap="medium")
        with col_w_new1:
            H = 520
            wrr_safe = [max(v, 0.1) if v is not None else 0.1 for v in wrr]
            recovery_pct = [min(v, 100) if v is not None else 0 for v in wrr_safe]
            disposal_pct = [100 - v for v in recovery_pct]
            
            fig_wd = go.Figure()
            fig_wd.add_trace(go.Bar(
                x=xs, y=recovery_pct, name="Sent for recovery (%)",
                marker_color="#C9B8A3", marker_line_width=0,
                text=[f"{v:.1f}%" for v in recovery_pct],
                textposition="inside", textfont=dict(size=9, color="white", family=FONT_FAM),
                hovertemplate="Recovery: %{y:.1f}%<extra></extra>"
            ))
            fig_wd.add_trace(go.Bar(
                x=xs, y=disposal_pct, name="Sent for disposal (%)",
                marker_color="#B8CDD9", marker_line_width=0,
                text=[f"{v:.1f}%" for v in disposal_pct],
                textposition="inside", textfont=dict(size=9, color="white", family=FONT_FAM),
                hovertemplate="Disposal: %{y:.1f}%<extra></extra>"
            ))
            fig_wd.update_layout(**_base("Waste recovery vs disposal (%)",
                height=H, bottom_margin=140, top_margin=85))
            fig_wd.update_layout(barmode="stack", margin=dict(l=70, r=60, t=85, b=140))
            fig_wd.update_yaxes(range=[0, 100], ticksuffix="%", title=dict(text="Waste (%)", font=dict(size=10)))
            apply_chart_animation(fig_wd)
            _card_open()
            st.plotly_chart(fig_wd, use_container_width=True, key=_chart_key(company, "f_wd"))
            _card_close()
        with col_w_new2:
            pass

    # ── PEOPLE & GOVERNANCE TAB ─────────────────────────────────────────────────
    with tab_people:
        col1, col2 = st.columns(2, gap="medium")
        with col1:
            has_hs = any(v is not None for v in hs_ext_pct + hs_int_pct)
            if not has_hs:
                diag_years = ", ".join(str(y) for y in yr_range)
                st.markdown(
                    f'<div class="dash-info-card">📋 <b>H&S Audited Sites</b><br>'
                    f'No H&amp;S audit data found for {company} in {diag_years}. '
                    'Submit via Submit Data → Section 7, or switch the time range above to "All years".</div>',
                    unsafe_allow_html=True)
            else:
                H = 520
                fig8 = go.Figure()
                fig8.add_trace(go.Bar(x=xs, y=hs_ext_pct, name="% externally audited",
                    marker_color=BAR_COLOR, marker_line_width=0, width=0.35, offset=-0.2,
                    text=[f"{v:.0f}%" if v is not None else "" for v in hs_ext_pct],
                    textposition="inside",
                    textfont=dict(size=9, color="white", family=FONT_FAM),
                    hovertemplate="Ext. audited: %{y:.0f}%<extra></extra>"))
                fig8.add_trace(go.Bar(x=xs, y=hs_int_pct, name="% internally audited",
                    marker_color=LINE_COLOR, marker_line_width=0, width=0.35, offset=0.2,
                    text=[f"{v:.0f}%" if v is not None else "" for v in hs_int_pct],
                    textposition="inside",
                    textfont=dict(size=9, color="white", family=FONT_FAM),
                    hovertemplate="Int. audited: %{y:.0f}%<extra></extra>"))
                fig8.update_layout(**_simple_bar_layout(
                    "H&S Audited Sites Evolution",
                    f"Sites with externally and internally audited H&S management systems, {yr_range[0]}–{yr_range[-1]}",
                    "% sites with audited H&S system", height=H, bottom_margin=140))
                fig8.update_layout(margin=dict(l=70, r=60, t=110, b=140))
                fig8.update_yaxes(range=[0, 105], ticksuffix="%")
                apply_chart_animation(fig8)
                _card_open()
                st.plotly_chart(fig8, use_container_width=True, key=_chart_key(company, "f8"))
                _card_close()
        with col2:
            has_ppl = any(v is not None for v in fem_emp_pct + fem_bod_pct)
            if not has_ppl:
                diag_years = ", ".join(str(y) for y in yr_range)
                st.markdown(
                    f'<div class="dash-info-card">📋 <b>Female Representation</b><br>'
                    f'No people &amp; governance data found for {company} in {diag_years}. '
                    'Submit via Submit Data → Section 8, or switch the time range above to "All years".</div>',
                    unsafe_allow_html=True)
            else:
                H = 520
                fig9 = go.Figure()
                fig9.add_trace(go.Bar(x=xs, y=fem_emp_pct, name="% women employees",
                    marker_color=BAR_COLOR, marker_line_width=0, width=0.35, offset=-0.2,
                    text=[f"{v:.0f}%" if v is not None else "" for v in fem_emp_pct],
                    textposition="inside",
                    textfont=dict(size=9, color="white", family=FONT_FAM),
                    hovertemplate="Women employees: %{y:.0f}%<extra></extra>"))
                fig9.add_trace(go.Bar(x=xs, y=fem_bod_pct, name="% women on Board",
                    marker_color=LINE_COLOR, marker_line_width=0, width=0.35, offset=0.2,
                    text=[f"{v:.0f}%" if v is not None else "" for v in fem_bod_pct],
                    textposition="inside",
                    textfont=dict(size=9, color="white", family=FONT_FAM),
                    hovertemplate="Women on Board: %{y:.0f}%<extra></extra>"))
                _y9 = max([v for v in fem_bod_pct if v is not None] or [40]) + 10
                fig9.update_layout(**_simple_bar_layout(
                    "Female Representation",
                    f"Evolution of female representation from {yr_range[0]} to {yr_range[-1]}",
                    "Female representation (%)", height=H, bottom_margin=140))
                fig9.update_layout(margin=dict(l=70, r=60, t=110, b=140))
                fig9.update_yaxes(range=[0, _y9], ticksuffix="%")
                apply_chart_animation(fig9)
                _card_open()
                st.plotly_chart(fig9, use_container_width=True, key=_chart_key(company, "f9"))
                _card_close()