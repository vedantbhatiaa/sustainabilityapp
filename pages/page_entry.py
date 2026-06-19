"""
pages/page_entry.py — Submit Data form (live KPI entry, all sections).
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

import html as _html
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


def page_entry():
    """
    Submit Data — full comprehensive form covering all TIP KPI fields.
    Sections: Global Info · Water · Energy (Electricity + Fuels) · CO₂ ·
              Waste · Health & Safety · Diversity · Science-Based Targets
    Auto-calculates KPIs live. On submit → saves to master CSV + supplementary
    CSV. When editing a previous year, requires a change reason which goes
    to the Verification Queue for DSS approval before becoming visible.
    """
    from pathlib import Path as _P
    from formula_engine import EF as _EF, GJ_TO_MWH as _G2M, _DEFAULT_SCOPE2_ELEC_EF as _S2EF

    company   = st.session_state.user_company
    comp_hist = dl.get_company_hist(state.CONSOLIDATED_DF, company)
    all_yrs   = sorted(dl.get_years(state.CONSOLIDATED_DF, company) or [])

    # ── Header ────────────────────────────────────────────────────────────────
    h1, h2, _ = st.columns([2, 1, 2])
    with h1:
        st.markdown(f"""<div style="font-size:22px;font-weight:800;color:{TEXT};margin-top:4px">
          {_html.escape(company)}</div>
          <div style="font-size:12px;color:{MUTED}">ESG KPI Data Entry — All TIP Fields</div>
        """, unsafe_allow_html=True)
    with h2:
        # Always offer every year from the company's first reported year (or
        # the platform current year, if they have none yet) through
        # state.CURR_YEAR + 1. CURR_YEAR is the platform-wide most recent
        # year ANY company has data for (recalculated on every save via
        # cfg.refresh_year_bounds) — so the +1 means the moment any company
        # submits e.g. 2025, every company's dropdown immediately offers 2026
        # too, without needing to touch this file again. This also fixes the
        # old bug where a company that stopped at 2023 while the platform had
        # moved on to 2025 would see "2025, 2023, 2022..." with 2024 missing
        # entirely — the old code only unioned all_yrs with the single value
        # state.CURR_YEAR, never filling the gap between them.
        lo = all_yrs[0] if all_yrs else state.CURR_YEAR
        yr_options = sorted(set(all_yrs) | set(range(lo, state.CURR_YEAR + 2)), reverse=True)
        sel_yr = st.selectbox("Year", yr_options, key="entry_year_sel",
                              label_visibility="collapsed")

    is_new = sel_yr not in all_yrs
    is_editing_prior = (not is_new) and (sel_yr < max(all_yrs + [sel_yr]))
    if is_new:
        st.info(f"📋 Entering **new data** for **{sel_yr}** — fields pre-filled from last year's projection")
    elif is_editing_prior:
        st.warning(f"✏️ Editing **existing data** for **{sel_yr}** — any changes will require a reason and DSS approval")
    else:
        st.info(f"✏️ Editing data for **{sel_yr}** (pre-filled from database)")

    # ── Pre-fill: from DB or projected ────────────────────────────────────────
    existing = dl.get_step_data(comp_hist, sel_yr) if (comp_hist and not is_new) else {}
    supp     = _load_supplementary(company, sel_yr)

    if is_new and comp_hist:
        prior_yr   = max(all_yrs) if all_yrs else sel_yr - 1
        prior_data = dl.get_step_data(comp_hist, prior_yr)
        def _num(key, default=0.0, supp_key=None):
            if supp_key:
                return float(_load_supplementary(company, prior_yr).get(supp_key, default) or default)
            return float(prior_data.get(key, default) or default)
    else:
        def _num(key, default=0.0, supp_key=None):
            if supp_key:
                return float(supp.get(supp_key, default) or default)
            return float(existing.get(key, default) or default)

    _yk = f"_{sel_yr}"     # key suffix per year avoids stale state

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 1 — Global Information
    # ══════════════════════════════════════════════════════════════════════════
    st.markdown(f"""<div style="border-left:4px solid {GREEN};padding:4px 12px;margin:16px 0 8px">
      <b style="font-size:15px;color:{TEXT}">1. Global Information</b>
      <div style="font-size:11px;color:{MUTED}">Sites, ISO 14001 certification, production volume</div>
    </div>""", unsafe_allow_html=True)

    g1, g2, g3 = st.columns(3)
    total_sites = g1.number_input("Total number of sites", min_value=0,
        value=int(_num("total_sites")), step=1, key=f"e_sites{_yk}")
    iso_sites = g2.number_input("ISO 14001 certified sites", min_value=0,
        value=int(_num("iso_sites")), step=1, key=f"e_iso{_yk}")
    iso_pct = round(iso_sites / max(total_sites, 1) * 100, 1)
    g3.metric("ISO 14001 % (auto)", f"{iso_pct:.1f}%")

    production = st.number_input("Total Production (metric t)", min_value=0.0,
        value=_num("production"), step=1000.0, format="%.0f", key=f"e_prod{_yk}")
    st.divider()

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 2 — Water
    # ══════════════════════════════════════════════════════════════════════════
    st.markdown(f"""<div style="border-left:4px solid {CAT_WATER};padding:4px 12px;margin:16px 0 8px">
      <b style="font-size:15px;color:{TEXT}">2. Water</b>
      <div style="font-size:11px;color:{MUTED}">All figures in m³</div>
    </div>""", unsafe_allow_html=True)

    w1, w2 = st.columns(2)
    water_intake = w1.number_input("Water intake (m³)", min_value=0.0,
        value=_num("water_withdrawals"), step=1000.0, format="%.0f", key=f"e_wintake{_yk}",
        help="Total water taken from all sources")
    water_withdrawal = w2.number_input("Water withdrawal (m³)", min_value=0.0,
        value=_num("water_withdrawals"), step=1000.0, format="%.0f", key=f"e_wdraw{_yk}",
        help="Total water withdrawn (may equal intake)")

    ws1, ws2 = st.columns(2)
    stress_wd = ws1.number_input("Stress water withdrawal (m³)", min_value=0.0,
        value=_num("", 0.0, "stress_water_withdrawal"), step=1000.0, format="%.0f", key=f"e_stress{_yk}",
        help="Withdrawals from water-stressed areas")
    non_stress_wd = round(max(water_withdrawal - stress_wd, 0), 0)
    ws2.metric("Non-stress withdrawal (auto)", f"{non_stress_wd:,.0f} m³")

    water_kpi_live = round(water_intake / max(production, 1), 4)
    st.metric("Water Intake KPI (m³/t)", f"{water_kpi_live:.4f}",
              help="Auto-calculated: Water intake ÷ Production")
    st.divider()

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 3 — Energy: Electricity
    # ══════════════════════════════════════════════════════════════════════════
    st.markdown(f"""<div style="border-left:4px solid {CAT_ENERGY};padding:4px 12px;margin:16px 0 8px">
      <b style="font-size:15px;color:{TEXT}">3. Energy — Electricity (GJ)</b>
    </div>""", unsafe_allow_html=True)

    ec1, ec2, ec3 = st.columns(3)
    renew_elec    = ec1.number_input("Renewable electricity purchased (GJ)", min_value=0.0,
        value=_num("renew_elec_purchased"), step=100.0, format="%.0f", key=f"e_re{_yk}")
    nonrenew_elec = ec2.number_input("Non-renewable electricity purchased (GJ)", min_value=0.0,
        value=_num("nonrenew_elec_purchased"), step=100.0, format="%.0f", key=f"e_nre{_yk}")
    self_gen      = ec3.number_input("Self-generated electricity (GJ)", min_value=0.0,
        value=_num("self_gen_elec"), step=100.0, format="%.0f", key=f"e_sg{_yk}")

    ec4, ec5, ec6 = st.columns(3)
    purchased_steam = ec4.number_input("Purchased steam (GJ)", min_value=0.0,
        value=_num("purchased_steam"), step=100.0, format="%.0f", key=f"e_ps{_yk}")
    sold_steam      = ec5.number_input("Sold steam (GJ)", min_value=0.0,
        value=_num("sold_steam"), step=100.0, format="%.0f", key=f"e_ss{_yk}",
        help="Energy sold as steam — deducted from total")
    sold_electricity = ec6.number_input("Sold electricity (GJ)", min_value=0.0,
        value=_num("sold_electricity"), step=100.0, format="%.0f", key=f"e_se{_yk}")

    total_elec = renew_elec + nonrenew_elec + self_gen
    st.metric("Total Electricity (auto)", f"{total_elec:,.0f} GJ")
    st.divider()

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 4 — Energy: Fuels
    # ══════════════════════════════════════════════════════════════════════════
    st.markdown(f"""<div style="border-left:4px solid {CAT_ENERGY};padding:4px 12px;margin:16px 0 8px">
      <b style="font-size:15px;color:{TEXT}">4. Energy — Fuels (GJ LHV unless noted)</b>
    </div>""", unsafe_allow_html=True)

    fc1, fc2, fc3 = st.columns(3)
    nat_gas  = fc1.number_input("Natural gas (GJ)", min_value=0.0,
        value=_num("nat_gas"), step=100.0, format="%.0f", key=f"e_ng{_yk}")
    propane  = fc2.number_input("Propane (GJ)", min_value=0.0,
        value=_num("propane"), step=100.0, format="%.0f", key=f"e_propane{_yk}")
    fuel_oil = fc3.number_input("Fuel oil (GJ)", min_value=0.0,
        value=_num("fuel_oil_heavy_a"), step=100.0, format="%.0f", key=f"e_foil{_yk}")

    fc4, fc5, fc6 = st.columns(3)
    diesel  = fc4.number_input("Diesel (GJ)", min_value=0.0,
        value=_num("diesel"), step=100.0, format="%.0f", key=f"e_diesel{_yk}")
    petrol  = fc5.number_input("Petrol (GJ)", min_value=0.0,
        value=_num("petrol"), step=100.0, format="%.0f", key=f"e_petrol{_yk}")
    biomass = fc6.number_input("Biomass (GJ)", min_value=0.0,
        value=_num("biomass"), step=100.0, format="%.0f", key=f"e_bio{_yk}")

    fc7, fc8, fc9 = st.columns(3)
    waste_tires = fc7.number_input("Waste tires (metric t)", min_value=0.0,
        value=_num("waste_tires_mt"), step=1.0, format="%.0f", key=f"e_wt{_yk}",
        help="Converted to GJ internally")
    lpg         = fc8.number_input("LPG (GJ)", min_value=0.0,
        value=_num("lpg"), step=100.0, format="%.0f", key=f"e_lpg{_yk}")
    other_fuels = fc9.number_input("Other fuels (GJ)", min_value=0.0,
        value=_num("other_fuels"), step=100.0, format="%.0f", key=f"e_other{_yk}")

    # ── Coal breakdown (inline, no expander) ─────────────────────────────────
    st.markdown(f"<div style='font-size:13px;font-weight:600;color:{TEXT};margin:8px 0 4px'>Coal breakdown (GJ LHV)</div>", unsafe_allow_html=True)
    cc1, cc2, cc3 = st.columns(3)
    coal_sub_bit  = cc1.number_input("Sub-bituminous coal (GJ)", min_value=0.0,
        value=_num("", 0.0, "coal_sub_bituminous"), step=100.0, format="%.0f", key=f"e_csub{_yk}")
    coal_brown    = cc2.number_input("Brown coal briquettes (GJ)", min_value=0.0,
        value=_num("", 0.0, "coal_brown_briquettes"), step=100.0, format="%.0f", key=f"e_cbrown{_yk}")
    coal_other    = cc3.number_input("Other bituminous coal (GJ)", min_value=0.0,
        value=_num("", 0.0, "coal_other_bituminous"), step=100.0, format="%.0f", key=f"e_cother{_yk}")

    coal_total = st.number_input(
        "Total coal (GJ) — auto-filled from breakdown above, or enter directly",
        min_value=0.0,
        value=max(_num("coal_sub"), coal_sub_bit + coal_brown + coal_other),
        step=100.0, format="%.0f", key=f"e_coal{_yk}")

    # Live energy totals
    _waste_tire_gj = waste_tires * 28.0   # approx GJ per tonne waste tires
    total_energy_live = (total_elec + purchased_steam + nat_gas + coal_total + propane +
                         fuel_oil + diesel + petrol + biomass + _waste_tire_gj + lpg +
                         other_fuels - sold_steam - sold_electricity)
    energy_kpi_live  = round(total_energy_live / max(production, 1), 4)
    renew_share_live = round((renew_elec + self_gen) / max(total_elec, 1) * 100, 1)

    em1, em2, em3, em4 = st.columns(4)
    em1.metric("Total Electricity (GJ)", f"{total_elec:,.0f}")
    em2.metric("Total Energy (GJ)", f"{total_energy_live:,.0f}")
    em3.metric("Energy KPI (GJ/t)", f"{energy_kpi_live:.4f}")
    em4.metric("Renewable Share", f"{renew_share_live:.1f}%")
    st.divider()

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 5 — CO₂ Emissions (all fields manual input)
    # ══════════════════════════════════════════════════════════════════════════
    st.markdown(f"""<div style="border-left:4px solid {RED};padding:4px 12px;margin:16px 0 8px">
      <b style="font-size:15px;color:{TEXT}">5. CO₂ Emissions (tCO₂)</b>
      <div style="font-size:11px;color:{MUTED}">Enter CO₂ values per fuel source. Total Scope 1 auto-sums. CO₂ KPI auto-calculated.</div>
    </div>""", unsafe_allow_html=True)

    # ── CO₂ Scope 1 — manual input per fuel ──────────────────────────────────
    ca1,ca2,ca3 = st.columns(3)
    co2_nat_gas  = ca1.number_input("Natural Gas (tCO₂)", min_value=0.0,
        value=_num("", nat_gas*_EF.get("Natural Gas",0.0561), "co2_nat_gas"),
        step=10.0, format="%.1f", key=f"e_c_ng{_yk}")
    co2_coal_inp = ca2.number_input("Coal (tCO₂)", min_value=0.0,
        value=_num("", coal_total*_EF.get("Coal",0.0946), "co2_coal"),
        step=10.0, format="%.1f", key=f"e_c_coal{_yk}")
    co2_propane  = ca3.number_input("Propane (tCO₂)", min_value=0.0,
        value=_num("", propane*_EF.get("Propane",0.0631), "co2_propane"),
        step=10.0, format="%.1f", key=f"e_c_prop{_yk}")

    cb1,cb2,cb3 = st.columns(3)
    co2_fuel_oil = cb1.number_input("Fuel Oil (tCO₂)", min_value=0.0,
        value=_num("", fuel_oil*_EF.get("Fuel Oil",0.0745), "co2_fuel_oil"),
        step=10.0, format="%.1f", key=f"e_c_foil{_yk}")
    co2_diesel   = cb2.number_input("Diesel (tCO₂)", min_value=0.0,
        value=_num("", diesel*_EF.get("Diesel",0.0741), "co2_diesel"),
        step=10.0, format="%.1f", key=f"e_c_dies{_yk}")
    co2_petrol   = cb3.number_input("Petrol (tCO₂)", min_value=0.0,
        value=_num("", petrol*_EF.get("Petrol",0.0693), "co2_petrol"),
        step=10.0, format="%.1f", key=f"e_c_pet{_yk}")

    cc1,cc2,cc3 = st.columns(3)
    co2_waste_tires = cc1.number_input("Waste Tires (tCO₂)", min_value=0.0,
        value=_num("", _waste_tire_gj*_EF.get("Waste Tires",0.085), "co2_waste_tires"),
        step=10.0, format="%.1f", key=f"e_c_wt{_yk}")
    co2_lpg      = cc2.number_input("LPG (tCO₂)", min_value=0.0,
        value=_num("", lpg*_EF.get("LPG",0.0639), "co2_lpg"),
        step=10.0, format="%.1f", key=f"e_c_lpg{_yk}")
    co2_other    = cc3.number_input("Other (tCO₂)", min_value=0.0,
        value=_num("", other_fuels*_EF.get("Other",0.075), "co2_other"),
        step=10.0, format="%.1f", key=f"e_c_oth{_yk}")

    # ── Scope 2 (keep steam for formula engine compatibility) ─────────────────
    co2_scope2_steam = 0.0   # removed from UI — set to 0
    scope1_total = (co2_nat_gas + co2_coal_inp + co2_propane + co2_fuel_oil +
                    co2_diesel + co2_petrol + co2_waste_tires + co2_lpg + co2_other)
    scope2_elec_auto = (nonrenew_elec * _G2M) * _S2EF
    scope2_total     = scope2_elec_auto        # only electricity scope 2 remains
    co2_total        = scope1_total + scope2_total
    co2_kpi_live     = round(co2_total / max(production, 1), 4)

    cd1,cd2,cd3,cd4 = st.columns(4)
    cd1.metric("Total CO₂ Scope 1 (tCO₂)",   f"{scope1_total:,.1f}")
    cd2.metric("Total CO₂ Scope 2 (tCO₂)",   f"{scope2_total:,.1f}")
    cd3.metric("Total CO₂ Scope 1+2 (tCO₂)", f"{co2_total:,.1f}")
    cd4.metric("CO₂ KPI (tCO₂/t)",            f"{co2_kpi_live:.4f}")
    st.divider()

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 6 — Waste
    # ══════════════════════════════════════════════════════════════════════════
    st.markdown(f"""<div style="border-left:4px solid {CAT_WASTE};padding:4px 12px;margin:16px 0 8px">
      <b style="font-size:15px;color:{TEXT}">6. Waste Management</b>
      <div style="font-size:11px;color:{MUTED}">Metric tonnes</div>
    </div>""", unsafe_allow_html=True)

    ww1, ww2 = st.columns(2)
    waste_total    = ww1.number_input("Total amount of waste (metric t)", min_value=0.0,
        value=_num("waste_total"), step=10.0, format="%.0f", key=f"e_wastot{_yk}")
    waste_recovery = ww2.number_input("Amount sent to recovery (metric t)", min_value=0.0,
        value=_num("waste_recovery"), step=10.0, format="%.0f", key=f"e_wasrec{_yk}")

    waste_elim   = max(waste_total - waste_recovery, 0)
    waste_rr_pct = round(waste_recovery / max(waste_total, 1) * 100, 1)
    wa1,wa2,wa3 = st.columns(3)
    wa1.metric("Sent to elimination (auto)", f"{waste_elim:,.0f} t")
    wa2.metric("Recovery rate (auto)",       f"{waste_rr_pct:.1f}%")
    wa3.metric("Waste intensity (kg/t)",     f"{waste_total/max(production,1)*1000:.1f}")
    if waste_recovery > waste_total > 0:
        st.error("⚠ Waste recovered cannot exceed total waste.")
    st.divider()

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 7 — Health & Safety
    # ══════════════════════════════════════════════════════════════════════════
    st.markdown(f"""<div style="border-left:4px solid #0EA5E9;padding:4px 12px;margin:16px 0 8px">
      <b style="font-size:15px;color:{TEXT}">7. Health & Safety</b>
      <div style="font-size:11px;color:{MUTED}">Site-level audit coverage</div>
    </div>""", unsafe_allow_html=True)

    hs1, hs2, hs3 = st.columns(3)
    hs_total_sites = hs1.number_input("Total sites (H&S)", min_value=0,
        value=int(_num("", int(total_sites), "hs_external_audit") or int(total_sites)),
        step=1, key=f"e_hstot{_yk}", help="Defaults to total sites above")
    hs_external = hs2.number_input("Sites with external H&S audit", min_value=0,
        value=int(_num("", 0, "hs_external_audit")), step=1, key=f"e_hsext{_yk}")
    hs_internal = hs3.number_input("Sites with internal H&S audit", min_value=0,
        value=int(_num("", 0, "hs_internal_audit")), step=1, key=f"e_hsint{_yk}")

    hs_ext_pct = round(hs_external / max(hs_total_sites, 1) * 100, 1)
    hs_int_pct = round(hs_internal / max(hs_total_sites, 1) * 100, 1)
    ha1,ha2 = st.columns(2)
    ha1.metric("External audit coverage (auto)", f"{hs_ext_pct:.1f}%")
    ha2.metric("Internal audit coverage (auto)", f"{hs_int_pct:.1f}%")
    st.divider()

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 8 — Diversity & Inclusion
    # ══════════════════════════════════════════════════════════════════════════
    st.markdown(f"""<div style="border-left:4px solid #8B5CF6;padding:4px 12px;margin:16px 0 8px">
      <b style="font-size:15px;color:{TEXT}">8. Diversity & Inclusion</b>
    </div>""", unsafe_allow_html=True)

    di1,di2,di3,di4 = st.columns(4)
    total_employees = di1.number_input("Total employees", min_value=0,
        value=int(_num("", 0, "total_employees")), step=10, key=f"e_emp{_yk}")
    female_employees = di2.number_input("Total female employees", min_value=0,
        value=int(_num("", 0, "female_employees")), step=1, key=f"e_femp{_yk}")
    board_total  = di3.number_input("Total Board of Directors", min_value=0,
        value=int(_num("", 0, "board_total")), step=1, key=f"e_bod{_yk}")
    female_board = di4.number_input("Female Board of Directors", min_value=0,
        value=int(_num("", 0, "female_board")), step=1, key=f"e_fbod{_yk}")

    fem_emp_pct = round(female_employees / max(total_employees, 1) * 100, 1)
    fem_bod_pct = round(female_board / max(board_total, 1) * 100, 1)
    da1,da2 = st.columns(2)
    da1.metric("% Female employees (auto)", f"{fem_emp_pct:.1f}%")
    da2.metric("% Female BOD (auto)",       f"{fem_bod_pct:.1f}%")
    st.divider()

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 9 — Science-Based Targets
    # ══════════════════════════════════════════════════════════════════════════
    st.markdown(f"""<div style="border-left:4px solid #F59E0B;padding:4px 12px;margin:16px 0 8px">
      <b style="font-size:15px;color:{TEXT}">9. Science-Based Targets (SBTs)</b>
      <div style="font-size:11px;color:{MUTED}">Number of companies — enter 0 or 1 per field as applicable</div>
    </div>""", unsafe_allow_html=True)

    sb1,sb2,sb3,sb4 = st.columns(4)
    sbt_total      = sb1.number_input("Total with SBT", min_value=0,
        value=int(_num("", 0, "sbt_total")), step=1, key=f"e_sbttot{_yk}")
    sbt_validated  = sb2.number_input("Validated", min_value=0,
        value=int(_num("", 0, "sbt_validated")), step=1, key=f"e_sbtval{_yk}")
    sbt_committed  = sb3.number_input("Committed", min_value=0,
        value=int(_num("", 0, "sbt_committed")), step=1, key=f"e_sbtcom{_yk}")
    sbt_non        = sb4.number_input("Non-committed", min_value=0,
        value=int(max(_num("", 0, "sbt_total") - _num("", 0, "sbt_validated") - _num("", 0, "sbt_committed"), 0)),
        step=1, key=f"e_sbtnon{_yk}")

    # ══════════════════════════════════════════════════════════════════════════
    # CHANGE REASON (shown only when editing a PREVIOUS year's record)
    # ══════════════════════════════════════════════════════════════════════════
    change_reason = ""
    if is_editing_prior:
        st.divider()
        st.markdown(f"""<div style="border-left:4px solid {AMBER};padding:4px 12px;margin:16px 0 8px">
          <b style="font-size:14px;color:{TEXT}">⚠ Change Reason Required</b>
          <div style="font-size:11px;color:{MUTED}">
            Editing a previous year requires a reason. This will be sent to DSS for approval
            before the comment is visible in the template.</div>
        </div>""", unsafe_allow_html=True)
        change_reason = st.text_area(
            "Reason for updating this record",
            placeholder="e.g. Corrected energy consumption figure after audit — original data included double-counted site",
            key=f"entry_reason{_yk}", height=80,
        )

    # ══════════════════════════════════════════════════════════════════════════
    # SUBMIT
    # ══════════════════════════════════════════════════════════════════════════
    st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)
    if is_editing_prior and not change_reason.strip():
        st.warning("Please enter a change reason before submitting.")
    submitted = st.button("✅  Submit & Save Data", type="primary",
                          use_container_width=True, key=f"entry_submit_btn{_yk}")

    if submitted:
        if is_editing_prior and not change_reason.strip():
            st.error("A change reason is required when editing a previous year.")
            st.stop()

        # Build TemplateInputs (fields that formula engine knows about)
        inp = TemplateInputs(
            company=company, year=sel_yr,
            total_sites=total_sites, iso_sites=iso_sites,
            production=production,
            water_withdrawals=water_intake,      # water_intake feeds formula engine
            renew_elec_purchased=renew_elec,
            nonrenew_elec_purchased=nonrenew_elec,
            self_gen_elec=self_gen,
            purchased_steam=purchased_steam,
            sold_electricity=sold_electricity,
            sold_steam=sold_steam,
            nat_gas=nat_gas, coal_sub=coal_total, propane=propane,
            fuel_oil_heavy_a=fuel_oil, diesel=diesel, petrol=petrol,
            biomass=biomass, waste_tires_mt=waste_tires,
            lpg=lpg, other_fuels=other_fuels,
            co2_scope2_steam=co2_scope2_steam,
            waste_total=waste_total, waste_recovery=waste_recovery,
        )
        out = calculate(inp)

        # Save supplementary fields
        supp_data = {
            "stress_water_withdrawal":   stress_wd,
            "non_stress_water_withdrawal": non_stress_wd,
            "coal_sub_bituminous":       coal_sub_bit,
            "coal_brown_briquettes":     coal_brown,
            "coal_other_bituminous":     coal_other,
            "hs_external_audit":         hs_external,
            "hs_internal_audit":         hs_internal,
            "total_employees":           total_employees,
            "female_employees":          female_employees,
            "board_total":               board_total,
            "female_board":              female_board,
            "sbt_total":                 sbt_total,
            "sbt_validated":             sbt_validated,
            "sbt_committed":             sbt_committed,
            "sbt_non_committed":         sbt_non,
        }
        _save_supplementary(company, sel_yr, supp_data)

        # Save change reason for modified fields (if editing previous year)
        if is_editing_prior and change_reason.strip():
            _save_change_comment(company, sel_yr, "SUBMISSION", "Data Submission",
                                 old_val="(previous values)", new_val="(updated values)",
                                 reason=change_reason.strip())

        # Save to master CSV via standard mechanism
        new_step_data = {fld: getattr(inp, fld) for fld in state.VALID_TEMPLATE_FIELDS}
        st.session_state.step_data          = new_step_data
        st.session_state["_codata_inp"]     = inp
        st.session_state["_codata_out"]     = out
        st.session_state.reporting_company  = company
        st.session_state.reporting_year     = sel_yr
        st.session_state.template_done      = True
        st.session_state.company_setup_done = True
        st.session_state.step               = 6
        for fld in state.VALID_TEMPLATE_FIELDS:
            st.session_state[fld] = getattr(inp, fld)

        msg = _save_submission_to_csv(inp, out)
        st.session_state["_last_save_msg"] = msg
        if is_editing_prior and change_reason.strip():
            st.session_state["_last_save_msg"] += " · Change reason submitted for DSS review."
        st.session_state.page = "my_records"
        st.session_state.pop("myrec_year", None)
        st.rerun()