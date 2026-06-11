"""
components/render_waste_tab.py — Waste data section.
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


def render_waste_tab():
    inp, out = get_current_outputs()
    hist     = get_hist_outputs()
    rep_year = st.session_state.get("reporting_year", state.CURR_YEAR)
    st.markdown("#### Waste KPIs — Corporate Units")
    st.caption("Total waste must equal Recovery + Elimination. The consistency check validates this.")

    WASTE_ROWS = [
        ("section","Global Information",None,None,None),
        ("input","Total no. of sites","no.","total_sites",None),
        ("input","Production","metric t","production",None),
        ("section","Waste",None,None,None),
        ("input","Total amount of waste","metric t","waste_total",None),
        ("input","Amount of waste sent to recovery","metric t","waste_recovery",None),
        ("calc","Amount of waste sent to elimination","metric t",None,lambda i,o:f"{o.waste_elimination:,.0f}"),
        ("calc","Consistency check","—",None,lambda i,o:"OK" if o.check_waste else "Error"),
        ("calc","Recovery rate","%",None,lambda i,o:f"{o.waste_recovery_pct*100:.1f}%"),
        ("calc","Waste intensity","kg/T prod",None,lambda i,o:f"{i.waste_total/i.production*1000:.2f}" if i.production else "—"),
    ]
    data = []
    for rtype, label, unit, key, fn in WASTE_ROWS:
        if rtype == "section":
            row = {"Indicator": f"▸ {label}", "Unit": ""}
            for yr, hi, ho in hist: row[str(yr)] = ""
            row[str(rep_year)] = ""; row["YoY %"] = ""
            data.append({"_type":"section","_row":row}); continue
        row = {"Indicator": label, "Unit": unit or ""}
        hist_nums = []
        for yr, hi, ho in hist:
            v = getattr(hi, key, None) if key else None
            if v is None and fn: v = fn(hi, ho)
            try:
                row[str(yr)] = f"{int(round(float(v))):,}" if isinstance(v,(int,float)) else (str(v) if v else "—")
            except (TypeError, ValueError):
                row[str(yr)] = str(v) if v is not None else "—"
            try: hist_nums.append(float(str(v).replace(",","").replace("%","").replace("—","0")))
            except: hist_nums.append(0)
        cv = getattr(inp, key, None) if key else None
        if cv is None and fn: cv = fn(inp, out)
        row[str(rep_year)] = str(cv) if cv is not None else "—"
        try:
            cn = float(str(cv).replace(",","").replace("%",""))
            pn = hist_nums[-1] if hist_nums else 0
            row["YoY %"] = f"{(cn-pn)/abs(pn)*100:+.1f}%" if pn else "—"
        except: row["YoY %"] = "—"
        data.append({"_type":rtype,"_row":row})

    all_rows  = [d["_row"]  for d in data]
    all_types = [d["_type"] for d in data]
    df_w = pd.DataFrame(all_rows)
    curr_col = str(rep_year)

    def _style_waste(row, idx):
        rt = all_types[idx]
        return [
            "background:#F0FDF8;font-weight:700;color:#065F46" if rt == "section"
            else "background:#DBEAFE;font-weight:600" if (rt == "input" and col == curr_col)
            else "background:#F0F9FF" if rt == "input"
            else "background:#F8FAFC;font-style:italic;color:#6B7280"
            for col in df_w.columns
        ]

    st.dataframe(df_w.style.apply(lambda row: _style_waste(row, row.name), axis=1),
                 hide_index=True, use_container_width=True, height=400)
    st.divider()
    c1, c2, c3 = st.columns(3)
    c1.metric("Total Waste", f"{inp.waste_total:,.0f} T")
    c2.metric("Recovery Rate", f"{out.waste_recovery_pct*100:.1f}%")
    c3.metric("Consistency", "OK" if out.check_waste else "Error")