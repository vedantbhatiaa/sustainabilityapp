"""
formula_engine.py — TIP ESG Platform · KPI Calculation Engine
==============================================================
Pure calculation logic — no Streamlit or file I/O dependencies.
Defines: TemplateInputs, TemplateOutputs, calculate(), validate_submission(),
         get_benchmarks(), BenchmarkResult, fmt_num(), yoy_change()

Emission factors (EF) and conversion constants are defined at module level.
To update factors: edit the EF dict and WASTE_TIRE_HV below.
"""

from dataclasses import dataclass, field
from typing import Optional
import numpy as np

# ── Emission factors (T.CO2 per GJ LHV) ─────────────────────────────────────
EF = {
    "Natural Gas": 0.0561, "Coal": 0.0961, "Propane": 0.0631,
    "Fuel Oil":    0.0774, "Diesel": 0.0741, "Petrol":  0.0693,
    "Biomass":     0.0,   "Waste tires": 0.0475,
    "LPG":         0.0561, "Other": 0.0719,
}

WASTE_TIRE_HV = 36.23          # GJ per metric T of waste tires
GJ_TO_MWH    = 1 / 3.6

# Default Scope 2 electricity emission factor (T.CO2/MWh).
# This is the European average.  Override per company via
# TemplateInputs.scope2_elec_ef when country-specific factors are known.
_DEFAULT_SCOPE2_ELEC_EF = 0.45


@dataclass
class TemplateInputs:
    company: str  = ""
    year:    int  = 2023

    total_sites: float = 0
    iso_sites:   float = 0
    production:  float = 0

    water_withdrawals: float = 0

    renew_elec_purchased:    float = 0
    nonrenew_elec_purchased: float = 0
    self_gen_elec:           float = 0
    purchased_steam:         float = 0
    sold_electricity:        float = 0
    sold_steam:              float = 0

    nat_gas:          float = 0
    coal_sub:         float = 0
    propane:          float = 0
    fuel_oil_heavy_a: float = 0
    diesel:           float = 0
    petrol:           float = 0
    biomass:          float = 0
    waste_tires_mt:   float = 0
    lpg:              float = 0
    other_fuels:      float = 0

    co2_scope2_steam: float = 0

    waste_total:    float = 0
    waste_recovery: float = 0

    # M4 FIX — configurable per company/region instead of a hardcoded global.
    # Defaults to 0.45 (EU average) so existing call-sites need no changes.
    scope2_elec_ef: float = _DEFAULT_SCOPE2_ELEC_EF


@dataclass
class TemplateOutputs:
    pct_certified:   float = 0.0
    water_kpi:       float = 0.0

    total_electricity: float = 0.0
    waste_tires_gj:    float = 0.0
    total_energy:      float = 0.0
    energy_kpi:        float = 0.0

    co2_nat_gas:    float = 0.0
    co2_coal:       float = 0.0
    co2_propane:    float = 0.0
    co2_fuel_oil:   float = 0.0
    co2_diesel:     float = 0.0
    co2_petrol:     float = 0.0
    co2_biomass:    float = 0.0
    co2_waste_tires:float = 0.0
    co2_lpg:        float = 0.0
    co2_other:      float = 0.0

    total_co2_scope1: float = 0.0
    total_co2_scope2: float = 0.0
    total_co2:        float = 0.0
    co2_kpi:          float = 0.0

    waste_elimination:   float = 0.0
    waste_recovery_pct:  float = 0.0

    # M1 FIX — check_waste now carries meaning (see calculate())
    check_waste: bool = True
    check_iso:   bool = True


def calculate(d: TemplateInputs) -> TemplateOutputs:
    def sdiv(a, b): return a / b if b else 0.0

    pct_cert  = sdiv(d.iso_sites, d.total_sites)
    water_kpi = sdiv(d.water_withdrawals, d.production)

    total_elec = (d.renew_elec_purchased
                  + d.nonrenew_elec_purchased
                  + d.self_gen_elec)

    wt_gj = d.waste_tires_mt * WASTE_TIRE_HV

    total_e = (total_elec + d.purchased_steam
               + d.nat_gas + d.coal_sub + d.propane
               + d.fuel_oil_heavy_a + d.diesel + d.petrol
               + d.biomass + wt_gj + d.lpg + d.other_fuels
               - d.sold_electricity - d.sold_steam)

    e_kpi = sdiv(total_e, d.production)

    s1_ng   = d.nat_gas          * EF["Natural Gas"]
    s1_coal = d.coal_sub         * EF["Coal"]
    s1_prop = d.propane          * EF["Propane"]
    s1_fo   = d.fuel_oil_heavy_a * EF["Fuel Oil"]
    s1_die  = d.diesel           * EF["Diesel"]
    s1_pet  = d.petrol           * EF["Petrol"]
    s1_bio  = d.biomass          * EF["Biomass"]
    s1_wt   = wt_gj              * EF["Waste tires"]
    s1_lpg  = d.lpg              * EF["LPG"]
    s1_oth  = d.other_fuels      * EF["Other"]

    scope1 = (s1_ng + s1_coal + s1_prop + s1_fo + s1_die
              + s1_pet + s1_bio + s1_wt + s1_lpg + s1_oth)

    # M4 FIX — use instance-level EF (defaults to 0.45 if not overridden)
    scope2 = (d.co2_scope2_steam
              + (d.nonrenew_elec_purchased * GJ_TO_MWH) * d.scope2_elec_ef)

    total_co2 = scope1 + scope2
    co2_kpi   = sdiv(total_co2, d.production)

    w_elim = d.waste_total - d.waste_recovery

    # M1 FIX — previous check was abs(total - recovery - w_elim) < 1 which
    # is always True because w_elim = total - recovery (a tautology).
    # Correct intent: if a user also enters waste_elimination separately we
    # would compare; here we validate that recovery cannot exceed total,
    # and that waste_total is a positive number when recovery is non-zero.
    check_waste = (
        d.waste_total >= 0
        and d.waste_recovery >= 0
        and d.waste_recovery <= d.waste_total
    )

    return TemplateOutputs(
        pct_certified=pct_cert,       water_kpi=water_kpi,
        total_electricity=total_elec, waste_tires_gj=wt_gj,
        total_energy=total_e,         energy_kpi=e_kpi,
        co2_nat_gas=s1_ng,   co2_coal=s1_coal,    co2_propane=s1_prop,
        co2_fuel_oil=s1_fo,  co2_diesel=s1_die,   co2_petrol=s1_pet,
        co2_biomass=s1_bio,  co2_waste_tires=s1_wt,
        co2_lpg=s1_lpg,      co2_other=s1_oth,
        total_co2_scope1=scope1,  total_co2_scope2=scope2,
        total_co2=total_co2,      co2_kpi=co2_kpi,
        waste_elimination=w_elim,
        waste_recovery_pct=sdiv(d.waste_recovery, d.waste_total),
        check_waste=check_waste,
        check_iso=(d.iso_sites <= d.total_sites),
    )


@dataclass
class ValidationFlag:
    severity: str
    message:  str
    detail:   str = ""


def validate_submission(inp, out, prev_out=None, threshold=20.0):
    flags = []

    # M1 FIX — this now actually catches waste_recovery > waste_total
    if not out.check_waste:
        flags.append(ValidationFlag(
            "error",
            "Waste consistency FAIL",
            f"Recovery {inp.waste_recovery:,.0f} T exceeds total {inp.waste_total:,.0f} T"
            if inp.waste_recovery > inp.waste_total
            else "Negative waste values entered",
        ))

    if not out.check_iso:
        flags.append(ValidationFlag("error", "ISO sites > total sites", ""))

    if prev_out:
        for name, cur, prev in [
            ("Total Energy", out.total_energy, prev_out.total_energy),
            ("Total CO2",    out.total_co2,    prev_out.total_co2),
        ]:
            if prev and abs(cur - prev) / max(abs(prev), 1) * 100 > threshold:
                pct = (cur - prev) / abs(prev) * 100
                flags.append(ValidationFlag(
                    "warning", f"{name}: {pct:+.1f}% YoY", ""
                ))

    if not flags:
        flags.append(ValidationFlag("ok", "All checks passed", ""))

    return flags


@dataclass
class BenchmarkResult:
    kpi_name:       str
    company_value:  float
    q25:            float
    median:         float
    q75:            float
    unit:           str
    lower_is_better:bool


def get_benchmarks(out, bench_df=None):
    STATIC = {
        "co2_kpi":    (0.55,  0.68, 0.82,  "T.CO2/T", True),
        "energy_kpi": (8.0,   9.2,  10.5,  "GJ/T",    True),
        "water_kpi":  (5.5,   7.0,   9.0,  "m3/T",    True),
    }
    results = []
    for col, (fq25, fmed, fq75, unit, lb) in STATIC.items():
        q25, med, q75 = fq25, fmed, fq75
        if bench_df is not None and not bench_df.empty and col in bench_df.columns:
            vals = bench_df[col].dropna().values
            if len(vals) >= 4:
                q25 = float(np.percentile(vals, 25))
                med = float(np.percentile(vals, 50))
                q75 = float(np.percentile(vals, 75))
        results.append(BenchmarkResult(
            col, getattr(out, col, 0.0), q25, med, q75, unit, lb
        ))
    return results


def fmt_num(val, decimals=0):
    try:
        return (f"{float(val):,.{decimals}f}" if decimals
                else f"{float(val):,.0f}")
    except Exception:
        return str(val)


def yoy_change(current, previous):
    try:
        if previous and abs(float(previous)) > 0:
            return (float(current) - float(previous)) / abs(float(previous)) * 100
    except Exception:
        pass
    return None


def build_template_dataframe(inp, out):
    import pandas as pd
    return pd.DataFrame([{
        "Company":          inp.company,
        "Year":             inp.year,
        "production":       inp.production,
        "water_kpi":        out.water_kpi,
        "total_energy":     out.total_energy,
        "energy_kpi":       out.energy_kpi,
        "total_co2_scope1": out.total_co2_scope1,
        "total_co2_scope2": out.total_co2_scope2,
        "total_co2":        out.total_co2,
        "co2_kpi":          out.co2_kpi,
        "waste_recovery_pct": out.waste_recovery_pct,
    }])