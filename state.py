"""
state.py — TIP ESG Platform · Live Application State
=====================================================
Mutable module-level variables shared across pages and components.
app.py writes these once at startup and refreshes after every save.
All page and component modules import what they need from here.

Never import streamlit here — this module has no UI dependency.
"""
from __future__ import annotations
import pandas as pd
import logging

_log = logging.getLogger("esg_app")

# ── Master data ───────────────────────────────────────────────────────────────
CONSOLIDATED_DF:  pd.DataFrame = pd.DataFrame()
COMPANIES:        list         = []
SECTOR_DF:        pd.DataFrame = pd.DataFrame()
USING_FALLBACK:   bool         = True

# ── Year constants (refreshed from data at startup) ───────────────────────────
HIST_YEARS: list = []
CURR_YEAR:  int  = 2023
LONG_YEARS: list = []

# ── Chart data ─────────────────────────────────────────────────────────────────
LONG_DATA: dict = {}
FUEL_MIX:  dict = {}

# ── Template field names (TemplateInputs dataclass fields) ────────────────────
# Used by pages to filter dict keys before constructing TemplateInputs objects.
from formula_engine import TemplateInputs as _TI
VALID_TEMPLATE_FIELDS: set = {f for f in _TI.__dataclass_fields__}

# ── Static historical fallback data (used when no CSV loaded) ─────────────────
HIST_RAW: dict[str, list] = {
    "total_sites":   [38,39,40,40,41,42,43,44,46,48,51,51,52,52],
    "iso_sites":     [36,38,39,39,40,41,42,43,45,47,51,51,52,52],
    "production":    [2_840_000,3_510_000,3_770_000,3_520_000,3_640_000,3_620_000,
                      3_540_000,3_630_000,3_700_000,3_910_000,3_860_000,3_050_000,3_320_000,3_580_000],
    "water_withdrawals": [18_000_000,19_200_000,20_100_000,19_700_000,20_500_000,21_000_000,
                          21_500_000,22_000_000,22_800_000,23_100_000,23_100_000,20_300_000,21_100_000,20_900_000],
    "renew_elec_purchased": [0,0,0,0,0,0,0,300_000,250_000,1_100_000,706_562,1_528_836,2_557_561,4_082_923],
    "nonrenew_elec_purchased": [9_500_000,9_400_000,9_600_000,9_300_000,9_400_000,9_500_000,
                                9_600_000,9_400_000,9_300_000,9_100_000,12_271_131,9_667_437,10_297_758,9_037_549],
    "nat_gas": [13_000_000,14_000_000,15_000_000,14_500_000,15_000_000,15_200_000,
                15_500_000,15_700_000,15_900_000,16_100_000,16_210_969,14_040_397,15_939_109,15_927_554],
    "coal_sub": [500_000,490_000,480_000,470_000,460_000,450_000,
                 440_000,430_000,420_000,410_000,456_997,337_992,360_848,395_006],
    "lpg": [1_000_000,1_050_000,1_100_000,1_100_000,1_100_000,1_150_000,
            1_150_000,1_180_000,1_200_000,1_220_000,1_237_839,1_124_479,1_271_422,1_329_571],
    "waste_total":    [330_000,330_000,335_000,335_000,340_000,342_000,
                       344_000,346_000,348_000,350_000,352_000,295_000,320_000,335_000],
    "waste_recovery": [280_000,281_000,283_000,284_000,286_000,287_000,
                       289_000,292_000,295_000,298_000,299_200,253_700,275_200,284_750],
}

# ── All 31 electricity-by-country column names ────────────────────────────────
ELEC_ALL_COUNTRIES = [
    "Canada", "Chile", "Mexico", "United States",
    "Australia", "Japan", "Korea", "New Zealand",
    "Austria", "Belgium", "Czech Republic", "Denmark", "Finland", "France",
    "Germany", "Hungary", "Iceland", "Ireland", "Italy", "Luxembourg",
    "Netherlands", "Norway", "Poland", "Portugal", "Spain", "Sweden",
    "Switzerland", "Turkey", "United Kingdom",
    "China", "India",
]

# ── Electricity column name helper + country-to-column mapping ───────────────
def _elec_col(country: str) -> str:
    """Canonical master CSV column name for a country's electricity (GJ)."""
    return "Elec_" + country.replace(" ", "_") + "_GJ"

ELEC_COUNTRY_COLS = {c: _elec_col(c) for c in ELEC_ALL_COUNTRIES}

# ── Supplementary data field names ──────────────────────────────────────────
_SUPP_FIELDS = [
    "Company","Year",
    # Water detail
    "stress_water_withdrawal","non_stress_water_withdrawal",
    # Coal breakdown
    "coal_sub_bituminous","coal_brown_briquettes","coal_other_bituminous",
    # H&S
    "hs_external_audit","hs_internal_audit",
    # Diversity
    "total_employees","female_employees","board_total","female_board",
    # SBT
    "sbt_total","sbt_validated","sbt_committed","sbt_non_committed",
]