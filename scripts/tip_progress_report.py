"""
scripts/tip_progress_report.py — TIP ESG Platform · Sector Progress Report
===========================================================================
Generates the annual TIP sector progress report as a formatted Excel workbook.
Shows year-on-year KPI trends across all TIP member companies.

Run from the project root:
    python scripts/tip_progress_report.py

Not imported by app.py — run as a standalone script only.
"""
import math
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from data_loader import get_tip_graph_data

TIP_CHARCOAL = "#2a2825"
TIP_SPRUCE = "#465c66"
TIP_SKY = "#b9c8d4"
TIP_SAND = "#cab6a5"
TIP_SAGE = "#c3cbb6"
REPORT_BG = "#f5f4f2"
BAR_COLOR = "#9fb7c9"
LINE_COLOR = TIP_SPRUCE
AXIS_COLOR = "#9aa1a9"
GRID_COLOR = "#e6eaed"
TEXT_COLOR = TIP_CHARCOAL
MUTED_TEXT = "#6f7882"
CHART_HEIGHT = 390
CHART_MARGIN_DUAL = dict(l=116, r=64, t=38, b=44)
CHART_MARGIN_SIMPLE = dict(l=78, r=50, t=38, b=94)

ENERGY_MIX_COLORS = {
    "Coal": "#2a2825",
    "Fuel oil": "#63724b",
    "LPG": "#d9c45f",
    "Natural gas": "#b9c8d4",
    "Non-renewable electricity": "#cfa5b7",
    "Renewable electricity": "#9cae7b",
    "Purchased steam": "#465c66",
    "Other": "#c7b6a3",
}

STATIC_HS_EXTERNAL = {2019: 54, 2020: 53, 2021: 56, 2022: 63, 2023: 70}
STATIC_HS_INTERNAL = {2019: 32, 2020: 33, 2021: 29, 2022: 32, 2023: 29}
STATIC_WOMEN_BOARD = {2019: 12, 2020: 11, 2021: 15, 2022: 15, 2023: 18}
STATIC_WOMEN_TOTAL = {2019: 13, 2020: 13, 2021: 14, 2022: 14, 2023: 15}
STATIC_TRWP_ANNUAL = {2019: 3, 2020: 1, 2021: 3, 2022: 4, 2023: 4}
STATIC_TRWP_CUMULATIVE = {2019: 12, 2020: 13, 2021: 16, 2022: 20, 2023: 24}
STATIC_TRWP_CITATIONS = {2019: 107, 2020: 249, 2021: 256, 2022: 480, 2023: 513}
STATIC_SBT_VALIDATED = {2019: 1, 2020: 2, 2021: 3, 2022: 3, 2023: 7}
STATIC_SBT_COMMITTED = {2019: 0, 2020: 0, 2021: 1, 2022: 3, 2023: 0}
STATIC_SBT_NOT_COMMITTED = {2019: 9, 2020: 8, 2021: 6, 2022: 4, 2023: 3}
STATIC_WATER_STRESS_SHARE = {2019: 19.5, 2020: 18.9, 2021: 19.1, 2022: 18.3, 2023: 18.0}


def render_tip_progress_report(sector_df, master_df=None):
    raw_data = get_tip_graph_data(sector_df)
    if not raw_data:
        st.warning("No sector data available.")
        return
    data = _clean_data(raw_data)
    if not data.get("years"):
        st.warning("No year data available.")
        return

    _, dropdown_col = st.columns([5, 1.25])
    with dropdown_col:
        selected_range = st.selectbox("Time Range", ["Last 5 years", "Last 3 years"], index=0, key="tip_progress_time_range")
    n_years = 5 if selected_range == "Last 5 years" else 3
    data = _latest_n(data, n_years)
    selected_years = data["years"]
    static_years = [2019, 2020, 2021, 2022, 2023][-n_years:]

    st.title("TIP Progress Report (Pathways 3, 4, 5)")
    st.subheader("Pathway 3 — Manufacturing")

    c1, c2 = st.columns(2)
    with c1:
        plot_dual_axis_report_chart(data, "energy", "energy_intensity", "Energy Consumption", "Total energy consumption (PJ)", "Energy intensity (GJ/t)", "Energy intensity", "energy")
    with c2:
        plot_dual_axis_report_chart(data, "co2", "co2_intensity", "CO₂ Emissions", "Total CO₂ emissions (Mt CO₂e)", "CO₂ intensity", "CO₂ intensity", "co2")

    c3, c4 = st.columns(2)
    with c3:
        plot_water_withdrawals_chart(data)
    with c4:
        plot_dual_axis_report_chart(data, "waste", "waste_intensity", "Waste", "Total waste generated (Mt)", "Waste intensity", "Waste intensity", "waste")

    c5, c6 = st.columns(2)
    with c5:
        plot_electricity_chart(data)
    with c6:
        plot_energy_mix_chart(master_df, selected_years)

    c7, c8 = st.columns(2)
    with c7:
        plot_sbt_chart(static_years)
    with c8:
        plot_iso_chart(data)

    c9, c10 = st.columns(2)
    with c9:
        plot_waste_breakdown_chart(master_df, selected_years)
    with c10:
        st.empty()

    st.subheader("Pathway 4 — Employees")
    c11, c12 = st.columns(2)
    with c11:
        plot_hs_chart(static_years)
    with c12:
        plot_women_chart(static_years)

    st.subheader("Pathway 5 — TRWP")
    c13, c14 = st.columns(2)
    with c13:
        plot_dual_axis_static_chart(
            static_years,
            [STATIC_TRWP_ANNUAL[y] for y in static_years],
            [STATIC_TRWP_CUMULATIVE[y] for y in static_years],
            "TRWP Publications",
            "Annual TRWP publications",
            "Cumulative TRWP publications",
            "Cumulative",
        )
    with c14:
        plot_simple_bar_report_chart(static_years, [STATIC_TRWP_CITATIONS[y] for y in static_years], "TRWP Citations", "Annual TRWP citations", bottom_values=True)


def _clean_data(raw_data: Dict[str, Any]) -> Dict[str, List[Any]]:
    cleaned = {k: _to_list(v) for k, v in raw_data.items()}
    if "years" in cleaned:
        cleaned["years"] = [_to_int_year(y) for y in cleaned["years"]]
        cleaned["years"] = [y for y in cleaned["years"] if y is not None]
    for key in cleaned:
        if key != "years":
            cleaned[key] = _to_float_list(cleaned[key])
    return _sort_by_year(cleaned)


def _to_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if hasattr(value, "tolist"):
        return value.tolist()
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _to_float_list(values: Sequence[Any]) -> List[Optional[float]]:
    out: List[Optional[float]] = []
    for value in values:
        try:
            out.append(None if value is None or (isinstance(value, float) and math.isnan(value)) else float(value))
        except Exception:
            out.append(None)
    return out


def _to_int_year(value: Any) -> Optional[int]:
    try:
        return int(float(value))
    except Exception:
        return None


def _sort_by_year(data: Dict[str, List[Any]]) -> Dict[str, List[Any]]:
    years = data.get("years", [])
    if not years:
        return data
    order = sorted(range(len(years)), key=lambda i: years[i])
    sorted_data = {"years": [years[i] for i in order]}
    for key, values in data.items():
        if key != "years":
            sorted_data[key] = [values[i] for i in order] if len(values) == len(years) else values
    return sorted_data


def _latest_n(data: Dict[str, List[Any]], n: int) -> Dict[str, List[Any]]:
    out = {"years": data.get("years", [])[-n:]}
    for key, values in data.items():
        if key != "years":
            out[key] = values[-n:]
    return out


def _align_series(years: List[Any], *series: List[Any]) -> Tuple[List[Any], ...]:
    min_len = len(years)
    for values in series:
        min_len = min(min_len, len(values))
    return tuple([years[-min_len:]] + [values[-min_len:] for values in series])


def _find_column(df: Optional[pd.DataFrame], candidates: Iterable[str]) -> Optional[str]:
    if df is None or df.empty:
        return None
    lookup = {str(c).strip().lower(): c for c in df.columns}
    for candidate in candidates:
        key = str(candidate).strip().lower()
        if key in lookup:
            return lookup[key]
    return None


def _sum_master_columns_by_year(master_df: Optional[pd.DataFrame], years: List[int], candidate_groups: List[List[str]]) -> Optional[List[float]]:
    if master_df is None or master_df.empty or "Year" not in master_df.columns:
        return None
    cols: List[str] = []
    for group in candidate_groups:
        col = _find_column(master_df, group)
        if col is not None and col not in cols:
            cols.append(col)
    if not cols:
        return None
    df = master_df.copy()
    df["Year"] = pd.to_numeric(df["Year"], errors="coerce").astype("Int64")
    df = df[df["Year"].isin(years)]
    if df.empty:
        return None
    for col in cols:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    grouped = df.groupby("Year")[cols].sum().sum(axis=1)
    return [float(grouped.get(y, 0.0)) for y in years]


def _scaled_values(values: List[Optional[float]], scale_type: Optional[str]) -> List[Optional[float]]:
    valid = [v for v in values if v is not None]
    if not valid:
        return values
    max_abs = max(abs(v) for v in valid)
    if scale_type in {"energy", "water", "waste"}:
        scale = 1_000_000 if max_abs > 10_000 else 1.0
    elif scale_type == "co2":
        scale = 1_000_000 if max_abs > 1_000 else 1.0
    else:
        scale = 1.0
    return [None if v is None else v / scale for v in values]


def _format_value(value: Any) -> str:
    if value is None:
        return ""
    try:
        value = float(value)
    except Exception:
        return ""
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if abs(value) >= 1000:
        return f"{value:,.0f}"
    if abs(value) >= 100:
        return f"{value:.0f}"
    if abs(value) >= 10:
        return f"{value:.1f}"
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _axis_range(values: List[Optional[float]], lower_pad: float = 0.25, upper_pad: float = 0.15, zero_floor: bool = True) -> Optional[List[float]]:
    valid = [v for v in values if v is not None]
    if not valid:
        return None
    v_min, v_max = min(valid), max(valid)
    if v_min == v_max:
        pad = abs(v_max) * 0.08 if v_max != 0 else 1
        low, high = v_min - pad, v_max + pad
    else:
        span = v_max - v_min
        low, high = v_min - span * lower_pad, v_max + span * upper_pad
    if zero_floor:
        low = max(0, low)
    return [low, high]


def _chart_config(filename: str = "tip_progress_chart") -> Dict[str, Any]:
    return {
        "displayModeBar": True,
        "displaylogo": False,
        "responsive": True,
        "toImageButtonOptions": {"format": "png", "filename": filename, "height": 900, "width": 1200, "scale": 2},
        "modeBarButtonsToRemove": ["lasso2d", "select2d"],
    }


def _apply_base_layout(fig: go.Figure, title: str, y1_label: str, y2_label: Optional[str] = None, y1_range=None, y2_range=None, margin=None) -> None:
    fig.update_layout(
        title=dict(text=title, x=0.02, font=dict(size=13, color=TEXT_COLOR)),
        height=CHART_HEIGHT,
        margin=margin or CHART_MARGIN_DUAL,
        plot_bgcolor=REPORT_BG,
        paper_bgcolor=REPORT_BG,
        showlegend=False,
        bargap=0.24,
        xaxis=dict(showline=True, linewidth=1, linecolor=AXIS_COLOR, showgrid=False, ticks="", tickfont=dict(size=11, color=MUTED_TEXT), zeroline=False),
        yaxis=dict(title=dict(text=y1_label, font=dict(size=12, color=MUTED_TEXT)), showline=True, linewidth=1, linecolor=AXIS_COLOR, showgrid=True, gridcolor=GRID_COLOR, gridwidth=1, ticks="", tickfont=dict(size=11, color=MUTED_TEXT), range=y1_range, zeroline=False),
    )
    if y2_label:
        fig.update_layout(yaxis2=dict(title=dict(text=y2_label, font=dict(size=12, color=MUTED_TEXT)), overlaying="y", side="right", showgrid=False, showline=True, linewidth=1, linecolor=AXIS_COLOR, ticks="", tickfont=dict(size=11, color=MUTED_TEXT), range=y2_range, zeroline=False))


def _add_dual_value_rows(fig, x, bar_values, line_values, line_label):
    fig.add_annotation(
        x=0.01,
        y=0.17,
        xref="paper",
        yref="paper",
        text="■ Absolute KPI",
        showarrow=False,
        font=dict(size=12, color=BAR_COLOR),
        align="left",
        xanchor="left",
    )
    fig.add_annotation(
        x=0.01,
        y=0.08,
        xref="paper",
        yref="paper",
        text=f"—○— {line_label}",
        showarrow=False,
        font=dict(size=12, color=LINE_COLOR),
        align="left",
        xanchor="left",
    )
    for i, x_pos in enumerate(x):
        fig.add_annotation(
            x=x_pos,
            y=0.17,
            xref="x",
            yref="paper",
            text=_format_value(bar_values[i]),
            showarrow=False,
            font=dict(size=11, color=MUTED_TEXT),
            align="center",
        )
        fig.add_annotation(
            x=x_pos,
            y=0.08,
            xref="x",
            yref="paper",
            text=_format_value(line_values[i]),
            showarrow=False,
            font=dict(size=11, color=MUTED_TEXT),
            align="center",
        )


def plot_dual_axis_report_chart(data, bar_key, line_key, title, y1_label, y2_label, line_label, bar_scale=None):
    years, bar, line = _align_series(
        data.get("years", []),
        data.get(bar_key, []),
        data.get(line_key, []),
    )
    if not years:
        st.info(f"No data available for {title}.")
        return

    bar = _scaled_values(bar, bar_scale)
    x = list(range(len(years)))
    year_labels = [str(y) for y in years]

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_bar(
        x=x,
        y=bar,
        marker=dict(color=BAR_COLOR),
        width=0.62,
        name="Absolute KPI",
    )
    fig.add_scatter(
        x=x,
        y=line,
        mode="lines",
        line=dict(color=LINE_COLOR, width=1.9),
        name=line_label,
        secondary_y=True,
    )

    _apply_base_layout(
        fig,
        title,
        y1_label,
        y2_label,
        _axis_range(bar, 0.10, 0.12, True),
        _axis_range(line, 0.22, 0.22, False),
        margin=dict(l=104, r=64, t=38, b=28),
    )

    fig.update_layout(
        height=430,
        yaxis=dict(domain=[0.30, 1.0]),
        yaxis2=dict(domain=[0.30, 1.0]),
        xaxis=dict(
            domain=[0.18, 1.0],
            tickmode="array",
            tickvals=x,
            ticktext=year_labels,
            showline=True,
            linewidth=1,
            linecolor=AXIS_COLOR,
            showgrid=False,
            ticks="",
            tickfont=dict(size=11, color=MUTED_TEXT),
            zeroline=False,
        ),
    )

    _add_dual_value_rows(fig, x, bar, line, line_label)
    st.plotly_chart(
        fig,
        use_container_width=True,
        config=_chart_config(title.replace(" ", "_").lower()),
    )


def plot_water_withdrawals_chart(data):
    years, water, intensity = _align_series(
        data.get("years", []),
        data.get("water", []),
        data.get("water_intensity", []),
    )
    if not years:
        st.info("No water data available.")
        return

    water = _scaled_values(water, "water")
    x = list(range(len(years)))
    year_labels = [str(y) for y in years]

    stressed = []
    non_stressed = []
    stress_pct_labels = []
    for i, year in enumerate(years):
        share = STATIC_WATER_STRESS_SHARE.get(int(year), 18.0)
        total = water[i] or 0
        stress_value = total * share / 100
        stressed.append(stress_value)
        non_stressed.append(total - stress_value)
        stress_pct_labels.append(share)

    totals = [(non_stressed[i] or 0) + (stressed[i] or 0) for i in range(len(years))]
    max_total = max(totals) if totals else 1

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_bar(x=x, y=non_stressed, marker=dict(color="#9cae7b"), width=0.62, name="Non-stress withdrawals")
    fig.add_bar(x=x, y=stressed, marker=dict(color="#b9c8d4"), width=0.62, name="Stress withdrawals")
    fig.add_scatter(
        x=x,
        y=intensity,
        mode="lines",
        line=dict(color=LINE_COLOR, width=1.9),
        name="Water intensity",
        secondary_y=True,
    )

    _apply_base_layout(
        fig,
        "Water Withdrawals",
        "Total water withdrawals (million m³)",
        "Water intensity",
        [0, max_total * 1.18],
        _axis_range(intensity, 0.22, 0.22, False),
        margin=dict(l=104, r=70, t=38, b=28),
    )
    fig.update_layout(
        height=430,
        barmode="stack",
        showlegend=False,
        xaxis=dict(domain=[0.18, 1.0], tickmode="array", tickvals=x, ticktext=year_labels, showline=True, linewidth=1, linecolor=AXIS_COLOR, showgrid=False, ticks="", tickfont=dict(size=11, color=MUTED_TEXT), zeroline=False),
        yaxis=dict(domain=[0.36, 1.0], title=dict(text="Total water withdrawals (million m³)", font=dict(size=12, color=MUTED_TEXT)), range=[0, max_total * 1.18], showgrid=True, gridcolor=GRID_COLOR, showline=True, linecolor=AXIS_COLOR, tickfont=dict(size=11, color=MUTED_TEXT), zeroline=False),
        yaxis2=dict(domain=[0.36, 1.0], title=dict(text="Water intensity", font=dict(size=12, color=MUTED_TEXT)), overlaying="y", side="right", range=_axis_range(intensity, 0.22, 0.22, False), showgrid=False, showline=True, linecolor=AXIS_COLOR, tickfont=dict(size=11, color=MUTED_TEXT), zeroline=False),
    )

    for i, x_pos in enumerate(x):
        if stressed[i] > 0:
            fig.add_annotation(x=x_pos, y=non_stressed[i] + stressed[i] / 2, text=f"{stress_pct_labels[i]:.1f}%", showarrow=False, font=dict(size=12, color=TEXT_COLOR))

    fig.add_annotation(x=0.01, y=0.25, xref="paper", yref="paper", text="■ Stress withdrawals", showarrow=False, font=dict(size=12, color="#b9c8d4"), align="left", xanchor="left")
    fig.add_annotation(x=0.01, y=0.15, xref="paper", yref="paper", text="■ Non-stress withdrawals", showarrow=False, font=dict(size=12, color="#9cae7b"), align="left", xanchor="left")
    fig.add_annotation(x=0.01, y=0.05, xref="paper", yref="paper", text="—○— Water intensity", showarrow=False, font=dict(size=12, color=LINE_COLOR), align="left", xanchor="left")

    for i, x_pos in enumerate(x):
        fig.add_annotation(x=x_pos, y=0.25, xref="x", yref="paper", text=_format_value(stressed[i]), showarrow=False, font=dict(size=11, color=MUTED_TEXT))
        fig.add_annotation(x=x_pos, y=0.15, xref="x", yref="paper", text=_format_value(non_stressed[i]), showarrow=False, font=dict(size=11, color=MUTED_TEXT))
        fig.add_annotation(x=x_pos, y=0.05, xref="x", yref="paper", text=_format_value(intensity[i]), showarrow=False, font=dict(size=11, color=MUTED_TEXT))

    st.plotly_chart(fig, use_container_width=True, config=_chart_config("water_withdrawals"))

def plot_electricity_chart(data):
    years, renewable, non_renewable = _align_series(
        data.get("years", []),
        data.get("renewable", []),
        data.get("non_renewable", []),
    )
    if not years:
        st.info("No electricity data available.")
        return

    x = list(range(len(years)))
    year_labels = [str(y) for y in years]
    renew_share = []
    nonrenew_share = []
    for i in range(len(years)):
        r = renewable[i] or 0
        nr = non_renewable[i] or 0
        total = r + nr
        renew_share.append(0 if total == 0 else r / total * 100)
        nonrenew_share.append(0 if total == 0 else nr / total * 100)

    fig = go.Figure()
    fig.add_bar(x=x, y=nonrenew_share, marker=dict(color=TIP_SAND), width=0.62, name="Non-renewable electricity (GJ)")
    fig.add_bar(x=x, y=renew_share, marker=dict(color=TIP_SPRUCE), width=0.62, name="Renewable electricity (GJ)")

    fig.update_layout(
        title=dict(text="Electricity from Renewable Sources", x=0.02, font=dict(size=13, color=TEXT_COLOR)),
        height=430,
        margin=dict(l=104, r=50, t=38, b=28),
        barmode="stack",
        plot_bgcolor=REPORT_BG,
        paper_bgcolor=REPORT_BG,
        showlegend=False,
        xaxis=dict(domain=[0.18, 1.0], tickmode="array", tickvals=x, ticktext=year_labels, showline=True, linecolor=AXIS_COLOR, showgrid=False, ticks="", tickfont=dict(size=11, color=MUTED_TEXT), zeroline=False),
        yaxis=dict(domain=[0.32, 1.0], title="Total electricity consumption (%)", range=[0, 100], showgrid=True, gridcolor=GRID_COLOR, showline=True, linecolor=AXIS_COLOR, tickfont=dict(size=11, color=MUTED_TEXT), zeroline=False),
    )

    for i, x_pos in enumerate(x):
        fig.add_annotation(x=x_pos, y=nonrenew_share[i] + renew_share[i] / 2, text=f"{renew_share[i]:.1f}%", showarrow=False, font=dict(size=11, color="white"))
        fig.add_annotation(x=x_pos, y=0.18, xref="x", yref="paper", text=_format_value(non_renewable[i]), showarrow=False, font=dict(size=11, color=MUTED_TEXT))
        fig.add_annotation(x=x_pos, y=0.08, xref="x", yref="paper", text=_format_value(renewable[i]), showarrow=False, font=dict(size=11, color=MUTED_TEXT))

    fig.add_annotation(x=0.01, y=0.18, xref="paper", yref="paper", text="■ Non-renewable electricity (GJ)", showarrow=False, font=dict(size=12, color=TIP_SAND), align="left", xanchor="left")
    fig.add_annotation(x=0.01, y=0.08, xref="paper", yref="paper", text="■ Renewable electricity (GJ)", showarrow=False, font=dict(size=12, color=TIP_SPRUCE), align="left", xanchor="left")

    st.plotly_chart(fig, use_container_width=True, config=_chart_config("electricity_renewable"))

def plot_energy_mix_chart(master_df, years):
    if master_df is None or master_df.empty:
        st.info("Energy mix requires master company-level data. Pass _CONSOLIDATED_DF from app.py.")
        return
    categories = [
        ("Coal", ENERGY_MIX_COLORS["Coal"], [["Coal"], ["Coal (all types)"], ["coal_sub"]]),
        ("Fuel oil", ENERGY_MIX_COLORS["Fuel oil"], [["Fuel Oil"], ["fuel_oil_heavy_a"]]),
        ("LPG", ENERGY_MIX_COLORS["LPG"], [["LPG"], ["lpg"]]),
        ("Natural gas", ENERGY_MIX_COLORS["Natural gas"], [["Natural Gas"], ["nat_gas"]]),
        ("Non-renewable electricity", ENERGY_MIX_COLORS["Non-renewable electricity"], [["Non-Renewable Electricity Purchased"], ["Non-renewable electricity purchased"], ["nonrenew_elec_purchased"]]),
        ("Renewable electricity", ENERGY_MIX_COLORS["Renewable electricity"], [["Renewable Electricity Purchased"], ["Renewable electricity purchased"], ["renew_elec_purchased"], ["Self-generated AND consumed electricity on-site"], ["self_gen_elec"]]),
        ("Purchased steam", ENERGY_MIX_COLORS["Purchased steam"], [["Purchased Steam"], ["purchased_steam"]]),
        ("Other", ENERGY_MIX_COLORS["Other"], [["Propane"], ["propane"], ["Diesel"], ["diesel"], ["Petrol"], ["petrol"], ["Biomass"], ["biomass"], ["Waste tires"], ["waste_tires_mt"], ["Other"], ["Other fuels"], ["other_fuels"]]),
    ]
    values_by_cat = {label: _sum_master_columns_by_year(master_df, years, candidates) for label, _, candidates in categories}
    if all(values is None for values in values_by_cat.values()):
        st.info("Energy mix source columns were not found in the master data.")
        return
    totals = []
    for i in range(len(years)):
        totals.append(sum((values[i] or 0) for values in values_by_cat.values() if values is not None and i < len(values)))
    shares: Dict[str, List[float]] = {}
    for label, _, _ in categories:
        vals = values_by_cat[label] or [0.0] * len(years)
        shares[label] = [0 if totals[i] == 0 else (vals[i] or 0) / totals[i] * 100 for i in range(len(years))]
    x = list(range(len(years)))
    year_labels = [str(y) for y in years]
    fig = go.Figure()
    for label, color, _ in categories:
        fig.add_bar(x=x, y=shares[label], name=label, marker=dict(color=color, line=dict(color=REPORT_BG, width=0.4)), width=0.62)
    fig.update_layout(title=dict(text="Energy Mix", x=0.02, font=dict(size=13)), height=CHART_HEIGHT, margin=dict(l=78, r=210, t=38, b=76), barmode="stack", plot_bgcolor=REPORT_BG, paper_bgcolor=REPORT_BG, xaxis=dict(tickmode="array", tickvals=x, ticktext=year_labels, showline=True, linecolor=AXIS_COLOR, showgrid=False, tickfont=dict(size=11, color=TEXT_COLOR)), yaxis=dict(title="Energy mix (%)", range=[0, 100], ticksuffix="%", dtick=10, showgrid=True, gridcolor=GRID_COLOR, showline=True, linecolor=AXIS_COLOR, tickfont=dict(size=11, color=TEXT_COLOR)), legend=dict(x=1.04, y=1.0, xanchor="left", yanchor="top", font=dict(size=10), bgcolor="rgba(0,0,0,0)"))
    for i, x_pos in enumerate(x):
        cumulative = 0.0
        for label, _, _ in categories:
            val = shares[label][i]
            if val >= 3.0:
                txt_color = "white" if label in {"Coal", "Purchased steam"} else TEXT_COLOR
                fig.add_annotation(x=x_pos, y=cumulative + val / 2, text=f"{val:.1f}%", showarrow=False, font=dict(size=11, color=txt_color))
            cumulative += val
    st.plotly_chart(fig, use_container_width=True, config=_chart_config("energy_mix"))


def plot_waste_breakdown_chart(master_df, years):
    if master_df is None or master_df.empty:
        st.info("Waste breakdown requires master company-level data. Pass _CONSOLIDATED_DF from app.py.")
        return
    recovery = _sum_master_columns_by_year(master_df, years, [["Amount of waste sent to recovery"], ["Waste Recovered"], ["waste_recovery"]])
    total = _sum_master_columns_by_year(master_df, years, [["Total amount of waste"], ["Total Waste"], ["waste_total"]])
    if recovery is None or total is None:
        st.info("Waste recovery/elimination columns were not found in the master data.")
        return
    recovery_mt = [(v or 0) / 1_000_000 for v in recovery]
    elimination_mt = [max((total[i] or 0) - (recovery[i] or 0), 0) / 1_000_000 for i in range(len(years))]
    x = list(range(len(years)))
    year_labels = [str(y) for y in years]
    fig = go.Figure()
    fig.add_bar(x=x, y=recovery_mt, marker=dict(color=BAR_COLOR), width=0.62, name="Recovery")
    fig.add_bar(x=x, y=elimination_mt, marker=dict(color=TIP_SPRUCE), width=0.62, name="Elimination")
    for i, x_pos in enumerate(x):
        if recovery_mt[i] > 0:
            fig.add_annotation(x=x_pos, y=recovery_mt[i] / 2, text=_format_value(recovery_mt[i]), showarrow=False, font=dict(size=11, color=TEXT_COLOR))
        if elimination_mt[i] > 0:
            fig.add_annotation(x=x_pos, y=recovery_mt[i] + elimination_mt[i] / 2, text=_format_value(elimination_mt[i]), showarrow=False, font=dict(size=11, color="white"))
    fig.update_layout(title=dict(text="Waste Recovery and Elimination", x=0.02, font=dict(size=13)), height=CHART_HEIGHT, margin=CHART_MARGIN_SIMPLE, barmode="stack", plot_bgcolor=REPORT_BG, paper_bgcolor=REPORT_BG, xaxis=dict(tickmode="array", tickvals=x, ticktext=year_labels, showline=True, linecolor=AXIS_COLOR, showgrid=False, tickfont=dict(size=11, color=MUTED_TEXT)), yaxis=dict(title="Waste sent for recovery or elimination (Mt)", showgrid=True, gridcolor=GRID_COLOR, showline=True, linecolor=AXIS_COLOR, tickfont=dict(size=11, color=MUTED_TEXT), range=_axis_range([a + b for a, b in zip(recovery_mt, elimination_mt)], 0.10, 0.15, True)), legend=dict(orientation="h", y=-0.22, x=0, font=dict(size=11)))
    st.plotly_chart(fig, use_container_width=True, config=_chart_config("waste_breakdown"))


def plot_sbt_chart(years):
    not_committed = [STATIC_SBT_NOT_COMMITTED[y] for y in years]
    committed = [STATIC_SBT_COMMITTED[y] for y in years]
    validated = [STATIC_SBT_VALIDATED[y] for y in years]
    x = list(range(len(years)))
    year_labels = [str(y) for y in years]
    fig = go.Figure()
    fig.add_bar(x=x, y=not_committed, name="Not committed", marker=dict(color=TIP_SKY), width=0.62)
    fig.add_bar(x=x, y=committed, name="Committed", marker=dict(color=TIP_SAGE), width=0.62)
    fig.add_bar(x=x, y=validated, name="Validated", marker=dict(color=TIP_SPRUCE), width=0.62)
    for i, x_pos in enumerate(x):
        y0 = 0
        for val, color in [(not_committed[i], TEXT_COLOR), (committed[i], TEXT_COLOR), (validated[i], "white")]:
            if val > 0:
                fig.add_annotation(x=x_pos, y=y0 + val / 2, text=str(val), showarrow=False, font=dict(size=9, color=color))
            y0 += val
    fig.update_layout(title=dict(text="Science-based Targets", x=0.02, font=dict(size=13)), height=CHART_HEIGHT, margin=CHART_MARGIN_SIMPLE, barmode="stack", plot_bgcolor=REPORT_BG, paper_bgcolor=REPORT_BG, xaxis=dict(tickmode="array", tickvals=x, ticktext=year_labels, showline=True, linecolor=AXIS_COLOR, showgrid=False, tickfont=dict(size=11, color=MUTED_TEXT)), yaxis=dict(title="Number of TIP members", range=[0, 10], showgrid=True, gridcolor=GRID_COLOR, showline=True, linecolor=AXIS_COLOR, tickfont=dict(size=11, color=MUTED_TEXT)), legend=dict(orientation="h", y=-0.22, x=0, font=dict(size=11)))
    st.plotly_chart(fig, use_container_width=True, config=_chart_config("science_based_targets"))


def plot_iso_chart(data):
    years, values = _align_series(data.get("years", []), data.get("iso", []))
    if not years:
        st.info("No ISO data available.")
        return
    x = list(range(len(years)))
    fig = go.Figure()
    fig.add_scatter(x=x, y=values, mode="lines", line=dict(color=LINE_COLOR, width=1.9))
    fig.update_layout(title=dict(text="ISO Certification", x=0.02, font=dict(size=13)), height=CHART_HEIGHT, margin=CHART_MARGIN_SIMPLE, plot_bgcolor=REPORT_BG, paper_bgcolor=REPORT_BG, showlegend=False, xaxis=dict(tickmode="array", tickvals=x, ticktext=[str(y) for y in years], showline=True, linecolor=AXIS_COLOR, showgrid=False, tickfont=dict(size=11, color=MUTED_TEXT)), yaxis=dict(title="ISO 14001-certified sites (%)", range=[95, 100], showgrid=True, gridcolor=GRID_COLOR, showline=True, linecolor=AXIS_COLOR, tickfont=dict(size=11, color=MUTED_TEXT)))
    st.plotly_chart(fig, use_container_width=True, config=_chart_config("iso_certification"))


def plot_hs_chart(years):
    external = [STATIC_HS_EXTERNAL[y] for y in years]
    internal = [STATIC_HS_INTERNAL[y] for y in years]
    x = list(range(len(years)))
    fig = go.Figure()
    fig.add_bar(x=x, y=external, marker=dict(color=TIP_SPRUCE), width=0.34, name="Externally audited")
    fig.add_bar(x=x, y=internal, marker=dict(color=TIP_SKY), width=0.34, name="Internally audited")
    for i, x_pos in enumerate(x):
        fig.add_annotation(x=x_pos - 0.17, y=external[i], text=f"{external[i]}%", showarrow=False, yshift=8, font=dict(size=10, color=MUTED_TEXT))
        fig.add_annotation(x=x_pos + 0.17, y=internal[i], text=f"{internal[i]}%", showarrow=False, yshift=8, font=dict(size=10, color=MUTED_TEXT))
    fig.update_layout(title=dict(text="H&S Management Systems", x=0.02, font=dict(size=13)), height=CHART_HEIGHT, margin=CHART_MARGIN_SIMPLE, plot_bgcolor=REPORT_BG, paper_bgcolor=REPORT_BG, barmode="group", xaxis=dict(tickmode="array", tickvals=x, ticktext=[str(y) for y in years], showline=True, linecolor=AXIS_COLOR, showgrid=False, tickfont=dict(size=11, color=MUTED_TEXT)), yaxis=dict(title="Sites with H&S system (%)", range=[0, 80], showgrid=True, gridcolor=GRID_COLOR, showline=True, linecolor=AXIS_COLOR, tickfont=dict(size=11, color=MUTED_TEXT)), legend=dict(orientation="h", y=-0.22, x=0, font=dict(size=11)))
    st.plotly_chart(fig, use_container_width=True, config=_chart_config("hs_management_systems"))


def plot_women_chart(years):
    board = [STATIC_WOMEN_BOARD[y] for y in years]
    total = [STATIC_WOMEN_TOTAL[y] for y in years]
    x = list(range(len(years)))
    fig = go.Figure()
    fig.add_scatter(x=x, y=board, mode="lines", name="Board of Directors", line=dict(color=TIP_SPRUCE, width=1.9))
    fig.add_scatter(x=x, y=total, mode="lines", name="Total employees", line=dict(color=TIP_SKY, width=1.9))
    fig.update_layout(title=dict(text="Women Representation", x=0.02, font=dict(size=13)), height=CHART_HEIGHT, margin=CHART_MARGIN_SIMPLE, plot_bgcolor=REPORT_BG, paper_bgcolor=REPORT_BG, xaxis=dict(tickmode="array", tickvals=x, ticktext=[str(y) for y in years], showline=True, linecolor=AXIS_COLOR, showgrid=False, tickfont=dict(size=11, color=MUTED_TEXT)), yaxis=dict(title="Women representation (%)", range=[0, 22], showgrid=True, gridcolor=GRID_COLOR, showline=True, linecolor=AXIS_COLOR, tickfont=dict(size=11, color=MUTED_TEXT)), legend=dict(orientation="h", y=-0.22, x=0, font=dict(size=11)))
    st.plotly_chart(fig, use_container_width=True, config=_chart_config("women_representation"))


def plot_dual_axis_static_chart(years, bar_values, line_values, title, y1_label, y2_label, line_label):
    x = list(range(len(years)))
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_bar(x=x, y=bar_values, marker=dict(color=BAR_COLOR), width=0.62, name="Annual")
    fig.add_scatter(x=x, y=line_values, mode="lines", line=dict(color=LINE_COLOR, width=1.9), name=line_label, secondary_y=True)
    _apply_base_layout(fig, title, y1_label, y2_label, _axis_range(bar_values, 0.20, 0.20, True), _axis_range(line_values, 0.20, 0.20, True), CHART_MARGIN_SIMPLE)
    fig.update_layout(xaxis=dict(tickmode="array", tickvals=x, ticktext=[str(y) for y in years], showline=True, linecolor=AXIS_COLOR), showlegend=True, legend=dict(orientation="h", y=-0.22, x=0, font=dict(size=11)))
    st.plotly_chart(fig, use_container_width=True, config=_chart_config(title.replace(" ", "_").lower()))


def plot_simple_bar_report_chart(years, values, title, y_label, bottom_values=False):
    x = list(range(len(years)))
    fig = go.Figure()
    fig.add_bar(x=x, y=values, marker=dict(color=BAR_COLOR), width=0.62)
    yaxis_layout = dict(title=y_label, showgrid=True, gridcolor=GRID_COLOR, showline=True, linecolor=AXIS_COLOR, range=_axis_range(values, 0.10, 0.18, True))
    if bottom_values:
        yaxis_layout["domain"] = [0.18, 1.0]
    fig.update_layout(title=dict(text=title, x=0.02, font=dict(size=13)), height=CHART_HEIGHT, margin=dict(l=78, r=50, t=38, b=44) if bottom_values else CHART_MARGIN_SIMPLE, plot_bgcolor=REPORT_BG, paper_bgcolor=REPORT_BG, showlegend=False, xaxis=dict(tickmode="array", tickvals=x, ticktext=[str(y) for y in years], showline=True, linecolor=AXIS_COLOR), yaxis=yaxis_layout)
    if bottom_values:
        for i, x_pos in enumerate(x):
            fig.add_annotation(x=x_pos, y=0.07, xref="x", yref="paper", text=_format_value(values[i]), showarrow=False, font=dict(size=11, color=MUTED_TEXT))
    else:
        for i, x_pos in enumerate(x):
            fig.add_annotation(x=x_pos, y=values[i], text=_format_value(values[i]), showarrow=False, yshift=8, font=dict(size=10, color=MUTED_TEXT))
    st.plotly_chart(fig, use_container_width=True, config=_chart_config(title.replace(" ", "_").lower()))