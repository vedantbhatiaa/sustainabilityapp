"""
utils/helpers.py — TIP ESG Platform · Page Helper Functions
============================================================
Stateless computation helpers shared across multiple pages.
These were previously defined inside app.py but extracted here
so pages can import them without circular dependencies.

No Streamlit state reads here — all inputs passed as arguments.
Globals read via state module.
"""
from __future__ import annotations
import streamlit as st
import pandas as pd
import numpy as np
import logging
from pathlib import Path
from datetime import datetime

import config as cfg
import data_loader as dl
import state
from utils.data_utils import _sync_company_member_files, _sync_consolidate_excel
from formula_engine import (
    TemplateInputs, calculate, validate_submission,
    get_benchmarks, fmt_num, yoy_change, BenchmarkResult,
)

_log = logging.getLogger("esg_app")

def get_hist_outputs():
    """
    Return list of (year, TemplateInputs, TemplateOutputs) for ALL years in the DB.
    Uses year-keyed dict lookup — avoids positional list drift when fields missing.
    Always reads from state.CONSOLIDATED_DF so any saved update is immediately visible.
    """
    company = (st.session_state.get("reporting_company") or
               st.session_state.get("user_company") or "")
    if company and not state.CONSOLIDATED_DF.empty:
        all_years  = sorted(dl.get_years(state.CONSOLIDATED_DF, company) or [])
        comp_hist  = dl.get_company_hist(state.CONSOLIDATED_DF, company)
    else:
        all_years  = list(state.HIST_YEARS)
        comp_hist  = {}
    outs = []
    for yr in all_years:
        step  = dl.get_step_data(comp_hist, yr) if comp_hist else {}
        clean = {k: v for k, v in step.items() if k in state.VALID_TEMPLATE_FIELDS}
        inp   = TemplateInputs(company=company, year=yr, **clean)
        outs.append((yr, inp, calculate(inp)))
    return outs


def _get_fresh_hist(company: str = None) -> dict:
    """
    Load company historical data for ALL available years from state.CONSOLIDATED_DF.
    Includes the current year if a row exists (e.g. after a save).
    Falls back to state.HIST_RAW (static demo data) when company is unknown.
    """
    co = company or st.session_state.get("reporting_company") or st.session_state.get("user_company") or ""
    if co and not state.CONSOLIDATED_DF.empty:
        hist = dl.get_company_hist(state.CONSOLIDATED_DF, co)
        if hist:
            # Use ALL years present in the DB, not just the pre-2023 window
            all_years = sorted(dl.get_years(state.CONSOLIDATED_DF, co) or [])
            return dl.get_hist_raw(hist, all_years) if all_years else dl.get_hist_raw(hist, state.HIST_YEARS)
    return st.session_state.get("live_hist_raw") or state.HIST_RAW


def get_current_outputs():
    sd = st.session_state.step_data
    inp = TemplateInputs(
        company=st.session_state.get("reporting_company") or st.session_state.user_company,
        year=st.session_state.get("reporting_year", state.CURR_YEAR),
        **{k: float(sd.get(k, 0)) for k in [
            "total_sites", "iso_sites", "production", "water_withdrawals",
            "renew_elec_purchased", "nonrenew_elec_purchased", "self_gen_elec",
            "purchased_steam", "sold_electricity", "sold_steam",
            "nat_gas", "coal_sub", "propane", "fuel_oil_heavy_a",
            "diesel", "petrol", "biomass", "waste_tires_mt", "lpg", "other_fuels",
            "co2_scope2_steam", "waste_total", "waste_recovery",
        ]}
    )
    return inp, calculate(inp)


def _load_company_year_outputs(company: str, year: int):
    """
    Load inputs and compute outputs for any company+year from the consolidated DB.
    Returns (TemplateInputs, TemplateOutputs) — never falls back to session state
    (session state belongs to the logged-in client, not the selected company).
    """
    hist = dl.get_company_hist(state.CONSOLIDATED_DF, company)
    if hist:
        sd = dl.get_step_data(hist, year)
        sd_clean = {k: v for k, v in sd.items() if k in state.VALID_TEMPLATE_FIELDS}
        if sd_clean:
            inp = TemplateInputs(company=company, year=year, **sd_clean)
            return inp, calculate(inp)
    # Neutral fallback — do NOT use session state (that's the logged-in client's data)
    inp = TemplateInputs(company=company, year=year)
    return inp, calculate(inp)


def _compute_industry_scores(df, year):
    """Compute sector median scores (0–100, 100=best) for the 5 TIP KPIs."""
    KPI_MAP = [
        ("Total CO2 - KPI",              True,  0.55, 0.82),
        ("Total energy - KPI",           True,  8.0,  10.5),
        ("Water intake - KPI",           True,  5.5,  9.0),
        ("Renewable_Electricity_Share_%", False, 0.0,  100.0),
        ("Waste_Recovery_Rate_%",         False, 70.0, 100.0),
    ]
    if df.empty or "Row_Label" in df.columns:
        return [50.0] * 5
    yr_df = df[df["Year"] == year]
    if yr_df.empty:
        # Try nearest year
        nearest = df["Year"].dropna().unique()
        if len(nearest):
            yr_df = df[df["Year"] == nearest[abs(nearest - year).argmin()]]
        if yr_df.empty:
            return [50.0] * 5
    scores = []
    for col, lower_better, best, worst in KPI_MAP:
        if col in yr_df.columns and yr_df[col].notna().any():
            med  = float(yr_df[col].median())
            span = abs(worst - best) or 1
            s    = ((worst - med) / span * 100 if lower_better
                    else (med - best) / span * 100)
            scores.append(round(max(0, min(100, s)), 1))
        else:
            scores.append(50.0)
    return scores


def _compute_kpi_improvement(company: str, base_year: int, end_year: int) -> dict:
    """
    Compute improvement % for each KPI between base_year and end_year.
    Returns {kpi_attr: pct_change_string} for CO2, energy, water KPIs + raw fields.
    """
    base_inp, base_out = _load_company_year_outputs(company, base_year)
    end_inp,  end_out  = _load_company_year_outputs(company, end_year)

    def _pct(b, e):
        if b and b != 0 and e:
            return f"{(e - b) / abs(b) * 100:+.1f}%"
        return "N/A"

    renew_base = (base_inp.renew_elec_purchased + base_inp.self_gen_elec) / max(base_out.total_electricity, 1) * 100
    renew_end  = (end_inp.renew_elec_purchased  + end_inp.self_gen_elec)  / max(end_out.total_electricity,  1) * 100
    wrec_base  = base_out.waste_recovery_pct * 100
    wrec_end   = end_out.waste_recovery_pct  * 100

    return {
        "CO₂ intensity":        _pct(base_out.co2_kpi,    end_out.co2_kpi),
        "Energy intensity":     _pct(base_out.energy_kpi, end_out.energy_kpi),
        "Water intensity":      _pct(base_out.water_kpi,  end_out.water_kpi),
        "Renewable electricity":_pct(renew_base,           renew_end),
        "Waste recovery rate":  _pct(wrec_base,            wrec_end),
    }


def _chart_key(*args) -> str:
    """Unique chart key that changes with company/year selection → forces animation replay."""
    return "__".join(str(a).replace(" ","_") for a in args)


def _compute_completeness(inp: "TemplateInputs", out: "TemplateOutputs") -> dict:
    """
    Returns {section_label: pct_complete} based on which fields have non-zero data.
    """
    def pct(*vals):
        filled = sum(1 for v in vals if v is not None and float(v) != 0)
        return int(filled / len(vals) * 100)

    fuel_vals = [inp.nat_gas, inp.coal_sub, inp.propane, inp.fuel_oil_heavy_a,
                 inp.diesel, inp.petrol, inp.biomass, inp.lpg, inp.other_fuels]
    fuel_filled = sum(1 for v in fuel_vals if v > 0)

    return {
        "ISO 14001":           pct(inp.total_sites, inp.iso_sites),
        "Production":          pct(inp.production),
        "Water":               pct(inp.water_withdrawals),
        "Energy — Electricity":pct(inp.renew_elec_purchased + inp.nonrenew_elec_purchased, inp.self_gen_elec),
        "Energy — Fuels":      min(100, int(fuel_filled / max(len(fuel_vals), 1) * 100)) if inp.nat_gas or inp.coal_sub else 0,
        "CO₂ Scope 1":         pct(out.total_co2_scope1),
        "CO₂ Scope 2":         pct(inp.co2_scope2_steam),
        "Waste":               pct(inp.waste_total, inp.waste_recovery),
        "Pathway 3 (SBTi)":    0,   # not captured in current template
        "Pathway 4 (H&S)":     0,   # not captured in current template
        "Pathway 4 (D&I)":     0,   # not captured in current template
    }


def _compute_readiness_score(completeness: dict, flags) -> tuple:
    """
    Score = weighted completeness average, minus penalties for flags.
    Returns (score: int, label: str)
    """
    weights = {
        "ISO 14001":1,"Production":2,"Water":2,
        "Energy — Electricity":3,"Energy — Fuels":3,
        "CO₂ Scope 1":3,"CO₂ Scope 2":2,"Waste":2,
        "Pathway 3 (SBTi)":1,"Pathway 4 (H&S)":1,"Pathway 4 (D&I)":1,
    }
    total_w  = sum(weights.values())
    raw      = sum(completeness.get(k,0) * w for k,w in weights.items()) / total_w
    n_errors   = sum(1 for f in flags if f.severity == "error")
    n_warnings = sum(1 for f in flags if f.severity == "warning")
    score = max(0, min(100, int(raw - n_errors * 10 - n_warnings * 3)))
    label = "Ready" if score >= 90 else "Review required" if score >= 70 else "Not ready"
    return score, label


def _dss_company_selector(page_key: str):
    """
    Lets a dss+ analyst pick any company + year from the consolidated DB.
    Stores selection in session_state under dss_{page_key}_company / _year.
    Returns (company, year, inp, out, prev_inp, prev_out, company_hist).
    """
    co_key = f"dss_{page_key}_company"
    yr_key = f"dss_{page_key}_year"

    companies_in_db = dl.get_companies(state.CONSOLIDATED_DF) or state.COMPANIES
    default_co = (st.session_state.get("reporting_company") or
                  st.session_state.get("user_company") or companies_in_db[0])
    if default_co not in companies_in_db:
        default_co = companies_in_db[0]

    col1, col2, _ = st.columns([2, 1, 3])
    with col1:
        sel_co = st.selectbox(
            "Company to review", options=companies_in_db,
            index=companies_in_db.index(st.session_state.get(co_key, default_co)),
            key=f"sel_{page_key}_co"
        )
    with col2:
        avail_years = dl.get_years(state.CONSOLIDATED_DF, sel_co) or [state.CURR_YEAR]
        sel_yr = st.selectbox(
            "Year", options=sorted(avail_years, reverse=True),
            key=f"sel_{page_key}_yr"
        )

    st.session_state[co_key] = sel_co
    st.session_state[yr_key] = sel_yr

    # Load data for selected and previous year
    hist = dl.get_company_hist(state.CONSOLIDATED_DF, sel_co)

    def _make_inp_out(year):
        sd = dl.get_step_data(hist, year)
        sd_clean = {k: v for k, v in sd.items() if k in state.VALID_TEMPLATE_FIELDS}
        inp = TemplateInputs(company=sel_co, year=year, **sd_clean)
        return inp, calculate(inp)

    inp,  out  = _make_inp_out(sel_yr)
    try:
        prev_inp, prev_out = _make_inp_out(sel_yr - 1)
    except Exception:
        prev_inp, prev_out = TemplateInputs(company=sel_co, year=sel_yr-1), None

    return sel_co, sel_yr, inp, out, prev_inp, prev_out, hist


def _save_electricity_to_master(company: str, year: int) -> str:
    """
    Save electricity-by-country data (from the Electricity tab editor) into:
      1. Master wide CSV  — columns Elec_<Country>_GJ  (GJ = MWh x 3.6)
      2. TIP members aggregate CSV
      3. Per-company member CSVs in data_storage/members/TIP/<Company>/
      4. CONSOLIDATED_DUMMY Excel (Raw Dummy data sheet, long format)
      5. Parquet snapshot of the complete company+year row

    Updates ALL years that have non-zero values in the electricity editor.
    Only the 7 countries already in the master schema are written:
        Canada, Mexico, United States, Japan, France, Hungary, Italy
    Any other country rows in the editor UI are displayed but not persisted.
    """
    from pathlib import Path
    from datetime import datetime

    COUNTRY_COL = state.ELEC_COUNTRY_COLS  # all 31 countries
    MWH_TO_GJ = 3.6

    elec_df = st.session_state.get("elec_data", pd.DataFrame())
    if elec_df.empty:
        return "No electricity data entered yet."

    _ecands = dl._get_csv_candidates()
    csv_path = next((p for p in _ecands if p.exists()
                     and p.name.startswith("ESG_MASTER_WIDE_ALL_COMPANIES_")), None)
    if csv_path is None:
        return "Master CSV not found. Save KPI data first."
    try:
        master = pd.read_csv(csv_path)
    except PermissionError:
        return "Master CSV is open in Excel — close it and try again."

    # Ensure all country columns exist in master (add if missing)
    for col in COUNTRY_COL.values():
        if col not in master.columns:
            master[col] = None
    if "Total_Electricity_by_Country_GJ" not in master.columns:
        master["Total_Electricity_by_Country_GJ"] = None

    yr_cols = [c for c in elec_df.columns if str(c).isdigit() and 2000 < int(c) < 2030]

    updated_years = []
    for yr_str in yr_cols:
        yr   = int(yr_str)
        mask = (master["Company"] == company) & (master["Year"] == yr)
        if not mask.any():
            # KPI row not found for this year — create a minimal stub row so
            # electricity data is not lost; user can submit KPIs later.
            stub = pd.DataFrame([{
                "Company": company, "Year": yr,
                **{c: 0.0 for c in COUNTRY_COL.values()},
                "Total_Electricity_by_Country_GJ": 0.0,
            }])
            # Align to master columns
            for col in master.columns:
                if col not in stub.columns:
                    stub[col] = None
            stub = stub[master.columns]
            master = pd.concat([master, stub], ignore_index=True)
            master = master.sort_values(["Company", "Year"]).reset_index(drop=True)
            mask = (master["Company"] == company) & (master["Year"] == yr)

        year_series = elec_df.set_index("Country")[yr_str]
        for country, mwh_val in year_series.items():
            col_name = COUNTRY_COL.get(str(country))
            if col_name is None:
                continue  # country not in master schema
            gj_val = float(mwh_val) * MWH_TO_GJ if pd.notna(mwh_val) else 0.0
            master.loc[mask, col_name] = round(gj_val, 4)

        # Recompute total-by-country for this row
        country_vals = [master.loc[mask, c].values[0]
                        for c in COUNTRY_COL.values() if c in master.columns]
        master.loc[mask, "Total_Electricity_by_Country_GJ"] = round(
            sum(v for v in country_vals if pd.notna(v)), 4)

        updated_years.append(yr)

    if not updated_years:
        return f"No KPI rows found for {company}. Save KPI data first."

    try:
        # H1 FIX: use the same advisory lock as the KPI save path
        lock_path = csv_path.with_suffix(".lock")
        with FileLock(str(lock_path), timeout=cfg.FILELOCK_TIMEOUT):
            master.to_csv(csv_path, index=False)
    except PermissionError:
        return "Master CSV is open in Excel — close it and try again."

    # Sync all dependent files
    try:
        _sp = csv_path.stem.split("_"); _ys, _ye = _sp[-2], _sp[-1]
    except Exception:
        _ys, _ye = str(cfg.DATA_YEAR_START), str(cfg.DATA_YEAR_END)
    tip_master_path = Path(f"data_storage/members/TIP/ESG_MASTER_WIDE_TIP_MEMBERS_{_ys}_{_ye}.csv")
    _update_tip_members_file(csv_path, tip_master_path)
    _sync_company_member_files(master)
    _sync_consolidate_excel(master)

    # Parquet snapshot
    co_safe  = company.replace(" ", "_").replace("/", "_")
    ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
    ver_dir  = Path("data_storage") / "versions" / co_safe
    ver_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{co_safe}_{year}_elec_{ts}.parquet"
    single_row = master[(master["Company"] == company) & (master["Year"] == year)].copy()
    try:
        single_row.to_parquet(ver_dir / filename, index=False)
    except Exception:
        filename = "[parquet skipped]"

    return (f"Electricity saved — {len(updated_years)} year(s) updated "
            f"({min(updated_years)}-{max(updated_years)}) converted MWh to GJ. "
            f"Consolidate + member files synced. "
            f"Snapshot: versions/{co_safe}/{filename}")