"""
pages/page_reports.py — PDF report generation (executive one-pager + benchmarking report).
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
from components.render_template_table import render_template_table
from components.render_electricity_tab import render_electricity_tab
from components.render_waste_tab import render_waste_tab
from components.render_people_tab import _render_people_governance_tab
from components.render_qualitative_tab import render_qualitative_tab
from components.render_conversion_tab import render_conversion_tab


def page_reports():
    """
    Sustainability Report — one-page CSR report with company summary,
    KPI tables, trend charts, benchmarking position. Download as PDF.
    """
    from pdf.pdf_report import generate_executive_pdf, build_kpi_dict_from_outputs, REPORTLAB_OK
    from datetime import date as _date

    company   = st.session_state.user_company
    comp_hist = dl.get_company_hist(state.CONSOLIDATED_DF, company)
    years     = sorted(dl.get_years(state.CONSOLIDATED_DF, company) or [state.CURR_YEAR])
    years_str = [str(y) for y in years]   # string labels for Plotly x-axis

    # ── Header with Download button top-right ─────────────────────────────────
    hdr_col, btn_col = st.columns([3, 1])
    with hdr_col:
        st.markdown(f"## {company}")
        st.caption("TIP ESG Sustainability Report · Tire Industry Project")
    with btn_col:
        if years:
            sel_yr = st.selectbox("Year", sorted(years, reverse=True),
                                  key="rpt_year_sel", label_visibility="collapsed")
        else:
            sel_yr = state.CURR_YEAR

    # ── Load data ─────────────────────────────────────────────────────────────
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

    kpi_dict = build_kpi_dict_from_outputs(inp, out, prev_out)
    rt       = max(inp.renew_elec_purchased + inp.nonrenew_elec_purchased + inp.self_gen_elec, 1)
    renew_pct = inp.renew_elec_purchased / rt * 100

    # ── Pre-compute historical table (needed by both PDF and web view) ────────
    from formula_engine import TemplateInputs as TI, calculate as calc
    valid = {f.name for f in TI.__dataclass_fields__.values()}
    tbl_yrs = sorted([y for y in years if y <= sel_yr and y >= sel_yr - 9], reverse=True)
    tbl_rows = []
    for y in tbl_yrs:
        sd_t = dl.get_step_data(comp_hist, y)
        sc_t = {k: v for k, v in sd_t.items() if k in valid}
        if not sc_t: continue
        o_t  = calc(TI(company=company, year=y, **sc_t))
        ii_t = TI(company=company, year=y, **sc_t)
        rt2  = max(ii_t.renew_elec_purchased + ii_t.nonrenew_elec_purchased + ii_t.self_gen_elec, 1)
        tbl_rows.append({
            "Year":              y,
            "Production (M T)":  f"{ii_t.production/1e6:.2f}",
            "CO₂ Total (T)":     f"{o_t.total_co2:,.0f}",
            "CO₂ Intensity":     f"{o_t.co2_kpi:.3f}",
            "Energy KPI (GJ/t)": f"{o_t.energy_kpi:.2f}",
            "Renew. Elec. %":    f"{ii_t.renew_elec_purchased/rt2*100:.1f}%",
            "Water KPI (m³/t)":  f"{o_t.water_kpi:.2f}",
            "Waste Recovery %":  f"{o_t.waste_recovery_pct*100:.1f}%",
        })

    # CO₂ trend for last 5 years
    trend_yrs  = sorted([y for y in years if y <= sel_yr])[-5:]
    co2_trend  = []
    for ty in trend_yrs:
        sd = dl.get_step_data(comp_hist, ty)
        sc = {k: v for k, v in sd.items() if k in valid}
        co2_trend.append(calc(TI(company=company, year=ty, **sc)).co2_kpi)

    # Generate PDF using matplotlib — matches the web page content
    import sys as _sys, os as _os
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
    pdf_bytes = None
    try:
        import pdf.pdf_charts_v2 as pc
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units    import mm
        from reportlab.pdfgen       import canvas as rl_canvas
        from reportlab.lib.utils    import ImageReader
        import io as _io

        W, H = A4; MARGIN = 12*mm; CW = W - 2*MARGIN
        buf2 = _io.BytesIO()
        cv   = rl_canvas.Canvas(buf2, pagesize=A4)

        # --- Cover band ---
        cv.setFillColor((10/255, 34/255, 64/255))
        cv.rect(0, H - 30*mm, W, 30*mm, fill=1, stroke=0)
        cv.setFont("Helvetica-Bold", 15)
        cv.setFillColor((1,1,1))
        cv.drawString(MARGIN, H - 13*mm, company)
        cv.setFont("Helvetica", 9); cv.setFillColor((0.55,0.65,0.75))
        cv.drawString(MARGIN, H - 20*mm, f"TIP ESG Sustainability Performance Report  ·  {sel_yr}")
        cv.setFont("Helvetica-Bold", 7); cv.setFillColor((0.3,0.9,0.4))
        cv.drawString(W - MARGIN - 55, H - 15*mm, "dss+ Verified Standard")
        cv.setFont("Helvetica-Bold", 28); cv.setFillColor((1,1,1))
        cv.drawRightString(W - MARGIN, H - 17*mm, str(sel_yr))

        cursor = H - 34*mm

        def _embed_img(img_bytes, h=55*mm, w=None):
            nonlocal cursor
            if cursor - h < MARGIN + 5*mm:
                cv.showPage(); cursor = H - MARGIN
            reader = ImageReader(_io.BytesIO(img_bytes))
            use_w = w or CW
            cv.drawImage(reader, MARGIN, cursor - h, width=use_w, height=h, preserveAspectRatio=True)
            cursor -= h + 4*mm

        def _section_hdr(title, subtitle, color=(10/255,34/255,64/255)):
            nonlocal cursor
            cv.setFillColor((0.96, 0.97, 0.99))
            cv.rect(MARGIN, cursor - 10*mm, CW, 10*mm, fill=1, stroke=0)
            cv.setFillColor(color)
            cv.rect(MARGIN, cursor - 10*mm, 2.5, 10*mm, fill=1, stroke=0)
            cv.setFont("Helvetica-Bold", 9); cv.setFillColor(color)
            cv.drawString(MARGIN + 5, cursor - 6*mm, title)
            cv.setFont("Helvetica", 7); cv.setFillColor((0.4,0.4,0.4))
            cv.drawString(MARGIN + 5, cursor - 9*mm, subtitle)
            cursor -= 12*mm

        # --- 6 KPI cards row ---
        kpi_card_data = [
            ("CO₂ Intensity",     f"{out.co2_kpi:.3f}", "tCO₂/t"),
            ("Renewable Elec.",   f"{renew_pct:.1f}",   "%"),
            ("Water Intensity",   f"{out.water_kpi:.2f}","m³/t"),
            ("Waste Recovery",    f"{out.waste_recovery_pct*100:.1f}","%"),
            ("Energy Intensity",  f"{out.energy_kpi:.2f}","GJ/t"),
            ("Production",        f"{inp.production/1e6:.2f}","M T"),
        ]
        card_w = CW / 6; card_h = 18*mm
        if cursor - card_h < MARGIN: cv.showPage(); cursor = H - MARGIN
        for j, (lbl, val, unit) in enumerate(kpi_card_data):
            cx = MARGIN + j * card_w
            cv.setFillColor((0.97, 0.98, 1.0))
            cv.roundRect(cx, cursor - card_h, card_w - 1, card_h, 2, fill=1, stroke=0)
            cv.setFillColor((0.4, 0.45, 0.5))
            cv.setFont("Helvetica", 6); cv.drawCentredString(cx + card_w/2, cursor - 5*mm, lbl.upper())
            cv.setFont("Helvetica-Bold", 11); cv.setFillColor((0.06, 0.13, 0.25))
            cv.drawCentredString(cx + card_w/2, cursor - 10*mm, val)
            cv.setFont("Helvetica", 6); cv.setFillColor((0.5, 0.5, 0.5))
            cv.drawCentredString(cx + card_w/2, cursor - 14*mm, unit)
        cursor -= card_h + 6*mm

        # --- Section 1: Environmental ---
        _section_hdr("1.  Environmental Performance",
                     "CO₂ emissions, energy consumption and climate targets")

        # Build data for charts
        all_hist = {}
        for y_h in years:
            sd_h = dl.get_step_data(comp_hist, y_h)
            sc_h = {k: v for k,v in sd_h.items() if k in valid}
            if not sc_h: continue
            o_h  = calc(TI(company=company, year=y_h, **sc_h))
            ii_h = TI(company=company, year=y_h, **sc_h)
            rt_h = max(ii_h.renew_elec_purchased + ii_h.nonrenew_elec_purchased + ii_h.self_gen_elec, 1)
            all_hist[y_h] = {"co2": o_h.total_co2, "nat_gas": ii_h.nat_gas,
                              "coal": ii_h.coal_sub, "diesel": ii_h.diesel,
                              "renew_gj": ii_h.renew_elec_purchased,
                              "nonrenew_gj": ii_h.nonrenew_elec_purchased,
                              "biomass": ii_h.biomass, "water_m3": ii_h.water_withdrawals,
                              "waste_pct": o_h.waste_recovery_pct*100}
        hy = sorted(all_hist.keys())

        # CO₂ + energy mix side by side
        if hy:
            img_co2 = pc.area_line(hy, [all_hist[y]["co2"] for y in hy],
                                   "Total CO₂ Emissions (tCO₂)", color=pc.C["co2"])
            img_nrg = pc.stacked_bar(hy[-8:], {
                "Nat. Gas": [all_hist[y]["nat_gas"]    for y in hy[-8:]],
                "Renew.":   [all_hist[y]["renew_gj"]   for y in hy[-8:]],
                "Diesel":   [all_hist[y]["diesel"]      for y in hy[-8:]],
                "Coal":     [all_hist[y]["coal"]        for y in hy[-8:]],
            }, "Energy Mix by Source (GJ)",
            color_dict={"Nat. Gas":pc.C["energy"],"Renew.":pc.C["green"],
                        "Diesel":"#78716C","Coal":"#475569"})

            half_w = CW / 2 - 2*mm
            h_img  = 52*mm
            if cursor - h_img < MARGIN: cv.showPage(); cursor = H - MARGIN
            cv.drawImage(ImageReader(_io.BytesIO(img_co2)),
                         MARGIN, cursor-h_img, width=half_w, height=h_img, preserveAspectRatio=True)
            cv.drawImage(ImageReader(_io.BytesIO(img_nrg)),
                         MARGIN+half_w+2*mm, cursor-h_img, width=half_w, height=h_img, preserveAspectRatio=True)
            cursor -= h_img + 5*mm

        # --- Section 2: Resource Efficiency ---
        _section_hdr("2.  Resource Efficiency",
                     "Water withdrawals, waste management and circular economy",
                     color=(0.03,0.35,0.43))
        if hy:
            img_wat = pc.bar_chart(hy, [all_hist[y]["water_m3"]/1e6 for y in hy],
                                   "Water Withdrawals (M m³)", "M m³", color=pc.C["water"])
            img_wst = pc.area_with_target(hy, [all_hist[y]["waste_pct"] for y in hy],
                                          "Waste Recovery Rate (%)", "%",
                                          color=pc.C["waste"])
            h_img = 52*mm
            if cursor - h_img < MARGIN: cv.showPage(); cursor = H - MARGIN
            cv.drawImage(ImageReader(_io.BytesIO(img_wat)),
                         MARGIN, cursor-h_img, width=half_w, height=h_img, preserveAspectRatio=True)
            cv.drawImage(ImageReader(_io.BytesIO(img_wst)),
                         MARGIN+half_w+2*mm, cursor-h_img, width=half_w, height=h_img, preserveAspectRatio=True)
            cursor -= h_img + 5*mm

        # --- Section 3: Historical table ---
        _section_hdr("3.  Historical Performance Data",
                     f"{max(tbl_yrs[-1] if tbl_rows else sel_yr-9, sel_yr-9)}–{sel_yr}",
                     color=(0.09,0.32,0.09))
        if tbl_rows:
            cv.setFont("Helvetica-Bold", 7); cv.setFillColor((0.06,0.13,0.25))
            headers = list(tbl_rows[0].keys())
            col_w   = CW / len(headers)
            row_h   = 5.5*mm
            # header row
            if cursor - row_h < MARGIN: cv.showPage(); cursor = H - MARGIN
            cv.setFillColor((0.94,0.95,0.98))
            cv.rect(MARGIN, cursor-row_h, CW, row_h, fill=1, stroke=0)
            for j, h_txt in enumerate(headers):
                cv.setFont("Helvetica-Bold", 6); cv.setFillColor((0.3,0.35,0.4))
                cv.drawCentredString(MARGIN + (j+0.5)*col_w, cursor-4*mm, str(h_txt)[:12])
            cursor -= row_h
            for ri, row in enumerate(tbl_rows):
                if cursor - row_h < MARGIN: cv.showPage(); cursor = H - MARGIN
                if ri % 2 == 0:
                    cv.setFillColor((0.975,0.978,0.985))
                    cv.rect(MARGIN, cursor-row_h, CW, row_h, fill=1, stroke=0)
                for j, col_name in enumerate(headers):
                    cv.setFont("Helvetica", 6)
                    cv.setFillColor((0.15,0.15,0.2) if j==0 else (0.35,0.38,0.42))
                    cv.drawCentredString(MARGIN+(j+0.5)*col_w, cursor-4*mm, str(row.get(col_name,""))[:10])
                cursor -= row_h

        # --- Footer ---
        cv.setFillColor((0.95,0.96,0.98))
        cv.rect(0, 0, W, 12*mm, fill=1, stroke=0)
        cv.setFont("Helvetica", 6); cv.setFillColor((0.4,0.4,0.4))
        cv.drawString(MARGIN, 5*mm,
            "Methodology: GHG Protocol (Scope 1+2) · TIP KPI definitions v3.1 · IEA 2023 emission factors")
        from datetime import date as _ddate
        cv.drawRightString(W-MARGIN, 5*mm,
            f"Generated {_ddate.today().strftime('%d %b %Y')} · TIP ESG Platform by dss+")

        cv.save(); buf2.seek(0); pdf_bytes = buf2.read()
    except Exception as _e:
        pdf_bytes = None
        st.warning(f"PDF generation error: {_e}")
    filename = f"{company.replace(' ','_')}_Sustainability_Report_{sel_yr}.pdf"
    with btn_col:
        if pdf_bytes:
            st.download_button("⬇ Download PDF", data=pdf_bytes, file_name=filename,
                               mime="application/pdf", type="primary",
                               use_container_width=True)
        else:
            st.button("⬇ Download PDF", disabled=True, use_container_width=True)

    st.divider()

    # ══════════════════════════════════════════════════════════════════════════
    # REPORT BODY — styled as a professional one-page CSR report
    # ══════════════════════════════════════════════════════════════════════════

    # ── Cover band ────────────────────────────────────────────────────────────
    st.markdown(f"""
    <div style="background:linear-gradient(135deg,#0A2240 0%,#164E63 100%);
        border-radius:12px;padding:28px 32px;margin-bottom:20px;
        display:flex;justify-content:space-between;align-items:center">
      <div>
        <div style="color:rgba(255,255,255,.5);font-size:11px;font-weight:500;
            text-transform:uppercase;letter-spacing:.8px;margin-bottom:6px">
          TIP ESG Platform · Tire Industry Project
        </div>
        <div style="color:#fff;font-size:28px;font-weight:800;letter-spacing:-.5px;
            margin-bottom:4px">{_html.escape(company)}</div>
        <div style="color:rgba(255,255,255,.6);font-size:14px">
          Sustainability Performance Report · {sel_yr}
        </div>
      </div>
      <div style="text-align:right">
        <div style="color:rgba(255,255,255,.4);font-size:10px;text-transform:uppercase">
          Reporting Year</div>
        <div style="color:#fff;font-size:52px;font-weight:800;line-height:1">
          {sel_yr}</div>
        <div style="color:{GREEN};font-size:11px;font-weight:600;margin-top:4px">
          ● dss+ Verified Standard</div>
      </div>
    </div>""", unsafe_allow_html=True)

    # ── Executive Summary ──────────────────────────────────────────────────────
    def _yoy_str(cur, prev_val, lower=True):
        if not prev_val or prev_val == 0: return ""
        pct = (cur - prev_val) / abs(prev_val) * 100
        good = pct <= 0 if lower else pct >= 0
        arrow = "▼" if pct < 0 else "▲"
        col   = GREEN if good else RED
        return f'<span style="color:{col};font-size:11px;font-weight:600">{arrow} {abs(pct):.1f}%</span>'

    co2_yoy    = _yoy_str(out.co2_kpi,    prev_out.co2_kpi if prev_out else None)
    energy_yoy = _yoy_str(out.energy_kpi, prev_out.energy_kpi if prev_out else None)
    water_yoy  = _yoy_str(out.water_kpi,  prev_out.water_kpi if prev_out else None)
    waste_yoy  = _yoy_str(out.waste_recovery_pct, prev_out.waste_recovery_pct if prev_out else None, lower=False)

    kpi_summary = [
        ("CO₂ Intensity",     f"{out.co2_kpi:.3f}",           "tCO₂/t", co2_yoy,    CAT_CO2),
        ("Renewable Elec.",   f"{renew_pct:.1f}",              "%",       "",          CAT_RENEW),
        ("Water Intensity",   f"{out.water_kpi:.2f}",          "m³/t",    water_yoy,  CAT_WATER),
        ("Waste Recovery",    f"{out.waste_recovery_pct*100:.1f}","%",    waste_yoy,  CAT_WASTE),
        ("Energy Intensity",  f"{out.energy_kpi:.2f}",         "GJ/t",    energy_yoy, CAT_ENERGY),
        ("Production",        f"{inp.production/1e6:.2f}",     "M T",     "",          NAVY),
    ]
    kpi_cols = st.columns(6)
    for i, (label, val, unit, yoy_h, color) in enumerate(kpi_summary):
        with kpi_cols[i]:
            st.markdown(f"""
            <div style="background:#fff;border:1px solid {BORDER};border-radius:8px;
                padding:10px 8px;text-align:center;
                height:90px;display:flex;flex-direction:column;
                justify-content:space-between;align-items:center;
                animation:tipFadeIn 400ms ease-out {i*50}ms both">
              <div style="font-size:9px;color:{MUTED};text-transform:uppercase;
                  letter-spacing:.5px;font-weight:600">{label}</div>
              <div style="font-size:19px;font-weight:800;color:{color};
                  font-variant-numeric:tabular-nums;line-height:1">{val}</div>
              <div style="font-size:9px;color:{MUTED}">{unit}</div>
              <div style="margin-top:2px;min-height:14px">{yoy_h}</div>
            </div>""", unsafe_allow_html=True)

    st.markdown('<div style="height:16px"></div>', unsafe_allow_html=True)

    # ── Section 1: Environmental Performance ─────────────────────────────────
    st.markdown(f"""
    <div style="border-left:3px solid {CAT_CO2};padding:4px 0 4px 12px;margin-bottom:12px">
      <div style="font-size:14px;font-weight:700;color:{TEXT}">
        1. Environmental Performance</div>
      <div style="font-size:11px;color:{MUTED}">
        CO₂ emissions, energy consumption and climate targets</div>
    </div>""", unsafe_allow_html=True)

    r1c1, r1c2 = st.columns(2, gap="medium")
    with r1c1:
        # CO₂ trend
        co2_all = []
        for y in years:
            sd = dl.get_step_data(comp_hist, y)
            sc = {k: v for k, v in sd.items() if k in valid}
            if sc: co2_all.append((y, calc(TI(company=company, year=y, **sc)).total_co2))
        if co2_all:
            ys_c, vals_c = zip(*co2_all)
            fig_co2 = go.Figure()
            fig_co2.add_trace(go.Scatter(
                x=list(ys_c), y=list(vals_c), mode="lines+markers",
                fill="tozeroy", fillcolor="rgba(71,85,105,0.08)",
                line=dict(color=CAT_CO2, width=2.5),
                marker=dict(size=6, color=CAT_CO2),
                hovertemplate="<b>%{x}</b>: %{y:,.0f} tCO₂<extra></extra>",
            ))
            fig_co2.update_layout(**chart_layout_defaults("Total CO₂ Emissions (tCO₂)", height=220,
                                                           showlegend=False),
                                   yaxis=dict(tickformat=",", gridcolor="#e6eaed", showline=True, linecolor="#9aa1a9",
                                            tickfont=dict(size=12, color="#6f7882")))
            apply_chart_animation(fig_co2)
            st.plotly_chart(fig_co2, use_container_width=True)

    with r1c2:
        # Energy mix stacked bar
        fuel_data = [(y, dl.get_step_data(comp_hist, y)) for y in years[-8:]]
        if fuel_data:
            fig_nrg = go.Figure()
            fuel_keys = [("Nat. Gas","nat_gas",CAT_ENERGY),
                         ("Coal","coal_sub","#475569"),
                         ("Diesel","diesel","#78716C"),
                         ("Renew. Elec","renew_elec_purchased",CAT_RENEW)]
            for lbl, fkey, fcol in fuel_keys:
                vals = [sd.get(fkey, 0) for _, sd in fuel_data]
                if any(v>0 for v in vals):
                    fig_nrg.add_trace(go.Bar(
                        x=[y for y,_ in fuel_data], y=vals,
                        name=lbl, marker_color=fcol, marker_line_width=0,
                        hovertemplate=f"<b>{lbl}</b>: %{{y:,.0f}} GJ<extra></extra>",
                    ))
            fig_nrg.update_layout(**chart_layout_defaults("Energy Mix by Source (GJ)", height=220),
                                   barmode="stack", bargap=0.2,
                                   yaxis=dict(tickformat=",", gridcolor="#e6eaed", showline=True, linecolor="#9aa1a9",
                                            tickfont=dict(size=12, color="#6f7882")))
            apply_chart_animation(fig_nrg)
            st.plotly_chart(fig_nrg, use_container_width=True)

    # ── Section 2: Resource Efficiency ────────────────────────────────────────
    st.markdown(f"""
    <div style="border-left:3px solid {CAT_WATER};padding:4px 0 4px 12px;margin-bottom:12px">
      <div style="font-size:14px;font-weight:700;color:{TEXT}">
        2. Resource Efficiency</div>
      <div style="font-size:11px;color:{MUTED}">
        Water withdrawals, waste management and circular economy</div>
    </div>""", unsafe_allow_html=True)

    r2c1, r2c2 = st.columns(2, gap="medium")
    with r2c1:
        water_vals = [(y, dl.get_step_data(comp_hist,y).get("water_withdrawals",0)) for y in years]
        if water_vals:
            ys_w, vals_w = zip(*water_vals)
            fig_wat = go.Figure(go.Bar(
                x=list(ys_w), y=[v/1e6 for v in vals_w],
                marker_color=CAT_WATER, marker_line_width=0, opacity=0.85,
                hovertemplate="<b>%{x}</b>: %{y:.2f} M m³<extra></extra>",
            ))
            fig_wat.update_layout(**chart_layout_defaults("Water Withdrawals (M m³)", height=200,
                                                           showlegend=False),
                                   yaxis=dict(gridcolor="#e6eaed"))
            apply_chart_animation(fig_wat)
            st.plotly_chart(fig_wat, use_container_width=True)

    with r2c2:
        waste_rec_vals = []
        for y in years:
            sd = dl.get_step_data(comp_hist, y)
            sc = {k: v for k, v in sd.items() if k in valid}
            if sc:
                o = calc(TI(company=company, year=y, **sc))
                waste_rec_vals.append((y, o.waste_recovery_pct*100))
        if waste_rec_vals:
            ys_wr, vals_wr = zip(*waste_rec_vals)
            fig_wr = go.Figure()
            fig_wr.add_hline(y=90, line_dash="dot", line_color=GREEN,
                             line_width=1.5, annotation_text="Target 90%",
                             annotation_font=dict(size=9, color=GREEN))
            fig_wr.add_trace(go.Scatter(
                x=list(ys_wr), y=list(vals_wr), mode="lines+markers",
                fill="tozeroy", fillcolor="rgba(124,58,237,0.08)",
                line=dict(color=CAT_WASTE, width=2.5),
                marker=dict(size=6, color=CAT_WASTE),
                hovertemplate="<b>%{x}</b>: %{y:.1f}%<extra></extra>",
            ))
            fig_wr.update_layout(**chart_layout_defaults("Waste Recovery Rate (%)", height=200,
                                                          showlegend=False),
                                  yaxis=dict(range=[0, 105], ticksuffix="%", gridcolor="#e6eaed"))
            apply_chart_animation(fig_wr)
            st.plotly_chart(fig_wr, use_container_width=True)

    # ── Section 3: Historical KPI Table ───────────────────────────────────────
    st.markdown(f"""
    <div style="border-left:3px solid {GREEN};padding:4px 0 4px 12px;margin-bottom:12px">
      <div style="font-size:14px;font-weight:700;color:{TEXT}">
        3. Historical Performance Data ({max(years)-9 if len(years)>=10 else min(years)}–{sel_yr})</div>
    </div>""", unsafe_allow_html=True)

    # tbl_rows already computed above (before PDF generation)
    if tbl_rows:
        tbl_df = pd.DataFrame(tbl_rows)
        st.dataframe(
            tbl_df.style
                .set_properties(**{"text-align":"right","font-size":"12px"})
                .set_table_styles([
                    {"selector":"th","props":[
                        ("font-size","10px"),("text-transform","uppercase"),
                        ("letter-spacing",".4px"),("color","#64748B"),
                        ("background","#F8FAFC"),("padding","8px 12px")]},
                    {"selector":"td:first-child","props":[
                        ("font-weight","600"),("color","#0F172A"),
                        ("text-align","center")]},
                ]),
            use_container_width=True, hide_index=True,
        )

    # ── Footer ────────────────────────────────────────────────────────────────
    st.markdown(f"""
    <div style="background:#F8FAFC;border-radius:8px;padding:12px 20px;margin-top:16px;
        display:flex;justify-content:space-between;align-items:center;
        border:1px solid {BORDER}">
      <div style="font-size:11px;color:{MUTED}">
        Methodology: GHG Protocol (Scope 1+2) · TIP KPI definitions v3.1 ·
        Emission factors: IEA 2023</div>
      <div style="font-size:11px;color:{MUTED}">
        Generated {_date.today().strftime('%d %b %Y')} · TIP ESG Platform powered by dss+</div>
    </div>""", unsafe_allow_html=True)