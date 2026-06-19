"""
components/render_template_table.py — KPI template table with Comments column.
Used by both page_my_records (client) and page_company_data (DSS).
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
import html as _html
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


def render_template_table():
    company  = st.session_state.get("reporting_company") or st.session_state.get("user_company") or "TIP Member Company"
    if company == "All Companies": company = "TIP Member Company"
    rep_year = st.session_state.get("reporting_year", state.CURR_YEAR)
    # Always reload from state.CONSOLIDATED_DF so updates to any year are visible
    _hist    = _get_fresh_hist(company)

    st.markdown(f"""
    <div style="display:flex;align-items:center;justify-content:space-between;
        background:#fff;border:1px solid #E5E7EB;border-radius:10px;
        padding:18px 24px;margin-bottom:14px">
      <div>
        <div style="font-size:17px;font-weight:700;color:#0A2240;letter-spacing:-.2px">
          Tire Industry Project — Key Performance Indicators
        </div>
        <div style="font-size:26px;font-weight:800;color:#00916E;margin-top:5px;letter-spacing:-.4px">
          {_html.escape(company)}
        </div>
        <div style="font-size:12px;color:#9CA3AF;margin-top:4px">Corporate units · ESG KPI Template — {rep_year}</div>
      </div>
      <div style="text-align:right">
        <div style="font-size:11px;color:#6B7280;text-transform:uppercase;letter-spacing:.5px">Reporting year</div>
        <div style="font-size:36px;font-weight:800;color:#0A2240;line-height:1">{rep_year}</div>
        <div style="font-size:11px;color:#9CA3AF;margin-top:3px">Data range: 2009–{rep_year}</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    st.info("Template generated from your inputs. Blue cells = company input, grey italic = auto-calculated formula.")

    # ── Data sources — all from state.CONSOLIDATED_DF so saves are immediately visible ──
    hist = get_hist_outputs()   # ALL years including current year

    # For the current reporting year prefer _codata_inp (freshest — set right after save)
    if (st.session_state.get("_codata_inp") is not None and
            getattr(st.session_state["_codata_inp"], "year", None) == rep_year):
        inp = st.session_state["_codata_inp"]
        out = st.session_state["_codata_out"]
    else:
        inp, out = _load_company_year_outputs(company, rep_year)

    # Always ensure current year is in hist with the freshest values
    hist = sorted(
        [(yr, hi, ho) for yr, hi, ho in hist if yr != rep_year] + [(rep_year, inp, out)],
        key=lambda t: t[0],
    )
    # Year-keyed lookup — used below to find rep_year-1 reliably even when
    # padding years (no data yet) sit after it in the chronological list.
    hist_by_yr = {yr: (hi, ho) for yr, hi, ho in hist}

    ROWS = [
        ("section","ISO 14001",None,None,None),
        ("input","Total no. of sites","no.","total_sites",None),
        ("input","ISO 14001 certified sites","no.","iso_sites",None),
        ("calc","% certified sites","%",None,lambda i,o:f"{o.pct_certified*100:.1f}%"),
        ("section","Production",None,None,None),
        ("input","Production","metric t","production",None),
        ("section","Water",None,None,None),
        ("input","Water withdrawals","m³","water_withdrawals",None),
        ("supp","Stress water withdrawal","m³","stress_water_withdrawal",None),
        ("supp","Non-stress water withdrawal","m³","non_stress_water_withdrawal",None),
        ("calc","Water intensity KPI","m³/t",None,lambda i,o:f"{o.water_kpi:.2f}"),
        ("section","Energy",None,None,None),
        ("calc","Total Electricity","GJ",None,lambda i,o:f"{o.total_electricity:,.0f}"),
        ("input","— Renewable electricity purchased","GJ","renew_elec_purchased",None),
        ("input","— Non-renewable electricity purchased","GJ","nonrenew_elec_purchased",None),
        ("input","— Self-generated renewable on-site","GJ","self_gen_elec",None),
        ("input","Purchased Steam","GJ","purchased_steam",None),
        ("input","Sold Electricity","GJ","sold_electricity",None),
        ("input","Sold Steam","GJ","sold_steam",None),
        ("input","Natural Gas","GJ LHV","nat_gas",None),
        ("input","Coal (all types)","GJ LHV","coal_sub",None),
        ("supp","— Sub-bituminous coal","GJ LHV","coal_sub_bituminous",None),
        ("supp","— Brown coal briquettes","GJ LHV","coal_brown_briquettes",None),
        ("supp","— Other bituminous coal","GJ LHV","coal_other_bituminous",None),
        ("input","Propane","GJ LHV","propane",None),
        ("input","Fuel Oil","GJ LHV","fuel_oil_heavy_a",None),
        ("input","Diesel","GJ LHV","diesel",None),
        ("input","Petrol","GJ LHV","petrol",None),
        ("input","Biomass","GJ LHV","biomass",None),
        ("input","Waste tires","metric t","waste_tires_mt",None),
        ("input","LPG","GJ LHV","lpg",None),
        ("input","Other fuels","GJ LHV","other_fuels",None),
        ("calc","TOTAL ENERGY","GJ",None,lambda i,o:f"{o.total_energy:,.0f}"),
        ("calc","Energy intensity KPI","GJ/t",None,lambda i,o:f"{o.energy_kpi:.2f}"),
        ("section","CO2 Emissions",None,None,None),
        ("input","Scope 2 — Steam","T.CO2","co2_scope2_steam",None),
        ("calc","CO2 — Natural Gas","T.CO2",None,lambda i,o:f"{o.co2_nat_gas:,.0f}"),
        ("calc","CO2 — Coal","T.CO2",None,lambda i,o:f"{o.co2_coal:,.0f}"),
        ("calc","CO2 — Propane","T.CO2",None,lambda i,o:f"{o.co2_propane:,.0f}"),
        ("calc","CO2 — Fuel Oil","T.CO2",None,lambda i,o:f"{o.co2_fuel_oil:,.0f}"),
        ("calc","CO2 — Diesel","T.CO2",None,lambda i,o:f"{o.co2_diesel:,.0f}"),
        ("calc","CO2 — Petrol","T.CO2",None,lambda i,o:f"{o.co2_petrol:,.0f}"),
        ("calc","CO2 — LPG","T.CO2",None,lambda i,o:f"{o.co2_lpg:,.0f}"),
        ("calc","TOTAL CO2 Scope 1","T.CO2",None,lambda i,o:f"{o.total_co2_scope1:,.0f}"),
        ("calc","TOTAL CO2 Scope 2","T.CO2",None,lambda i,o:f"{o.total_co2_scope2:,.0f}"),
        ("calc","TOTAL CO2 (S1+S2)","T.CO2",None,lambda i,o:f"{o.total_co2:,.0f}"),
        ("calc","CO2 intensity KPI","T.CO2/T",None,lambda i,o:f"{o.co2_kpi:.3f}"),
        ("section","Waste",None,None,None),
        ("input","Total waste generated","metric t","waste_total",None),
        ("input","Waste sent to recovery","metric t","waste_recovery",None),
        ("calc","Waste sent to elimination","metric t",None,lambda i,o:f"{o.waste_elimination:,.0f}"),
        ("calc","Recovery rate","%",None,lambda i,o:f"{o.waste_recovery_pct*100:.1f}%"),
        ("calc","Waste intensity KPI","kg/T",None,lambda i,o:f"{i.waste_total/i.production*1000:.1f}" if i.production else "—"),
    ]

    _all_cmts = _get_all_active_comments(company, rep_year)

    data = []
    for rdef in ROWS:
        rtype, label, unit, key, fn = rdef
        if rtype == "section":
            row = {"Indicator": f"▸ {label}", "Unit": ""}
            for yr, hi, ho in hist: row[str(yr)] = ""
            row["YoY %"] = ""
            row["Comments"] = ""
            data.append({"_type": "section", "_row": row, "_key": "", "_label": label})
            continue

        row = {"Indicator": label, "Unit": unit or ""}
        prev_num = None
        for yr, hi, ho in hist:
            # supp rows read from master CSV supplementary columns
            if rtype == "supp" and key:
                yr_supp = _load_supplementary(company, yr)
                v = yr_supp.get(key, None)
                # also check master CSV columns (after migration)
                if v is None:
                    _mrow = state.CONSOLIDATED_DF[
                        (state.CONSOLIDATED_DF.get("Company","") == company) &
                        (state.CONSOLIDATED_DF.get("Year","") == yr)
                    ] if not state.CONSOLIDATED_DF.empty and "Company" in state.CONSOLIDATED_DF.columns else None
                    if _mrow is not None and not _mrow.empty:
                        _col_map = {
                            "stress_water_withdrawal":   "Stress Water Withdrawal",
                            "non_stress_water_withdrawal":"Non-Stress Water Withdrawal",
                            "coal_sub_bituminous":       "Coal Sub-Bituminous",
                            "coal_brown_briquettes":     "Coal Brown Briquettes",
                            "coal_other_bituminous":     "Coal Other Bituminous",
                            "hs_external_audit":         "HS External Audit Sites",
                            "hs_internal_audit":         "HS Internal Audit Sites",
                            "total_employees":           "Total Employees",
                            "female_employees":          "Female Employees",
                            "board_total":               "Board Total",
                            "female_board":              "Female Board",
                            "sbt_total":                 "SBT Total",
                            "sbt_validated":             "SBT Validated",
                            "sbt_committed":             "SBT Committed",
                            "sbt_non_committed":         "SBT Non-Committed",
                        }
                        mc = _col_map.get(key)
                        if mc and mc in _mrow.columns:
                            v = _mrow[mc].values[0]
            else:
                v = getattr(hi, key, None) if key else None
            if v is None and fn:
                v = fn(hi, ho)
            try:
                row[str(yr)] = f"{int(round(float(v))):,}"
            except (TypeError, ValueError):
                row[str(yr)] = str(v) if v else "—"
            try:
                prev_num = float(str(v).replace(",", "").replace("%", "").replace("—", "0"))
            except:
                pass

        # YoY %: compare raw floats — avoids string formatting artifacts
        def _rv(hi, ho, k, f):
            if k:
                v = getattr(hi, k, None)
                if v is not None:
                    try: return float(v)
                    except: pass
            if f:
                raw = f(hi, ho)
                try: return float(str(raw).replace(",","").replace("%","")
                                          .replace("—","0") or "0")
                except: pass
            return None
        curr_num = _rv(inp, out, key, fn)
        prev_num = None
        prev_entry = hist_by_yr.get(rep_year - 1)
        if prev_entry is not None:
            ph, po = prev_entry
            prev_num = _rv(ph, po, key, fn)
        try:
            if curr_num is not None and prev_num is not None and prev_num != 0:
                row["YoY %"] = f"{(curr_num-prev_num)/abs(prev_num)*100:+.1f}%"
            else:
                row["YoY %"] = "—"
        except:
            row["YoY %"] = "—"

        fk = key or label
        _e = _all_cmts.get(fk)
        row["Comments"] = _e[1] if _e else ""
        data.append({"_type": rtype, "_row": row, "_key": key or "", "_label": label})

    all_rows       = [d["_row"]  for d in data]
    all_types      = [d["_type"] for d in data]
    _all_keys_list = [d["_key"]  for d in data]
    df_tbl         = pd.DataFrame(all_rows)
    curr_col       = str(rep_year)

    def style_row(row, idx):
        rt  = all_types[idx]
        cmt = str(row.get("Comments", ""))
        return [
            ("background-color:#E8F5F0;color:#065F46;font-weight:800;font-size:13px;"
             "border-top:2px solid #6EE7B7;padding-top:8px;padding-bottom:8px;"
             "letter-spacing:.3px;text-transform:uppercase") if rt == "section"
            else ("color:#B91C1C;font-weight:800;font-size:11px;background:#FEF2F2"
                   if cmt and not cmt.startswith("⏳") and not cmt.startswith("⚠")
                   else "color:#92400E;font-weight:600;font-size:11px;background:#FFFBEB"
                   if cmt.startswith("⏳")
                   else "color:#C2410C;font-weight:600;font-size:11px;background:#FFF7ED"
                   if cmt.startswith("⚠")
                   else "color:#9CA3AF;font-size:11px") if col == "Comments"
            else "background-color:#DBEAFE;color:#1E40AF;font-weight:700" if (col == curr_col and rt == "input")
            else "background-color:#EFF6FF;color:#1D4ED8;font-style:italic" if (col == curr_col and rt == "calc")
            else "background-color:#F8FAFC;color:#6B7280;font-style:italic" if rt == "calc"
            else "background-color:#F0F9FF;"
            for col in df_tbl.columns
        ]

    styled     = df_tbl.style.apply(lambda row: style_row(row, row.name), axis=1)
    tbl_height = min(900, max(400, len(all_rows)*36+60))
    _cmt_ver   = len(_all_cmts)

    edited_df = st.data_editor(
        styled, hide_index=True, height=tbl_height, use_container_width=True,
        column_config={
            "Indicator": st.column_config.TextColumn(disabled=True),
            "Unit":      st.column_config.TextColumn(disabled=True),
            "YoY %":     st.column_config.TextColumn(disabled=True),
            "Comments":  st.column_config.TextColumn(
                "Comments ✏", width="medium",
                help="Type reason and press Enter → Pending. "
                     "Clear cell and press Enter → deletes comment.",
            ),
        },
        key=f"tbl_editor_{company}_{rep_year}_v{_cmt_ver}",
    )

    if edited_df is not None and "Comments" in edited_df.columns:
        actor = st.session_state.get("username", "Client")
        for idx_r, row_e in edited_df.iterrows():
            new_cmt = str(row_e.get("Comments", "")).strip()
            fk_r    = _all_keys_list[idx_r] if idx_r < len(_all_keys_list) else ""
            lbl_r   = str(row_e.get("Indicator", "unknown"))
            old_raw = (all_rows[idx_r].get("Comments", "") or "")
            for _pfx in ("⏳ ", "⚠ "): old_raw = old_raw.replace(_pfx, "")
            old_raw = old_raw.strip()
            if new_cmt == "" and old_raw:
                _delete_comment(company, rep_year, fk_r)
                _save_comment_version(company, rep_year, fk_r, old_raw, "Deleted", actor)
            elif new_cmt and new_cmt != old_raw:
                _save_change_comment(company, rep_year, fk_r, lbl_r,
                                     old_val="", new_val="", reason=new_cmt)

    st.markdown(f"""<div class="tbl-legend">
      <div class="tl"><div class="tl-sw" style="background:#F0F9FF;border-color:#BAE6FD"></div>Company input (historical)</div>
      <div class="tl"><div class="tl-sw" style="background:#DBEAFE;border-color:#93C5FD"></div>Company input ({rep_year})</div>
      <div class="tl"><div class="tl-sw" style="background:#EFF6FF;border-color:#A5B4FC"></div>Auto-calculated ({rep_year})</div>
      <div class="tl"><div class="tl-sw" style="background:#F8FAFC;border-color:#E5E7EB"></div>Auto-calculated (historical)</div>
      <div class="tl"><div class="tl-sw" style="background:#FEF2F2;border-color:#FCA5A5"></div>Change comment (Pending/⏳Seen/⚠Rejected)</div>
    </div>""", unsafe_allow_html=True)