"""
pages/page_home.py — Client home dashboard with KPI tiles and trend charts.
Globals are read from state.py (populated by app.py at startup).

v4 CHANGES:
- Blue hero banner replaces plain welcome text
- Year dropdown + Submit Data moved below banner
- Submission status shows which sections are missing
- KPI cards: show current year vs previous year (like benchmarking style)
- Red chip badges removed from KPI cards
- Tab order: Energy → CO₂ → Water → Waste & Fuel → People & Governance
- All charts: values annotated inside bars + below x-axis, no stray markers
- Waste & Fuel section redesigned with better charts
- People & Governance tab added with H&S and Female Representation charts
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

# ── Chart constants ────────────────────────────────────────────────────────────
FONT_FAM   = "Inter, -apple-system, BlinkMacSystemFont, sans-serif"
NAVY_DARK  = "#0F2540"
NAVY_MID   = "#1B4060"
AXIS_COL   = "#6f7882"
GRID_COL   = "#e6eaed"
AXIS_LINE  = "#9aa1a9"
BAR_BLUE   = "#B8CDD9"
BAR_GREEN  = "#7BAF74"
LINE_DARK  = "#2D4A5A"
LINE_AMBER = "#F5A623"

SECTION_LABELS = [
    "Energy",
    "CO₂ Emissions",
    "Water",
    "Waste",
    "People & Governance",
]


def _chart_base(title, height=320, bottom=55, top=50, r=70):
    return dict(
        plot_bgcolor="#f5f4f2", paper_bgcolor="#f5f4f2",
        height=height, bargap=0.24,
        margin=dict(l=55, r=r, t=top, b=bottom),
        title=dict(text=f"<b>{title}</b>",
                   font=dict(size=14, color="#2a2825", family=FONT_FAM), x=0),
        font=dict(family=FONT_FAM, size=11, color=AXIS_COL),
        hovermode="x unified",
        xaxis=dict(
            tickmode="array", showgrid=False, showline=True,
            linecolor=AXIS_LINE, linewidth=1.2,
            tickfont=dict(size=11, color=AXIS_COL), zeroline=False,
        ),
        yaxis=dict(
            showgrid=True, gridcolor=GRID_COL, showline=True,
            linecolor=AXIS_LINE, linewidth=1.2,
            tickfont=dict(size=11, color=AXIS_COL), zeroline=False,
        ),
        legend=dict(
            orientation="h", x=0.5, xanchor="center", y=-0.22,
            font=dict(size=11, color=AXIS_COL), bgcolor="rgba(0,0,0,0)",
        ),
    )


def _dual_y(fig, y2_title, y2_color=LINE_DARK):
    fig.update_layout(
        yaxis2=dict(
            title=dict(text=y2_title, font=dict(size=11, color=y2_color)),
            overlaying="y", side="right", tickformat=".2f",
            showgrid=False, showline=True, linecolor=AXIS_LINE,
            tickfont=dict(size=11, color=y2_color),
        )
    )


def _annot_bar_values(fig, xs, ys, fmt="{:.0f}", threshold=0):
    """Add values inside bars (white text)."""
    for x, y in zip(xs, ys):
        if y and y > threshold:
            fig.add_annotation(
                x=x, y=y / 2, text=fmt.format(y),
                showarrow=False,
                font=dict(size=8, color="white", family=FONT_FAM),
                xref="x", yref="y",
            )


def _annot_below(fig, xs, rows):
    """
    Add value rows below x-axis (like my dashboard / benchmarking style).
    rows = list of (label, values_list, fmt_str)
    """
    y_start  = -0.20
    row_gap  = 0.10
    ann_col  = "#374151"
    for i, (lbl, vals, fmt) in enumerate(rows):
        y_pos = y_start - i * row_gap
        fig.add_annotation(
            text=lbl, xref="paper", yref="paper",
            x=-0.01, y=y_pos, xanchor="right", yanchor="middle",
            showarrow=False, font=dict(size=8.5, color=ann_col, family=FONT_FAM),
        )
        for x, v in zip(xs, vals):
            if v is not None:
                fig.add_annotation(
                    text=fmt.format(v), xref="x", yref="paper",
                    x=x, y=y_pos, xanchor="center", yanchor="middle",
                    showarrow=False, font=dict(size=8.5, color=ann_col, family=FONT_FAM),
                )


def page_home():
    """
    Client Home — Hero banner, KPI cards (cur vs prev year), trend charts with values.
    Tab order: Energy → CO₂ → Water → Waste & Fuel → People & Governance
    """
    company   = st.session_state.user_company
    comp_hist = dl.get_company_hist(state.CONSOLIDATED_DF, company)
    years     = sorted(dl.get_years(state.CONSOLIDATED_DF, company))

    # Platform-wide current year (the most recent year ANY company has reported,
    # set in app.py via cfg.refresh_year_bounds across the whole consolidated file).
    # A behind-schedule or recently-onboarded client may not have data that far
    # yet — but they should still be able to select that year from the dropdown
    # (it'll just show up as fully "pending" in the submission status below).
    platform_curr_yr = state.CURR_YEAR
    if years:
        selectable_years = sorted(set(years) | set(range(years[0], platform_curr_yr + 1)), reverse=True)
    else:
        selectable_years = [platform_curr_yr]

    # ══════════════════════════════════════════════════════════════════════════
    # ── Hero banner (replaces plain welcome text) ─────────────────────────────
    # ══════════════════════════════════════════════════════════════════════════
    user_first = st.session_state.user_name.split()[0]
    st.markdown(f"""
    <div style="background:linear-gradient(135deg,{NAVY_DARK} 0%,{NAVY_MID} 100%);
        border-radius:12px;padding:22px 28px;margin-bottom:14px;
        display:flex;justify-content:space-between;align-items:flex-start">
      <div>
        <div style="font-size:11px;letter-spacing:.06em;text-transform:uppercase;
            color:rgba(255,255,255,.55);margin-bottom:6px">Tire Industry Platform</div>
        <div style="font-size:24px;font-weight:700;color:white;line-height:1.2">
          Welcome, {user_first} 👋</div>
        <div style="font-size:14px;font-weight:600;color:rgba(255,255,255,.85);margin-top:4px">
          {company}</div>
        <div style="font-size:12px;color:rgba(255,255,255,.6);margin-top:2px">
          Your Performance Dashboard</div>
      </div>
      <div style="text-align:right">
        <div style="font-size:10px;color:rgba(255,255,255,.5);text-transform:uppercase;
            letter-spacing:.05em">TIP ESG Platform</div>
        <div style="font-size:13px;color:rgba(255,255,255,.7);margin-top:4px">dss+ · Tire Industry Project</div>
      </div>
    </div>""", unsafe_allow_html=True)

    # ── Year selector + Submit Data (compact single row) ────────────────────
    _sp1, _dd_col, _btn_col = st.columns([4, 1, 1])
    with _dd_col:
        sel_yr = st.selectbox("Year", selectable_years,
                              key="home_yr", label_visibility="collapsed")
    with _btn_col:
        if st.button("📋 Submit Data", use_container_width=True, key="home_submit_btn"):
            st.session_state.page = "entry"
            st.rerun()

    if not years:
        st.markdown(empty_state_html("📊", "No data yet",
            "Submit your first KPI report to see your dashboard.",
            "→ Submit Data"), unsafe_allow_html=True)
        return

    # `sel_yr` drives the Submission Status strip below — it should reflect
    # exactly what the user picked, including years with no data at all.
    # `display_yr` is the year actually used for the KPI cards & trend charts:
    # if the selected year has no data yet, fall back to the most recent year
    # that *does* have data, so cards show real numbers instead of zeros.
    has_data_for_sel_yr = sel_yr in years
    display_yr = sel_yr if has_data_for_sel_yr else max(years)

    from formula_engine import TemplateInputs as TI, calculate as calc
    valid = {f.name for f in TI.__dataclass_fields__.values()}

    step  = dl.get_step_data(comp_hist, display_yr)
    clean = {k: v for k, v in step.items() if k in valid}
    inp   = TI(company=company, year=display_yr, **clean)
    out   = calc(inp)

    prev_out = None
    prev_inp = None
    if display_yr - 1 in years:
        ps = dl.get_step_data(comp_hist, display_yr - 1)
        pc = {k: v for k, v in ps.items() if k in valid}
        prev_inp = TI(company=company, year=display_yr - 1, **pc)
        prev_out = calc(prev_inp)

    # ══════════════════════════════════════════════════════════════════════════
    # ── Submission status strip (dynamic, shows missing sections) ────────────
    # ══════════════════════════════════════════════════════════════════════════
    status_hist  = dl.get_company_hist(state.CONSOLIDATED_DF, company)
    step_data_yr = dl.get_step_data(status_hist, sel_yr) if status_hist else {}

    # IMPORTANT: the submission-status checks below must reflect exactly what
    # was filed for `sel_yr` — never `display_yr`. `inp`/`out` above are
    # deliberately the *fallback* (most-recent-reported-year) values used only
    # for the KPI cards, so reusing them here would make an empty year look
    # "complete" just because an earlier year had data. Build sel_yr-only
    # calculated outputs from scratch:
    status_clean = {k: v for k, v in step_data_yr.items() if k in valid}
    status_inp   = TI(company=company, year=sel_yr, **status_clean)
    status_out   = calc(status_inp)

    def _calc_has(val, min_val=0.0001):
        """True only if a *formulated/calculated* value exists and is non-zero.
        This is what 'filed' means: the KPI cell that the company actually
        sees on the dashboard/My Records has a real number in it."""
        try:
            return val is not None and not pd.isna(val) and abs(float(val)) > min_val
        except (TypeError, ValueError):
            return False

    def _master_val(col):
        """Read a single calculated/master-CSV cell for company+sel_yr."""
        if state.CONSOLIDATED_DF.empty or "Company" not in state.CONSOLIDATED_DF.columns:
            return None
        row = state.CONSOLIDATED_DF[
            (state.CONSOLIDATED_DF["Company"] == company) &
            (state.CONSOLIDATED_DF["Year"] == sel_yr)
        ]
        if row.empty or col not in row.columns:
            return None
        v = row[col].values[0]
        return float(v) if pd.notna(v) else None

    # Electricity-by-country total (GJ) — the "Electricity details" tab rolls
    # up into the Energy section, per the same logic used in total_energy.
    # Strictly scoped to sel_yr, same as everything else in this block.
    elec_country_total_gj = 0.0
    if not state.CONSOLIDATED_DF.empty and company:
        co_row = state.CONSOLIDATED_DF[
            (state.CONSOLIDATED_DF["Company"] == company) &
            (state.CONSOLIDATED_DF["Year"] == sel_yr)
        ]
        if not co_row.empty:
            for col_gj in state.ELEC_COUNTRY_COLS.values():
                if col_gj in co_row.columns:
                    v = co_row[col_gj].values[0]
                    if pd.notna(v):
                        elec_country_total_gj += float(v)

    # H&S internally-audited % — the formulated People & Governance field
    # (same calc as render_people_tab: internal audit sites / total sites).
    hs_int_pct = _master_val("HS Internal Audit %")
    if hs_int_pct is None:
        ext = _master_val("HS Internal Audit Sites")
        ts  = status_inp.total_sites or step_data_yr.get("total_sites")
        if ext is not None and ts:
            hs_int_pct = round(ext / max(float(ts), 1) * 100, 1)

    # ── Section "filed" = the formulated/calculated cell for that section ────
    # is present and non-zero, for sel_yr specifically. Electricity rolls into Energy.
    section_checks = [
        _calc_has(status_out.total_energy) or _calc_has(elec_country_total_gj),     # Energy (+ Electricity)
        _calc_has(status_out.total_co2),                                            # CO2 — calculated scope1+scope2 total
        _calc_has(status_out.water_kpi),                                            # Water — calculated KPI
        _calc_has(status_out.waste_elimination) or _calc_has(status_inp.waste_total), # Waste — calculated elimination / total
        hs_int_pct is not None,                                                     # People & Governance — calculated %
    ]
    n_done  = sum(section_checks)
    pct     = n_done / len(section_checks) * 100
    sc      = GREEN if pct == 100 else (AMBER if pct >= 50 else RED)

    # Missing-sections label — shown inline on the right, parallel to verification status
    missing = [SECTION_LABELS[i] for i, done in enumerate(section_checks) if not done]

    # DSS+ verification status
    verif_status = "Not Submitted"
    verif_color  = "#94A3B8"
    verif_icon   = "○"
    try:
        vcsv = Path("data_storage/verifications.csv")
        if vcsv.exists():
            import csv
            with open(vcsv, newline="") as f:
                for row in csv.DictReader(f):
                    if (row.get("Company","").strip() == company and
                            str(row.get("Year","")).strip() == str(sel_yr)):
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

    # ── Single-row: status bar + year dropdown + submit data ─────────────────
    with _sp1:
        # If any section is missing for sel_yr, show ONLY the red "Pending: ..."
        # text — don't also show the (unrelated) DSS verification status, since
        # that duplicated/confusing combo was the original ask to simplify.
        if missing:
            right_side_text = f'<span style="color:{RED};font-weight:600">Pending: {", ".join(missing)}</span>'
            right_side_color = RED
        else:
            right_side_text  = f'{verif_icon} {verif_status}'
            right_side_color = verif_color

        st.markdown(f"""
        <div style="background:#fff;border:1px solid {BORDER};border-radius:8px;
            padding:9px 16px;display:flex;align-items:center;gap:12px;height:38px">
          <div style="flex:1;min-width:0">
            <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:3px">
              <div style="display:flex;align-items:center;gap:8px">
                <span style="font-size:11px;color:{MUTED};white-space:nowrap">{sel_yr} Submission Status</span>
                <span style="font-size:12px;font-weight:700;color:{sc}">{n_done}/{len(section_checks)}</span>
                <span style="font-size:11px;color:{MUTED}">sections complete</span>
              </div>
              <span style="font-size:11px;color:{right_side_color};font-weight:600;white-space:nowrap">{right_side_text}</span>
            </div>
            <div style="background:#F1F5F9;border-radius:3px;height:4px;overflow:hidden">
              <div style="background:{sc};width:{pct:.0f}%;height:100%;border-radius:3px;transition:width 0.8s ease"></div>
            </div>
          </div>
        </div>
        """, unsafe_allow_html=True)

    # ══════════════════════════════════════════════════════════════════════════
    # ── KPI Cards: current vs previous year (benchmarking-style side-by-side) ─
    # ══════════════════════════════════════════════════════════════════════════
    renew_tot = max(inp.renew_elec_purchased + inp.nonrenew_elec_purchased + inp.self_gen_elec, 1)
    renew_pct = inp.renew_elec_purchased / renew_tot * 100

    p_renew_pct = None
    if prev_inp is not None:
        p_rt = max(prev_inp.renew_elec_purchased + prev_inp.nonrenew_elec_purchased + prev_inp.self_gen_elec, 1)
        p_renew_pct = prev_inp.renew_elec_purchased / p_rt * 100

    prev_yr = display_yr - 1

    # (label, color, unit, cur_val, prev_val, fmt)
    KPI_CARDS = [
        ("CO₂ Absolute",     CAT_CO2,    "tCO₂",  out.total_co2,              prev_out.total_co2              if prev_out else None, "{:,.0f}"),
        ("CO₂ Intensity",    CAT_CO2,    "t/t",   out.co2_kpi,               prev_out.co2_kpi               if prev_out else None, "{:.3f}"),
        ("Energy Intensity", CAT_ENERGY, "GJ/t",  out.energy_kpi,            prev_out.energy_kpi            if prev_out else None, "{:.2f}"),
        ("Renewable Share",  CAT_RENEW,  "%",     renew_pct,                 p_renew_pct,                                          "{:.1f}"),
        ("Water Intensity",  CAT_WATER,  "m³/t",  out.water_kpi,             prev_out.water_kpi             if prev_out else None, "{:.2f}"),
        ("Water Withdrawal", CAT_WATER,  "m³",    inp.water_withdrawals,     prev_inp.water_withdrawals     if prev_inp else None, "{:,.0f}"),
        ("Waste Recovery",   CAT_WASTE,  "%",     out.waste_recovery_pct*100,(prev_out.waste_recovery_pct*100 if prev_out else None), "{:.1f}"),
        ("ISO 14001",        GREEN,      "%",     out.pct_certified*100,     (prev_out.pct_certified*100    if prev_out else None), "{:.0f}"),
    ]

    for row_start in [0, 4]:
        cols = st.columns(4)
        for i, (label, color, unit, cur_val, prev_val, fmt) in enumerate(KPI_CARDS[row_start:row_start+4]):
            cur_str  = fmt.format(cur_val)  if cur_val  is not None else "—"
            prev_str = fmt.format(prev_val) if prev_val is not None else "—"
            with cols[i]:
                st.markdown(f"""
                <div style="background:#fff;border:1px solid {BORDER};border-radius:10px;
                    padding:14px 16px 12px;margin-bottom:8px;
                    animation:tipFadeIn 400ms ease-out {i*70+row_start*30}ms both;
                    transition:box-shadow 200ms,transform 200ms"
                    onmouseover="this.style.boxShadow='0 6px 20px rgba(15,23,42,.1)';this.style.transform='translateY(-2px)'"
                    onmouseout="this.style.boxShadow='';this.style.transform=''">
                  <div style="font-size:9.5px;font-weight:600;color:{MUTED};
                      text-transform:uppercase;letter-spacing:.6px;margin-bottom:8px">{label}</div>
                  <div style="display:flex;justify-content:center;align-items:flex-end;gap:14px">
                    <div style="text-align:center">
                      <div style="font-size:9px;color:{MUTED};margin-bottom:2px">{display_yr}</div>
                      <div style="font-size:22px;font-weight:700;color:{color};
                          font-variant-numeric:tabular-nums;line-height:1;white-space:nowrap">{cur_str}</div>
                      <div style="font-size:9px;color:{MUTED};margin-top:2px">{unit}</div>
                    </div>
                    <div style="width:1px;height:34px;background:{BORDER};margin-bottom:4px"></div>
                    <div style="text-align:center">
                      <div style="font-size:9px;color:{MUTED};margin-bottom:2px">{prev_yr}</div>
                      <div style="font-size:22px;font-weight:700;color:{MUTED};
                          font-variant-numeric:tabular-nums;line-height:1;white-space:nowrap">{prev_str}</div>
                      <div style="font-size:9px;color:{MUTED};margin-top:2px">{unit}</div>
                    </div>
                  </div>
                </div>""", unsafe_allow_html=True)

    # ── KPI footnote — which years are shown ─────────────────────────────────
    prev_yr_note = f" vs {prev_yr}" if prev_out is not None else ""
    if has_data_for_sel_yr:
        footnote = (
            f"KPI values shown for <b>{display_yr}</b>{prev_yr_note}. "
            f"Change year using the selector above to view different periods."
        )
    else:
        footnote = (
            f"<b>{sel_yr}</b> has not been submitted yet — showing the most recently "
            f"reported year, <b>{display_yr}</b>{prev_yr_note}, instead. "
            f"Use Submit Data to report {sel_yr}."
        )
    st.markdown(
        f"<div style='font-size:11px;color:{MUTED};text-align:left;margin-top:2px;margin-bottom:12px'>"
        f"{footnote}</div>",
        unsafe_allow_html=True,
    )

    # ══════════════════════════════════════════════════════════════════════════
    # ── Build multi-year KPI lookup ────────────────────────────────────────────
    # ══════════════════════════════════════════════════════════════════════════
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
            "energy_total": ii.nat_gas + ii.coal_sub + ii.diesel + ii.biomass
                            + ii.renew_elec_purchased + ii.nonrenew_elec_purchased,
            "energy_kpi": o.energy_kpi,
            "water_kpi": o.water_kpi, "waste_pct": o.waste_recovery_pct * 100,
            "renew_pct": ii.renew_elec_purchased / rt * 100,
            "nat_gas": ii.nat_gas, "coal": ii.coal_sub, "diesel": ii.diesel,
            "biomass": ii.biomass, "renew_elec": ii.renew_elec_purchased,
            "nonrenew_elec": ii.nonrenew_elec_purchased,
            "water_m3": ii.water_withdrawals, "production": ii.production,
            "waste_total":    sd.get("waste_total",    0),
            "waste_recovery": sd.get("waste_recovery", 0),
            # People & governance
            "hs_ext_pct": sd.get("hs_ext_audit_pct",  None),
            "hs_int_pct": sd.get("hs_int_audit_pct",  None),
            "fem_emp_pct": sd.get("female_emp_pct",   None),
            "fem_bod_pct": sd.get("female_board_pct", None),
        }

    ys     = [y for y in years if yr_kpis.get(y, {}).get("production", 0) > 0]
    if not ys: ys = years
    ys     = ys[-10:]
    ys_str = [str(y) for y in ys]
    xi     = list(range(len(ys)))   # integer x-positions

    # ══════════════════════════════════════════════════════════════════════════
    # ── Tabs: Energy → CO₂ → Water → Waste & Fuel → People & Governance ──────
    # ══════════════════════════════════════════════════════════════════════════
    t_energy, t_co2, t_water, t_waste, t_people = st.tabs([
        "Energy & Certification", "CO₂ Emissions", "Water",
        "Waste Management", "People & Governance",
    ])

    # ── TAB 1: ENERGY ─────────────────────────────────────────────────────────
    with t_energy:
        c1, c2 = st.columns(2, gap="medium")

        # Left: Total energy + intensity dual-axis
        with c1:
            en_vals  = [yr_kpis[y]["energy_total"] / 1e6 for y in ys]   # PJ-scale for readability
            en_kpi   = [yr_kpis[y]["energy_kpi"]          for y in ys]

            fig_en = go.Figure()
            fig_en.add_trace(go.Bar(
                x=xi, y=en_vals, name="Total Energy",
                marker_color=BAR_BLUE, marker_line_width=0, width=0.6,
                customdata=ys_str,
                hovertemplate="<b>%{customdata}</b><br>Energy: %{y:,.1f} PJ<extra></extra>",
                text=[f"{v:.1f}" for v in en_vals],
                textposition="inside",
                textfont=dict(size=8, color="white", family=FONT_FAM),
            ))
            fig_en.add_trace(go.Scatter(
                x=xi, y=en_kpi, name="Energy Intensity (GJ/t)",
                yaxis="y2", mode="lines",
                line=dict(color=LINE_AMBER, width=2.2),
                customdata=ys_str,
                hovertemplate="<b>%{customdata}</b><br>Intensity: %{y:.2f} GJ/t<extra></extra>",
            ))
            lay = _chart_base("Total Energy Consumption", height=360, bottom=130)
            lay["xaxis"]["tickvals"] = xi
            lay["xaxis"]["ticktext"] = ys_str
            lay["yaxis"]["title"] = dict(text="Total Energy (PJ)", font=dict(size=11, color=AXIS_COL))
            lay["yaxis2"] = dict(
                title=dict(text="Energy Intensity (GJ/t)", font=dict(size=11, color=LINE_AMBER)),
                overlaying="y", side="right", tickformat=".2f",
                showgrid=False, showline=True, linecolor=AXIS_LINE,
                tickfont=dict(size=11, color=LINE_AMBER),
            )
            lay["margin"] = dict(l=60, r=70, t=50, b=130)
            fig_en.update_layout(**lay)
            _annot_below(fig_en, xi, [
                ("Total Energy (PJ)", en_vals, "{:.2f}"),
                ("Intensity (GJ/t)",  en_kpi,  "{:.2f}"),
            ])
            apply_chart_animation(fig_en)
            st.plotly_chart(fig_en, use_container_width=True)

        # Right: Energy mix stacked bar
        with c2:
            fuel_cfg = [
                ("Renewable Elec.",  [yr_kpis[y]["renew_elec"]    / 1e3 for y in ys], "#7BAF74"),
                ("Non-Renew. Elec.", [yr_kpis[y]["nonrenew_elec"] / 1e3 for y in ys], "#B8CDD9"),
                ("Natural Gas",      [yr_kpis[y]["nat_gas"]        / 1e3 for y in ys], "#C8B49A"),
                ("Coal",             [yr_kpis[y]["coal"]           / 1e3 for y in ys], "#2D4A5A"),
                ("Diesel",           [yr_kpis[y]["diesel"]         / 1e3 for y in ys], "#E0935A"),
                ("Biomass",          [yr_kpis[y]["biomass"]        / 1e3 for y in ys], "#9FB8C5"),
            ]
            fig_mix = go.Figure()
            for label, vals, color in fuel_cfg:
                if any(v > 0 for v in vals):
                    fig_mix.add_trace(go.Bar(
                        name=label, x=xi, y=vals,
                        marker_color=color, marker_line_width=0, width=0.6,
                        customdata=ys_str,
                        hovertemplate=f"<b>%{{customdata}}</b> · {label}<br>%{{y:,.1f}} TJ<extra></extra>",
                    ))
            lay2 = _chart_base("Energy Mix by Source", height=360, bottom=130)
            lay2["xaxis"]["tickvals"] = xi
            lay2["xaxis"]["ticktext"] = ys_str
            lay2["yaxis"]["title"] = dict(text="Energy (TJ)", font=dict(size=11, color=AXIS_COL))
            lay2["margin"] = dict(l=60, r=40, t=50, b=130)
            fig_mix.update_layout(**lay2, barmode="stack")
            apply_chart_animation(fig_mix)
            st.plotly_chart(fig_mix, use_container_width=True)

        # Bottom: Renewable % stacked 100%
        c3, _ = st.columns(2, gap="medium")
        with c3:
            renew_vals    = [yr_kpis[y]["renew_pct"]        for y in ys]
            nonrenew_vals = [100 - v                          for v in renew_vals]
            fig_ren = go.Figure()
            fig_ren.add_trace(go.Bar(
                x=xi, y=nonrenew_vals, name="Non-Renewable Electricity",
                marker_color="#D4A574", marker_line_width=0, width=0.6,
                text=[f"{v:.1f}%" for v in nonrenew_vals],
                textposition="inside", textfont=dict(size=8, color="white", family=FONT_FAM),
                customdata=ys_str,
                hovertemplate="<b>%{customdata}</b><br>Non-Renewable: %{y:.1f}%<extra></extra>",
            ))
            fig_ren.add_trace(go.Bar(
                x=xi, y=renew_vals, name="Renewable Electricity",
                marker_color="#3DBDB5", marker_line_width=0, width=0.6,
                text=[f"{v:.1f}%" for v in renew_vals],
                textposition="inside", textfont=dict(size=8, color="white", family=FONT_FAM),
                customdata=ys_str,
                hovertemplate="<b>%{customdata}</b><br>Renewable: %{y:.1f}%<extra></extra>",
            ))
            lay3 = _chart_base("Electricity from Renewable Sources (%)", height=300, bottom=55)
            lay3["xaxis"]["tickvals"] = xi
            lay3["xaxis"]["ticktext"] = ys_str
            lay3["yaxis"].update(range=[0, 100], ticksuffix="%",
                                 title=dict(text="Electricity (%)", font=dict(size=11, color=AXIS_COL)))
            lay3["margin"] = dict(l=60, r=40, t=50, b=80)
            fig_ren.update_layout(**lay3, barmode="stack")
            apply_chart_animation(fig_ren)
            st.plotly_chart(fig_ren, use_container_width=True)

    # ── TAB 2: CO₂ EMISSIONS ──────────────────────────────────────────────────
    with t_co2:
        scope1 = [yr_kpis[y]["scope1"]   for y in ys]
        scope2 = [yr_kpis[y]["scope2"]   for y in ys]
        co2kpi = [yr_kpis[y]["co2_kpi"]  for y in ys]

        fig_co2 = go.Figure()
        fig_co2.add_trace(go.Bar(
            x=xi, y=scope2, name="Scope 2 (indirect)",
            marker_color="rgba(185,200,212,0.88)", marker_line_width=0, width=0.62,
            text=[f"{v/1e3:.0f}k" if v else "" for v in scope2],
            textposition="inside", textfont=dict(size=8, color="white", family=FONT_FAM),
            customdata=ys_str,
            hovertemplate="<b>%{customdata}</b> · Scope 2<br>%{y:,.0f} tCO₂<extra></extra>",
        ))
        fig_co2.add_trace(go.Bar(
            x=xi, y=scope1, name="Scope 1 (direct)",
            marker_color="rgba(70,92,102,0.88)", marker_line_width=0, width=0.62,
            text=[f"{v/1e3:.0f}k" if v else "" for v in scope1],
            textposition="inside", textfont=dict(size=8, color="white", family=FONT_FAM),
            customdata=ys_str,
            hovertemplate="<b>%{customdata}</b> · Scope 1<br>%{y:,.0f} tCO₂<extra></extra>",
        ))
        fig_co2.add_trace(go.Scatter(
            x=xi, y=co2kpi, name="CO₂ Intensity (t/t)",
            yaxis="y2", mode="lines",
            line=dict(color="#cab6a5", width=2.2),
            customdata=ys_str,
            hovertemplate="<b>%{customdata}</b><br>Intensity: %{y:.3f} t/t<extra></extra>",
        ))
        # Best-intensity annotation
        if len(ys) >= 2:
            best_y  = min(ys, key=lambda y: yr_kpis[y]["co2_kpi"])
            best_xi = ys.index(best_y)
            fig_co2.add_annotation(
                x=best_xi, y=yr_kpis[best_y]["co2_kpi"], yref="y2",
                text="Best", showarrow=True, arrowhead=2, ax=0, ay=-30,
                font=dict(size=11, color=GREEN), arrowcolor=GREEN,
            )

        lay_co2 = _chart_base("Total CO₂ Emissions (Scope 1 + 2) with Intensity", height=380, bottom=140)
        lay_co2["xaxis"]["tickvals"] = xi
        lay_co2["xaxis"]["ticktext"] = ys_str
        lay_co2["yaxis"]["title"] = dict(text="tCO₂", font=dict(size=11, color=AXIS_COL))
        lay_co2["yaxis"]["tickformat"] = ","
        lay_co2["yaxis2"] = dict(
            title=dict(text="CO₂ Intensity (t/t)", font=dict(size=11, color="#cab6a5")),
            overlaying="y", side="right", tickformat=".3f",
            showgrid=False, showline=True, linecolor=AXIS_LINE,
            tickfont=dict(size=11, color=AXIS_COL),
        )
        lay_co2["barmode"] = "stack"
        lay_co2["margin"] = dict(l=60, r=80, t=50, b=140)
        fig_co2.update_layout(**lay_co2)
        _annot_below(fig_co2, xi, [
            ("Scope 1 (tCO₂)", scope1, "{:,.0f}"),
            ("Scope 2 (tCO₂)", scope2, "{:,.0f}"),
            ("Intensity (t/t)", co2kpi, "{:.3f}"),
        ])
        apply_chart_animation(fig_co2)
        st.plotly_chart(fig_co2, use_container_width=True)

    # ── TAB 3: WATER ──────────────────────────────────────────────────────────
    with t_water:
        c1, _ = st.columns(2, gap="medium")
        with c1:
            w_m3  = [yr_kpis[y]["water_m3"]  for y in ys]
            w_kpi = [yr_kpis[y]["water_kpi"] for y in ys]
            w_mm3 = [v / 1e6 for v in w_m3]   # million m³

            fig_water = go.Figure()
            fig_water.add_trace(go.Bar(
                x=xi, y=w_mm3, name="Total Withdrawals",
                marker_color=BAR_BLUE, marker_line_width=0, width=0.62,
                text=[f"{v:.1f}" for v in w_mm3],
                textposition="inside", textfont=dict(size=8, color="white", family=FONT_FAM),
                customdata=ys_str,
                hovertemplate="<b>%{customdata}</b><br>%{y:,.1f} Mm³<extra></extra>",
            ))
            fig_water.add_trace(go.Scatter(
                x=xi, y=w_kpi, name="Intensity (m³/t)",
                yaxis="y2", mode="lines",
                line=dict(color=LINE_DARK, width=2.2),
                customdata=ys_str,
                hovertemplate="<b>%{customdata}</b><br>Intensity: %{y:.2f} m³/t<extra></extra>",
            ))
            lay_w = _chart_base("Water Withdrawals & Intensity", height=380, bottom=120)
            lay_w["xaxis"]["tickvals"] = xi
            lay_w["xaxis"]["ticktext"] = ys_str
            lay_w["yaxis"]["title"] = dict(text="Total Withdrawals (Million m³)", font=dict(size=11, color=AXIS_COL))
            lay_w["yaxis"]["tickformat"] = ".1f"
            lay_w["yaxis2"] = dict(
                title=dict(text="Water Intensity (m³/t)", font=dict(size=11, color=LINE_DARK)),
                overlaying="y", side="right", tickformat=".2f",
                showgrid=False, showline=True, linecolor=AXIS_LINE,
                tickfont=dict(size=11, color=LINE_DARK),
            )
            lay_w["margin"] = dict(l=60, r=80, t=50, b=120)
            fig_water.update_layout(**lay_w)
            _annot_below(fig_water, xi, [
                ("Withdrawals (Mm³)", w_mm3, "{:.1f}"),
                ("Intensity (m³/t)", w_kpi,  "{:.2f}"),
            ])
            apply_chart_animation(fig_water)
            st.plotly_chart(fig_water, use_container_width=True)

    # ── TAB 4: WASTE & FUEL ───────────────────────────────────────────────────
    with t_waste:
        w_total    = [yr_kpis[y]["waste_total"]    for y in ys]
        w_recovery = [yr_kpis[y]["waste_recovery"] for y in ys]
        w_pcts     = [yr_kpis[y]["waste_pct"]      for y in ys]
        w_elim     = [max(t - r, 0) for t, r in zip(w_total, w_recovery)]

        c1, c2 = st.columns(2, gap="medium")

        # Left: Waste total (stacked: recovered + eliminated) with recovery % line
        with c1:
            fig_waste = go.Figure()
            fig_waste.add_trace(go.Bar(
                x=xi, y=w_recovery, name="Recovered",
                marker_color=BAR_GREEN, marker_line_width=0, width=0.6,
                text=[f"{v:,.0f}" if v else "" for v in w_recovery],
                textposition="inside", textfont=dict(size=8, color="white", family=FONT_FAM),
                customdata=ys_str,
                hovertemplate="<b>%{customdata}</b><br>Recovered: %{y:,.0f} T<extra></extra>",
            ))
            fig_waste.add_trace(go.Bar(
                x=xi, y=w_elim, name="Eliminated/Disposed",
                marker_color="#2D4A5A", marker_line_width=0, width=0.6,
                text=[f"{v:,.0f}" if v else "" for v in w_elim],
                textposition="inside", textfont=dict(size=8, color="white", family=FONT_FAM),
                customdata=ys_str,
                hovertemplate="<b>%{customdata}</b><br>Disposed: %{y:,.0f} T<extra></extra>",
            ))
            fig_waste.add_trace(go.Scatter(
                x=xi, y=w_pcts, name="Recovery %",
                yaxis="y2", mode="lines",
                line=dict(color=LINE_AMBER, width=2.2),
                customdata=ys_str,
                hovertemplate="<b>%{customdata}</b><br>Recovery: %{y:.1f}%<extra></extra>",
            ))
            lay_wst = _chart_base("Waste: Recovery vs Disposal (T)", height=380, bottom=130)
            lay_wst["xaxis"]["tickvals"] = xi
            lay_wst["xaxis"]["ticktext"] = ys_str
            lay_wst["yaxis"]["title"] = dict(text="Waste (Metric T)", font=dict(size=11, color=AXIS_COL))
            lay_wst["yaxis"]["tickformat"] = ","
            lay_wst["yaxis2"] = dict(
                title=dict(text="Recovery %", font=dict(size=11, color=LINE_AMBER)),
                overlaying="y", side="right", range=[0, 110], ticksuffix="%",
                showgrid=False, showline=True, linecolor=AXIS_LINE,
                tickfont=dict(size=11, color=LINE_AMBER),
            )
            lay_wst["barmode"] = "stack"
            lay_wst["margin"]  = dict(l=60, r=80, t=50, b=130)
            fig_waste.update_layout(**lay_wst)
            _annot_below(fig_waste, xi, [
                ("Recovered (T)",  w_recovery, "{:,.0f}"),
                ("Disposed (T)",   w_elim,     "{:,.0f}"),
                ("Recovery %",     w_pcts,     "{:.1f}%"),
            ])
            apply_chart_animation(fig_waste)
            st.plotly_chart(fig_waste, use_container_width=True)

        # Right: Recovery % trend with colour bands
        with c2:
            fig_rec = go.Figure()
            fig_rec.add_hrect(y0=0,  y1=70,  fillcolor="#FEE2E2", opacity=0.25, line_width=0)
            fig_rec.add_hrect(y0=70, y1=85,  fillcolor="#FEF3C7", opacity=0.25, line_width=0)
            fig_rec.add_hrect(y0=85, y1=100, fillcolor="#DCFCE7", opacity=0.25, line_width=0)
            fig_rec.add_hline(y=90, line_dash="dot", line_color=GREEN, line_width=1.5,
                              annotation_text="Target 90%",
                              annotation_font=dict(size=9, color=GREEN))
            fig_rec.add_trace(go.Scatter(
                x=xi, y=w_pcts, name="Recovery %",
                mode="lines+markers",
                fill="tozeroy", fillcolor="rgba(123,175,116,0.12)",
                line=dict(color="#465c66", width=2.2),
                marker=dict(size=7, color="#f5f4f2",
                            line=dict(color="#465c66", width=2)),
                customdata=ys_str,
                hovertemplate="<b>%{customdata}</b><br>Recovery: %{y:.1f}%<extra></extra>",
            ))
            # Annotate each point
            for x, y in zip(xi, w_pcts):
                if y:
                    fig_rec.add_annotation(
                        x=x, y=y + 3, text=f"{y:.1f}%",
                        showarrow=False,
                        font=dict(size=8, color="#465c66", family=FONT_FAM),
                    )
            lay_rec = _chart_base("Waste Recovery Rate (%)", height=380, bottom=55)
            lay_rec["xaxis"]["tickvals"] = xi
            lay_rec["xaxis"]["ticktext"] = ys_str
            lay_rec["yaxis"].update(range=[0, 105], ticksuffix="%",
                                    title=dict(text="Recovery %", font=dict(size=11, color=AXIS_COL)))
            lay_rec["showlegend"] = False
            lay_rec["margin"] = dict(l=60, r=40, t=50, b=55)
            fig_rec.update_layout(**lay_rec)
            apply_chart_animation(fig_rec)
            st.plotly_chart(fig_rec, use_container_width=True)

        # Bottom row: Fuel mix (from yr_kpis) full-width
        fuel_cfg2 = [
            ("Renewable Elec.",  [yr_kpis[y]["renew_elec"]    / 1e3 for y in ys], "#7BAF74"),
            ("Non-Renew. Elec.", [yr_kpis[y]["nonrenew_elec"] / 1e3 for y in ys], "#B8CDD9"),
            ("Natural Gas",      [yr_kpis[y]["nat_gas"]        / 1e3 for y in ys], "#C8B49A"),
            ("Coal",             [yr_kpis[y]["coal"]           / 1e3 for y in ys], "#2D4A5A"),
            ("Diesel",           [yr_kpis[y]["diesel"]         / 1e3 for y in ys], "#E0935A"),
            ("Biomass",          [yr_kpis[y]["biomass"]        / 1e3 for y in ys], "#9FB8C5"),
        ]
        fig_fuel = go.Figure()
        for label, vals, color in fuel_cfg2:
            if any(v > 0 for v in vals):
                fig_fuel.add_trace(go.Bar(
                    name=label, x=xi, y=vals,
                    marker_color=color, marker_line_width=0, width=0.6,
                    customdata=ys_str,
                    hovertemplate=f"<b>%{{customdata}}</b> · {label}<br>%{{y:,.1f}} TJ<extra></extra>",
                ))
        lay_fuel = _chart_base("Fuel & Energy Mix by Source (TJ)", height=300, bottom=55)
        lay_fuel["xaxis"]["tickvals"] = xi
        lay_fuel["xaxis"]["ticktext"] = ys_str
        lay_fuel["yaxis"]["title"] = dict(text="Energy (TJ)", font=dict(size=11, color=AXIS_COL))
        lay_fuel["margin"] = dict(l=60, r=40, t=50, b=80)
        fig_fuel.update_layout(**lay_fuel, barmode="stack")
        apply_chart_animation(fig_fuel)
        st.plotly_chart(fig_fuel, use_container_width=True)

    # ── TAB 5: PEOPLE & GOVERNANCE ─────────────────────────────────────────────
    with t_people:
        hs_ext  = [yr_kpis[y]["hs_ext_pct"]  for y in ys]
        hs_int  = [yr_kpis[y]["hs_int_pct"]  for y in ys]
        fem_emp = [yr_kpis[y]["fem_emp_pct"] for y in ys]
        fem_bod = [yr_kpis[y]["fem_bod_pct"] for y in ys]

        has_hs  = any(v is not None for v in hs_ext + hs_int)
        has_ppl = any(v is not None for v in fem_emp + fem_bod)

        c1, c2 = st.columns(2, gap="medium")

        with c1:
            if not has_hs:
                st.markdown(
                    f"<div style='background:#F8FAFC;border:1px dashed #D1D9E0;"
                    f"border-radius:10px;padding:26px 18px;text-align:center;"
                    f"color:#6B7280;font-size:12.5px;margin-bottom:16px'>"
                    f"📋 <b>H&S Audited Sites</b><br>"
                    f"No H&amp;S audit data found for {company}. "
                    f"Submit via Submit Data → Section 7.</div>",
                    unsafe_allow_html=True)
            else:
                hs_ext_clean = [v if v is not None else 0 for v in hs_ext]
                hs_int_clean = [v if v is not None else 0 for v in hs_int]
                fig_hs = go.Figure()
                fig_hs.add_trace(go.Bar(
                    x=xi, y=hs_ext_clean, name="% Externally Audited",
                    marker_color=BAR_BLUE, marker_line_width=0, width=0.35, offset=-0.2,
                    text=[f"{v:.0f}%" if v else "" for v in hs_ext_clean],
                    textposition="inside", textfont=dict(size=9, color="white", family=FONT_FAM),
                    customdata=ys_str,
                    hovertemplate="<b>%{customdata}</b><br>Ext. audited: %{y:.0f}%<extra></extra>",
                ))
                fig_hs.add_trace(go.Bar(
                    x=xi, y=hs_int_clean, name="% Internally Audited",
                    marker_color=LINE_AMBER, marker_line_width=0, width=0.35, offset=0.2,
                    text=[f"{v:.0f}%" if v else "" for v in hs_int_clean],
                    textposition="inside", textfont=dict(size=9, color="white", family=FONT_FAM),
                    customdata=ys_str,
                    hovertemplate="<b>%{customdata}</b><br>Int. audited: %{y:.0f}%<extra></extra>",
                ))
                lay_hs = _chart_base("H&S Audited Sites Evolution (%)", height=380, bottom=80)
                lay_hs["xaxis"]["tickvals"] = xi
                lay_hs["xaxis"]["ticktext"] = ys_str
                lay_hs["yaxis"].update(range=[0, 105], ticksuffix="%",
                                       title=dict(text="% Sites Audited", font=dict(size=11, color=AXIS_COL)))
                lay_hs["margin"] = dict(l=60, r=40, t=50, b=100)
                fig_hs.update_layout(**lay_hs)
                _annot_below(fig_hs, xi, [
                    ("Ext. Audit %", hs_ext_clean, "{:.0f}%"),
                    ("Int. Audit %", hs_int_clean, "{:.0f}%"),
                ])
                apply_chart_animation(fig_hs)
                st.plotly_chart(fig_hs, use_container_width=True)

        with c2:
            if not has_ppl:
                st.markdown(
                    f"<div style='background:#F8FAFC;border:1px dashed #D1D9E0;"
                    f"border-radius:10px;padding:26px 18px;text-align:center;"
                    f"color:#6B7280;font-size:12.5px;margin-bottom:16px'>"
                    f"📋 <b>Female Representation</b><br>"
                    f"No people &amp; governance data found for {company}. "
                    f"Submit via Submit Data → Section 8.</div>",
                    unsafe_allow_html=True)
            else:
                fem_emp_clean = [v if v is not None else 0 for v in fem_emp]
                fem_bod_clean = [v if v is not None else 0 for v in fem_bod]
                _y_max = max(max((v for v in fem_bod_clean if v), default=40) + 10, 40)
                fig_ppl = go.Figure()
                fig_ppl.add_trace(go.Bar(
                    x=xi, y=fem_emp_clean, name="% Women Employees",
                    marker_color=BAR_BLUE, marker_line_width=0, width=0.35, offset=-0.2,
                    text=[f"{v:.0f}%" if v else "" for v in fem_emp_clean],
                    textposition="inside", textfont=dict(size=9, color="white", family=FONT_FAM),
                    customdata=ys_str,
                    hovertemplate="<b>%{customdata}</b><br>Women employees: %{y:.0f}%<extra></extra>",
                ))
                fig_ppl.add_trace(go.Bar(
                    x=xi, y=fem_bod_clean, name="% Women on Board",
                    marker_color=LINE_AMBER, marker_line_width=0, width=0.35, offset=0.2,
                    text=[f"{v:.0f}%" if v else "" for v in fem_bod_clean],
                    textposition="inside", textfont=dict(size=9, color="white", family=FONT_FAM),
                    customdata=ys_str,
                    hovertemplate="<b>%{customdata}</b><br>Women on Board: %{y:.0f}%<extra></extra>",
                ))
                lay_ppl = _chart_base("Female Representation (%)", height=380, bottom=80)
                lay_ppl["xaxis"]["tickvals"] = xi
                lay_ppl["xaxis"]["ticktext"] = ys_str
                lay_ppl["yaxis"].update(range=[0, _y_max], ticksuffix="%",
                                        title=dict(text="Female Representation (%)", font=dict(size=11, color=AXIS_COL)))
                lay_ppl["margin"] = dict(l=60, r=40, t=50, b=100)
                fig_ppl.update_layout(**lay_ppl)
                _annot_below(fig_ppl, xi, [
                    ("Women Emp. %", fem_emp_clean, "{:.0f}%"),
                    ("Women Board %", fem_bod_clean, "{:.0f}%"),
                ])
                apply_chart_animation(fig_ppl)
                st.plotly_chart(fig_ppl, use_container_width=True)

    # ── Historical KPI summary table ───────────────────────────────────────────
    st.markdown('<div style="height:8px"></div>', unsafe_allow_html=True)
    st.markdown(f"**Historical KPI Summary — {company}**")

    tbl_rows = []
    table_years = sorted([y for y in years if y >= 2014], reverse=True)
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