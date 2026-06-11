"""
scripts/build_esg_master.py — TIP ESG Platform · Master Database Builder
=========================================================================
One-time (or periodic) script that converts the consolidated Excel workbook
into the master wide CSV used by the Streamlit app.

Run from the project root:
    python scripts/build_esg_master.py

Input:  data_storage/master/CONSOLIDATED_DUMMY_2009_2023.xlsx
Output: data_storage/master/ESG_MASTER_WIDE_ALL_COMPANIES_2009_2023.csv
        data_storage/master/ESG_SECTOR_AGGREGATED_2009_2023.csv
        data_storage/members/TIP/<company>/<company>_latest.csv
        data_storage/master/ESG_MASTER_WIDE_ALL_COMPANIES_2009_2023.xlsx

Not imported by app.py — run as a standalone script only.
"""

import os
import shutil
import numpy as np
import pandas as pd
from pathlib import Path


def _drop_zero_elec_cols(df):
    """Drop Elec_*_GJ country columns where every value is zero/null."""
    elec_cols = [c for c in df.columns if c.startswith("Elec_") and c.endswith("_GJ")
                 and c != "Total_Electricity_by_Country_GJ"]
    zero_cols = [c for c in elec_cols if df[c].fillna(0).eq(0).all()]
    return df.drop(columns=zero_cols) if zero_cols else df

# ── Folder structure ──────────────────────────────────────────────────────────
BASE_DIR    = Path(os.path.dirname(os.path.abspath(__file__)))
MASTER_DIR  = BASE_DIR / "data_storage" / "master"
MEMBERS_TIP = BASE_DIR / "data_storage" / "members" / "TIP"
MEMBERS_NON = BASE_DIR / "data_storage" / "members" / "non_TIP"
VERSIONS_DIR= BASE_DIR / "data_storage" / "versions"
REPORTS_TIP = BASE_DIR / "data_storage" / "reports" / "TIP"
REPORTS_NON = BASE_DIR / "data_storage" / "reports" / "non_TIP"

for d in [MASTER_DIR, MEMBERS_TIP, MEMBERS_NON, VERSIONS_DIR, REPORTS_TIP, REPORTS_NON]:
    d.mkdir(parents=True, exist_ok=True)

# ── Locate source file ────────────────────────────────────────────────────────
FILENAME    = "CONSOLIDATED_DUMMY_2009_2023.xlsx"
SOURCE_FILE = MASTER_DIR / FILENAME
if not SOURCE_FILE.exists():
    fallback = BASE_DIR / FILENAME
    if fallback.exists():
        shutil.copy(fallback, SOURCE_FILE)
        print(f"[INFO] Copied {FILENAME} → data_storage/master/")
    else:
        print(f"[ERROR] Cannot find '{FILENAME}'. Place it in the project root or data_storage/master/")
        raise SystemExit(1)

# ── Country electricity columns ───────────────────────────────────────────────
ELEC_COUNTRIES = [
    "Canada", "Chile", "Mexico", "United States",
    "Australia", "Japan", "Korea", "New Zealand",
    "Austria", "Belgium", "Czech Republic", "Denmark", "Finland", "France",
    "Germany", "Hungary", "Iceland", "Ireland", "Italy", "Luxembourg",
    "Netherlands", "Norway", "Poland", "Portugal", "Spain", "Sweden",
    "Switzerland", "Turkey", "United Kingdom",
    "China", "India",
]

def elec_col_raw(country):   return f"Electricity - {country}"
def elec_col_clean(country): return f"Elec_{country.replace(' ', '_')}_GJ"

ELEC_RAW_COLS   = [elec_col_raw(c)   for c in ELEC_COUNTRIES]
ELEC_CLEAN_COLS = [elec_col_clean(c) for c in ELEC_COUNTRIES]

# ── Step 1: Load ──────────────────────────────────────────────────────────────
print("[1/6] Loading consolidated data...")
raw = pd.read_excel(SOURCE_FILE, sheet_name="Raw Dummy data", header=0)
raw.columns = raw.columns.str.strip()
raw = raw.dropna(subset=["Row_Label"]).copy()
raw["Year"] = raw["Year"].astype(int)
raw["Data"] = pd.to_numeric(raw["Data"], errors="coerce")

COMPANIES = raw["Company"].unique().tolist()
YEARS     = sorted(raw["Year"].unique().tolist())
print(f"    → {len(COMPANIES)} companies | {YEARS[0]}–{YEARS[-1]} | {raw['Row_Label'].nunique()} KPI fields")

# ── Step 2: Pivot ─────────────────────────────────────────────────────────────
print("[2/6] Pivoting to wide format (Company × Year)...")
wide = raw.pivot_table(index=["Company","Year"], columns="Row_Label", values="Data", aggfunc="first").reset_index()
wide.columns.name = None

# Rename country electricity columns to clean names
wide = wide.rename(columns={r: c for r, c in zip(ELEC_RAW_COLS, ELEC_CLEAN_COLS)})

ordered = [
    "Company","Year","Total no. of sites","ISO 14001 sites","% certified sites",
    "Production","Water intake","Water intake - KPI","Total Electricity",
    "Renewable Electricity Purchased","Non-Renewable Electricity Purchased",
    "Self-generated AND consumed electricity on-site","Purchased Steam",
    "Sold Electricity","Sold Steam","Natural Gas","Coal","Propane","Fuel Oil",
    "Diesel","Petrol","Biomass","Waste tires","LPG","Other",
    "Total energy","Total energy - KPI","Total CO2 - Scope 1","Total CO2 - Scope 2",
    "Total CO2","Total CO2 - KPI",
    # ── Waste fields ──────────────────────────────────────────────────────────
    "Total Waste","Waste Recovered","Recovery Rate",
    # ── Electricity by country (one column per country) ───────────────────────
] + ELEC_CLEAN_COLS

ordered = [c for c in ordered if c in wide.columns]
wide = wide[ordered]
print(f"    → {wide.shape[0]} rows × {wide.shape[1]} columns")

# ── Step 3: Derived KPIs ──────────────────────────────────────────────────────
print("[3/6] Engineering derived KPIs...")
df = wide.copy()

df["Renewable_Electricity_Share_%"] = (
    df["Renewable Electricity Purchased"] / df["Total Electricity"].replace(0, np.nan) * 100).round(4)
df["Scope1_Share_%"] = (
    df["Total CO2 - Scope 1"] / df["Total CO2"].replace(0, np.nan) * 100).round(4)
df["Scope2_Share_%"] = (
    df["Total CO2 - Scope 2"] / df["Total CO2"].replace(0, np.nan) * 100).round(4)

fuel_cols = ["Natural Gas","Coal","Propane","Fuel Oil","Diesel","Petrol","Biomass","Waste tires","LPG","Other"]
df["Fossil_Energy_Share_%"] = (
    df[[c for c in fuel_cols if c in df.columns]].sum(axis=1, min_count=1)
    / df["Total energy"].replace(0, np.nan) * 100).round(4)

df["Water_per_ton"]   = (df["Water intake"]  / df["Production"].replace(0, np.nan)).round(4)
df["CO2_per_ton"]     = (df["Total CO2"]     / df["Production"].replace(0, np.nan)).round(4)
df["Energy_per_ton"]  = (df["Total energy"]  / df["Production"].replace(0, np.nan)).round(4)
df["ISO_Certification_%"] = (df["% certified sites"] * 100).round(2)

# Waste derived KPI
if "Total Waste" in df.columns and "Waste Recovered" in df.columns:
    df["Waste_Recovery_Rate_%"] = (
        df["Waste Recovered"] / df["Total Waste"].replace(0, np.nan) * 100).round(4)

# Country electricity total
avail_country_cols = [c for c in ELEC_CLEAN_COLS if c in df.columns]
if avail_country_cols:
    df["Total_Electricity_by_Country_GJ"] = df[avail_country_cols].sum(axis=1, min_count=1).round(2)

print(f"    → Final shape: {df.shape[0]} rows × {df.shape[1]} columns")

# ── Step 4: Save master outputs ───────────────────────────────────────────────
print("[4/6] Saving master files...")

# Long CSV: drop electricity country rows that are zero across all companies
elec_labels = {f"Electricity - {c}" for c in ELEC_COUNTRIES}
long_filtered = raw[
    ~(raw["Row_Label"].isin(elec_labels) & raw["Data"].fillna(0).eq(0))
].copy()
long_path = MASTER_DIR / "ESG_LONG_ALL_COMPANIES_2009_2023.csv"
long_filtered.to_csv(long_path, index=False)
print(f"    → LONG CSV:         {long_path}")

wide_csv = MASTER_DIR / "ESG_MASTER_WIDE_ALL_COMPANIES_2009_2023.csv"
# Master CSV keeps full schema; derived outputs strip all-zero elec country cols
df.to_csv(wide_csv, index=False)
df_out = _drop_zero_elec_cols(df)  # used for Excel + member files
print(f"    → WIDE CSV:         {wide_csv} ({len(df.columns)} cols, "
      f"{len(df_out.columns)} after dropping all-zero country cols)")

wide_xlsx = MASTER_DIR / "ESG_MASTER_WIDE_ALL_COMPANIES_2009_2023.xlsx"
with pd.ExcelWriter(wide_xlsx, engine="openpyxl") as writer:
    df_out.to_excel(writer, sheet_name="All_Companies", index=False)
    for company in COMPANIES:
        # Per-company sheet: strip columns that are all-zero for that company only
        co_df = df[df["Company"] == company].reset_index(drop=True)
        co_df_out = _drop_zero_elec_cols(co_df)
        sheet = company.replace(" ", "_")[:31]
        co_df_out.to_excel(writer, sheet_name=sheet, index=False)
print(f"    → WIDE Excel:       {wide_xlsx}")

agg_dict = dict(
    n_companies=("Company","nunique"), Total_Production=("Production","sum"),
    Total_Energy=("Total energy","sum"), Total_CO2=("Total CO2","sum"),
    Total_Water=("Water intake","sum"), Avg_Energy_KPI=("Total energy - KPI","mean"),
    Avg_CO2_KPI=("Total CO2 - KPI","mean"), Avg_Water_KPI=("Water intake - KPI","mean"),
    Avg_Renewable_Share=("Renewable_Electricity_Share_%","mean"),
    Avg_ISO_Cert=("ISO_Certification_%","mean"),
)
if "Total Waste" in df.columns:
    agg_dict["Total_Waste"] = ("Total Waste", "sum")
if "Waste Recovered" in df.columns:
    agg_dict["Total_Waste_Recovered"] = ("Waste Recovered", "sum")
if "Waste_Recovery_Rate_%" in df.columns:
    agg_dict["Avg_Waste_Recovery_Rate"] = ("Waste_Recovery_Rate_%", "mean")
if "Total_Electricity_by_Country_GJ" in df.columns:
    agg_dict["Total_Elec_by_Country"] = ("Total_Electricity_by_Country_GJ", "sum")
for cc in ELEC_CLEAN_COLS:
    if cc in df.columns:
        agg_dict[f"Total_{cc}"] = (cc, "sum")

sector = df.groupby("Year").agg(**agg_dict).reset_index()
sector_path = MASTER_DIR / "ESG_SECTOR_AGGREGATED_2009_2023.csv"
sector.to_csv(sector_path, index=False)
print(f"    → SECTOR CSV:       {sector_path}")

# ── Step 5: Per-company files in members/TIP/ ─────────────────────────────────
print("[5/6] Writing per-company files to members/TIP/...")
for company in COMPANIES:
    co_folder = MEMBERS_TIP / company.replace(" ", "_")
    co_folder.mkdir(parents=True, exist_ok=True)
    co_df = df[df["Company"] == company].reset_index(drop=True)
    _drop_zero_elec_cols(co_df).to_csv(
        co_folder / f"{company.replace(' ','_')}_latest.csv", index=False)
    (REPORTS_TIP / company.replace(" ", "_")).mkdir(parents=True, exist_ok=True)
print(f"    → {len(COMPANIES)} company folders created in members/TIP/")

# ── Step 6: Clean up legacy columns ──────────────────────────────────────────
print("[6/6] Verifying master CSV column integrity...")
MASTER_COLS = [
    "Company","Year","Total no. of sites","ISO 14001 sites","% certified sites",
    "Production","Water intake","Water intake - KPI","Total Electricity",
    "Renewable Electricity Purchased","Non-Renewable Electricity Purchased",
    "Self-generated AND consumed electricity on-site","Purchased Steam",
    "Sold Electricity","Sold Steam","Natural Gas","Coal","Propane","Fuel Oil",
    "Diesel","Petrol","Biomass","Waste tires","LPG","Other",
    "Total energy","Total energy - KPI","Total CO2 - Scope 1","Total CO2 - Scope 2",
    "Total CO2","Total CO2 - KPI",
    # Waste
    "Total Waste","Waste Recovered","Recovery Rate",
    # Country electricity
] + ELEC_CLEAN_COLS + [
    # Derived KPIs
    "Renewable_Electricity_Share_%","Scope1_Share_%","Scope2_Share_%",
    "Fossil_Energy_Share_%","Water_per_ton","CO2_per_ton","Energy_per_ton",
    "ISO_Certification_%","Waste_Recovery_Rate_%","Total_Electricity_by_Country_GJ",
]
_dirty  = pd.read_csv(wide_csv)
_before = len(_dirty.columns)
_clean  = [c for c in MASTER_COLS if c in _dirty.columns]
_dropped = _before - len(_clean)
if _dropped > 0:
    _dirty[_clean].to_csv(wide_csv, index=False)
    print(f"    Removed {_dropped} legacy columns from master CSV.")
else:
    print("    Master CSV is clean — no legacy columns found.")

print("\n✅ Master database ready.")
print(f"   Master files:  {MASTER_DIR}")
print(f"   Member files:  {MEMBERS_TIP}")
print(f"\nNew fields in wide master:")
print(f"  Waste    → Total Waste | Waste Recovered | Recovery Rate | Waste_Recovery_Rate_%")
print(f"  Elec/Co  → " + " | ".join(ELEC_CLEAN_COLS))
print(f"  Derived  → Total_Electricity_by_Country_GJ")
print('\n   Load in Streamlit:')
print('   df = pd.read_csv("data_storage/master/ESG_MASTER_WIDE_ALL_COMPANIES_2009_2023.csv")')

# ── Step 7: TIP aggregate ──────────────────────────────────────────────────────
print("\n[7/7] Writing TIP members aggregate to members/TIP/...")
tip_wide = MEMBERS_TIP / "ESG_MASTER_WIDE_TIP_MEMBERS_2009_2023.csv"
_drop_zero_elec_cols(df).to_csv(tip_wide, index=False)
tip_long = MEMBERS_TIP / "ESG_CONSOLIDATED_TIP_MEMBERS_2009_2023.csv"
raw.to_csv(tip_long, index=False)
print(f"    → TIP wide:  {tip_wide}")
print(f"    → TIP long:  {tip_long}")
print(f"\n✅ Done.")