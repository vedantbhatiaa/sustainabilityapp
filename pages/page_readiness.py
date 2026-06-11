"""
pages/page_readiness.py — Submission readiness scoring with AI commentary.
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


def page_readiness():
    if not st.session_state.is_dss:
        st.error("This section is restricted to dss+ analysts and managers."); return

    st.markdown("## AI Readiness Check")
    st.caption("Select any company and reporting year to compute a live readiness score.")

    sel_co, sel_yr, inp, out, prev_inp, prev_out, hist = _dss_company_selector("ready")
    st.divider()

    # -- Compute live values ---------------------------------------------------
    flags        = validate_submission(inp, out, prev_out, threshold=20.0)
    completeness = _compute_completeness(inp, out)
    score, label = _compute_readiness_score(completeness, flags)
    n_errors     = sum(1 for f in flags if f.severity == "error")
    n_warnings   = sum(1 for f in flags if f.severity == "warning")

    renew_pct = (inp.renew_elec_purchased + inp.self_gen_elec) / max(out.total_electricity, 1) * 100
    prev_co2  = out.total_co2  # placeholder for YoY
    prev_e    = out.total_energy
    if prev_out:
        yoy_co2 = yoy_change(out.total_co2, prev_out.total_co2) or 0
        yoy_e   = yoy_change(out.total_energy, prev_out.total_energy) or 0
    else:
        yoy_co2 = yoy_e = 0

    # -- Gauge + summary -------------------------------------------------------
    col_score, col_info = st.columns([1, 3])
    with col_score:
        score_color = "#00916E" if score >= 80 else "#D97706" if score >= 60 else "#DC2626"
        fig = go.Figure(go.Indicator(
            mode="gauge+number", value=score,
            number=dict(suffix="/100", font=dict(size=32, color=score_color)),
            gauge=dict(
                axis=dict(range=[0,100]),
                bar=dict(color=score_color, thickness=.25),
                steps=[
                    dict(range=[0,60],  color="#FEE2E2"),
                    dict(range=[60,80], color="#FEF3C7"),
                    dict(range=[80,100],color="#D1FAE5"),
                ],
                threshold=dict(line=dict(color="#065F46",width=3), thickness=.75, value=score)
            )
        ))
        fig.update_layout(height=200, margin=dict(l=10,r=10,t=10,b=10), paper_bgcolor="rgba(0,0,0,0)")
        apply_chart_animation(fig)
        st.plotly_chart(fig, use_container_width=True)

    with col_info:
        st.markdown(f"### Report Readiness Score: **{score} / 100**")
        st.caption(f"{sel_co} · {sel_yr} Reporting Year · "
                   f"{n_errors} error{'s' if n_errors!=1 else ''}, "
                   f"{n_warnings} warning{'s' if n_warnings!=1 else ''}")
        if score >= 90:
            st.success(f"✅ {label} — submission can be included in consolidated report.")
        elif score >= 70:
            st.warning(f"⚠️ {label} — resolve open items before submission.")
        else:
            st.error(f"❌ {label} — significant data gaps must be addressed.")

        # Key live KPIs at a glance
        k1,k2,k3,k4 = st.columns(4)
        k1.metric("Energy KPI",   f"{out.energy_kpi:.2f} GJ/t")
        k2.metric("CO₂ KPI",      f"{out.co2_kpi:.3f} t/t")
        k3.metric("Water KPI",    f"{out.water_kpi:.2f} m³/t")
        k4.metric("Renewable %",  f"{renew_pct:.1f}%")

    st.divider()

    # -- Completeness by section -----------------------------------------------
    st.markdown("#### Data completeness by section")
    cols = st.columns(3)
    for i, (label_s, pct) in enumerate(completeness.items()):
        color = "#00916E" if pct == 100 else "#D97706" if pct >= 60 else "#DC2626"
        with cols[i % 3]:
            with st.container(border=True):
                st.caption(label_s)
                st.progress(pct / 100, text=f"{pct}%")

    st.divider()

    # ── ESG Analyst Chat (replaces old LLM insights) ──────────────────────────
    st.markdown("#### dss+ ESG Analyst")
    st.caption(f"Ask about {sel_co} {sel_yr} or any TIP company — powered by local AI (Ollama).")

    try:
        from chatbot.chatbot_engine import ESGChatbot
        _bot_key = f"_readiness_bot_{st.session_state.get('user_name','dss')}"
        if _bot_key not in st.session_state:
            st.session_state[_bot_key] = ESGChatbot(
                st.session_state.get("user_name", "dss_user"))
        _bot = st.session_state[_bot_key]

        _ok, _status = _bot.copilot.is_available()

        # Status bar
        _dot   = "🟢" if _ok else "🔴"
        _slabel = _bot.copilot.provider_label() if _ok else "Ollama not running — open from system tray"
        st.markdown(
            f'<div style="font-size:12px;color:#6B7280;margin-bottom:8px">'
            f'{_dot} {_slabel}</div>',
            unsafe_allow_html=True,
        )

        if not _ok:
            st.info("Start Ollama from your system tray, then reload this page.")
        else:
            # Quick-context chips for this company
            _chat_key = f"ai_msgs_{sel_co}_{sel_yr}"
            if _chat_key not in st.session_state:
                st.session_state[_chat_key] = []

            _msgs = st.session_state[_chat_key]

            # Render message history
            for _i, _m in enumerate(_msgs):
                _av = "👤" if _m["role"] == "user" else "🤖"
                with st.chat_message(_m["role"], avatar=_av):
                    st.markdown(_m["content"])
                    if _m.get("figure"):
                        st.plotly_chart(_m["figure"], use_container_width=True,
                                        key=f"ai_fig_{_i}")

            # Suggestion chips on empty state
            if not _msgs:
                _sugs = [
                    f"Summarise {sel_co} ESG performance in {sel_yr}",
                    f"Why did CO₂ intensity change for {sel_co.split()[0]}?",
                    f"Chart water intake for {sel_co.split()[0]} 2016–{sel_yr}",
                    f"Compare {sel_co.split()[0]} vs sector average in {sel_yr}",
                ]
                _sc = st.columns(2)
                for _si, _s in enumerate(_sugs):
                    with _sc[_si % 2]:
                        if st.button(_s, key=f"ai_chip_{_si}", use_container_width=True):
                            st.session_state[_chat_key].append(
                                {"role": "user", "content": _s, "figure": None})
                            with st.spinner("Thinking…"):
                                _resp = _bot.chat(_s)
                            st.session_state[_chat_key].append({
                                "role": "assistant",
                                "content": _resp.text,
                                "figure": _resp.figure,
                            })
                            st.rerun()

            # Chat input
            _q = st.chat_input(
                f"Ask about {sel_co} {sel_yr} or any ESG metric…",
                key=f"ai_input_{sel_co}_{sel_yr}",
            )
            if _q:
                st.session_state[_chat_key].append(
                    {"role": "user", "content": _q, "figure": None})
                with st.chat_message("user", avatar="👤"):
                    st.markdown(_q)

                with st.chat_message("assistant", avatar="🤖"):
                    _placeholder = st.empty()
                    _acc = ""
                    for _chunk in _bot.copilot.call_stream(
                        user_message  = _q,
                        data_context  = _bot.context.build_context_str(_q),
                        history       = _bot.history,
                        system_prompt = _bot.system_prompt,
                    ):
                        _acc += _chunk
                        _placeholder.markdown(_acc + "▌")

                    _placeholder.markdown(_acc)

                    _spec = _bot.graph.extract_spec(_acc)
                    _fig  = None
                    if _spec and not _bot.context.df.empty:
                        _fig = _bot.graph.build(_spec, _bot.context.df)
                        if _fig:
                            st.plotly_chart(_fig, use_container_width=True,
                                            key=f"ai_resp_fig_{len(_msgs)}")

                    _clean = _bot.graph.strip_spec(_acc)

                _bot.history.append({"role": "user",      "content": _q})
                _bot.history.append({"role": "assistant",  "content": _clean})
                if len(_bot.history) > 12:
                    _bot.history = _bot.history[-12:]
                _bot.logger.log(_q, _clean, _bot.classifier.classify(_q),
                                had_chart=(_fig is not None))

                st.session_state[_chat_key].append({
                    "role": "assistant", "content": _clean, "figure": _fig})
                st.rerun()

            # Clear button
            if _msgs:
                if st.button("🗑 Clear conversation", key="ai_clear_conv"):
                    st.session_state[_chat_key] = []
                    _bot.clear_history()
                    st.rerun()

    except ImportError:
        st.info("Chatbot module not available. Ensure chatbot/ folder is present.")
    except Exception as _e:
        st.error(f"Chat error: {_e}")