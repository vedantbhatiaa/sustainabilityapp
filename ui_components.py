"""
ui_components.py — TIP ESG Platform · UI Component Library
===========================================================
Shared CSS injection, HTML card builders, and chart layout helpers.
All functions return HTML strings or Plotly layout dicts — no page-level
Streamlit calls are made here.

Design tokens (colours, font sizes, border radii) are defined at the top
as module-level constants. Change them here to restyle the entire platform.
"""

from __future__ import annotations
import streamlit as st
import plotly.graph_objects as go

# ── Design tokens ─────────────────────────────────────────────────────────────
GREEN   = "#16A34A"
AMBER   = "#F59E0B"
RED     = "#DC2626"
NAVY    = "#0A2240"
BG      = "#F8FAFC"
CARD    = "#FFFFFF"
BORDER  = "#E2E8F0"
TEXT    = "#0F172A"
MUTED   = "#64748B"

# KPI category palette
CAT_CO2    = "#475569"   # slate
CAT_ENERGY = "#F59E0B"   # amber
CAT_WATER  = "#0891B2"   # cyan
CAT_WASTE  = "#7C3AED"   # violet
CAT_RENEW  = "#16A34A"   # green


# ── Global CSS (inject once per session) ──────────────────────────────────────

GLOBAL_CSS = """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap"
      rel="stylesheet">

<style>
/* ── Base typography ───────────────────────────────────────────────────── */
html, body, [data-testid="stApp"], .stMarkdown, .stText,
button, input, select, textarea {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
}

/* Tabular nums for all KPI values */
.kpi-value, .kpi-num, [data-kpi-num] {
    font-variant-numeric: tabular-nums !important;
}

/* ── Page fade-in ──────────────────────────────────────────────────────── */
@keyframes tipFadeIn {
    from { opacity: 0; transform: translateY(10px); }
    to   { opacity: 1; transform: translateY(0); }
}
.main .block-container {
    animation: tipFadeIn 350ms ease-out !important;
}

/* ── KPI card ──────────────────────────────────────────────────────────── */
.tip-kpi-card {
    background: #FFFFFF;
    border: 1px solid #E2E8F0;
    border-radius: 8px;
    padding: 20px 20px 16px;
    display: flex;
    flex-direction: column;
    gap: 4px;
    box-shadow: 0 1px 3px rgba(15,23,42,.04);
    animation: tipFadeIn 300ms ease-out both;
    transition: box-shadow 200ms, transform 200ms;
    cursor: default;
}
.tip-kpi-card:hover {
    box-shadow: 0 4px 12px rgba(15,23,42,.08);
    transform: translateY(-1px);
}
.tip-kpi-label {
    font-size: 12px;
    font-weight: 500;
    color: #64748B;
    text-transform: uppercase;
    letter-spacing: .5px;
    line-height: 1.3;
}
.tip-kpi-num {
    font-size: 30px;
    font-weight: 700;
    color: #0F172A;
    line-height: 1.1;
    font-variant-numeric: tabular-nums;
}
.tip-kpi-unit {
    font-size: 12px;
    color: #64748B;
    margin-left: 2px;
    font-weight: 400;
}
.tip-kpi-delta {
    display: inline-flex;
    align-items: center;
    gap: 3px;
    font-size: 12px;
    font-weight: 500;
    padding: 2px 7px;
    border-radius: 4px;
    margin-top: 4px;
    width: fit-content;
}
.tip-kpi-delta.pos { background: #DCFCE7; color: #166534; }
.tip-kpi-delta.neg { background: #FEE2E2; color: #991B1B; }
.tip-kpi-delta.neu { background: #F1F5F9; color: #475569; }
.tip-kpi-sparkline { margin-top: 6px; height: 36px; }

/* ── Skeleton shimmer ──────────────────────────────────────────────────── */
@keyframes tipShimmer {
    0%   { background-position: -400px 0; }
    100% { background-position: 400px 0; }
}
.tip-skeleton {
    background: linear-gradient(
        90deg,
        #F1F5F9 25%,
        #E2E8F0 50%,
        #F1F5F9 75%
    );
    background-size: 800px 100%;
    animation: tipShimmer 1.4s ease-in-out infinite;
    border-radius: 8px;
}
.tip-skeleton-card {
    height: 110px;
    border-radius: 8px;
}
.tip-skeleton-row {
    height: 16px;
    border-radius: 4px;
    margin-bottom: 8px;
}
.tip-skeleton-row.w80 { width: 80%; }
.tip-skeleton-row.w60 { width: 60%; }
.tip-skeleton-row.w40 { width: 40%; }
.tip-skeleton-chart {
    height: 200px;
    border-radius: 8px;
}

/* ── Status chips ──────────────────────────────────────────────────────── */
.tip-chip {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 3px 10px;
    border-radius: 4px;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: .2px;
    line-height: 1.4;
}
.tip-chip.complete  { background: #DCFCE7; color: #166534; }
.tip-chip.review    { background: #FEF3C7; color: #92400E; }
.tip-chip.issue     { background: #FEE2E2; color: #991B1B; }
.tip-chip.pending   { background: #F1F5F9; color: #475569; }
.tip-chip.approved  { background: #DBEAFE; color: #1E40AF; }

/* ── Section header ────────────────────────────────────────────────────── */
.tip-section-hdr {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 16px;
    padding-bottom: 4px;
}
.tip-section-title {
    font-size: 18px;
    font-weight: 700;
    color: #0F172A;
    letter-spacing: -.3px;
}
.tip-section-sub {
    font-size: 13px;
    color: #64748B;
    margin-top: 2px;
}

/* ── Company grid card ─────────────────────────────────────────────────── */
.tip-co-card {
    background: #FFFFFF;
    border: 1px solid #E2E8F0;
    border-radius: 8px;
    padding: 16px;
    display: flex;
    flex-direction: column;
    gap: 8px;
    transition: box-shadow 200ms, border-color 200ms;
    animation: tipFadeIn 300ms ease-out both;
}
.tip-co-card:hover {
    box-shadow: 0 4px 12px rgba(15,23,42,.08);
    border-color: #CBD5E1;
}
.tip-co-name {
    font-size: 14px;
    font-weight: 600;
    color: #0F172A;
}
.tip-co-meta {
    font-size: 11px;
    color: #64748B;
}

/* ── Empty state ───────────────────────────────────────────────────────── */
.tip-empty {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 64px 32px;
    text-align: center;
    gap: 12px;
}
.tip-empty-icon {
    font-size: 40px;
    opacity: .5;
}
.tip-empty-title {
    font-size: 16px;
    font-weight: 600;
    color: #0F172A;
}
.tip-empty-sub {
    font-size: 13px;
    color: #64748B;
    max-width: 280px;
    line-height: 1.6;
}

/* ── Sidebar active item pulse ─────────────────────────────────────────── */
@keyframes tipActivePulse {
    0%   { box-shadow: 0 0 0 0 rgba(22,163,74,.4); }
    70%  { box-shadow: 0 0 0 6px rgba(22,163,74,0); }
    100% { box-shadow: 0 0 0 0 rgba(22,163,74,0); }
}

/* ── Tab slide-fade ────────────────────────────────────────────────────── */
@keyframes tipTabSlide {
    from { opacity: 0; transform: translateX(6px); }
    to   { opacity: 1; transform: translateX(0); }
}
[data-testid="stTabPanel"] {
    animation: tipTabSlide 250ms ease-out !important;
}

/* ── Horizontal benchmark band ─────────────────────────────────────────── */
.tip-band-wrap {
    background: #FFFFFF;
    border: 1px solid #E2E8F0;
    border-radius: 8px;
    padding: 14px 18px;
    margin-bottom: 10px;
    animation: tipFadeIn 400ms ease-out both;
}
.tip-band-label {
    font-size: 12px;
    font-weight: 500;
    color: #64748B;
    margin-bottom: 6px;
}
.tip-band-track {
    position: relative;
    height: 8px;
    background: #F1F5F9;
    border-radius: 4px;
    margin: 8px 0;
}
.tip-band-range {
    position: absolute;
    height: 100%;
    background: #DCFCE7;
    border-radius: 4px;
}
.tip-band-marker {
    position: absolute;
    width: 14px;
    height: 14px;
    background: #16A34A;
    border: 2px solid #FFFFFF;
    border-radius: 50%;
    top: -3px;
    transform: translateX(-7px);
    box-shadow: 0 1px 4px rgba(0,0,0,.15);
}
.tip-band-ticks {
    display: flex;
    justify-content: space-between;
    font-size: 10px;
    color: #94A3B8;
    margin-top: 4px;
}

/* ── Report download button ────────────────────────────────────────────── */
.tip-download-btn {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    background: #16A34A;
    color: #ffffff !important;
    border: none;
    border-radius: 6px;
    padding: 8px 18px;
    font-size: 13px;
    font-weight: 500;
    cursor: pointer;
    transition: background 200ms, transform 200ms;
    text-decoration: none;
}
.tip-download-btn:hover {
    background: #15803D;
    transform: translateY(-1px);
}

/* ── Home activity feed ────────────────────────────────────────────────── */
.tip-activity-item {
    display: flex;
    align-items: flex-start;
    gap: 10px;
    padding: 10px 0;
    border-bottom: 1px solid #F1F5F9;
    font-size: 13px;
}
.tip-activity-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    margin-top: 4px;
    flex-shrink: 0;
}
.tip-activity-ts {
    font-size: 11px;
    color: #94A3B8;
    margin-top: 2px;
}

/* ── Plotly chart container fade-in ────────────────────────────────────── */
[data-testid="stPlotlyChart"] {
    animation: tipFadeIn 800ms ease-out both !important;
}

/* ── Bar chart rise-from-x-axis animation ──────────────────────────────── */
@keyframes barRise {
    0%   { clip-path: inset(100% 0 0% 0); opacity: 0; }
    8%   { opacity: 1; }
    100% { clip-path: inset(0% 0 0% 0);   opacity: 1; }
}

/* Apply to BOTH selector paths so stacked + grouped + single bars all match */
.js-plotly-plot .barlayer .point path,
.js-plotly-plot .barlayer .trace .point path {
    animation: barRise 1.3s cubic-bezier(0.16, 1, 0.3, 1) both;
    will-change: clip-path;
}
/* Stagger: each column (year) rises 100ms after the previous.
   Using BOTH .point and .trace .point selectors guarantees that
   bar #16 (year 2024) gets the same delay as bar #1 (year 2009) — no exceptions. */
.js-plotly-plot .barlayer .point:nth-child(1)  path { animation-delay: 0ms; }
.js-plotly-plot .barlayer .point:nth-child(2)  path { animation-delay: 100ms; }
.js-plotly-plot .barlayer .point:nth-child(3)  path { animation-delay: 200ms; }
.js-plotly-plot .barlayer .point:nth-child(4)  path { animation-delay: 300ms; }
.js-plotly-plot .barlayer .point:nth-child(5)  path { animation-delay: 400ms; }
.js-plotly-plot .barlayer .point:nth-child(6)  path { animation-delay: 500ms; }
.js-plotly-plot .barlayer .point:nth-child(7)  path { animation-delay: 600ms; }
.js-plotly-plot .barlayer .point:nth-child(8)  path { animation-delay: 700ms; }
.js-plotly-plot .barlayer .point:nth-child(9)  path { animation-delay: 800ms; }
.js-plotly-plot .barlayer .point:nth-child(10) path { animation-delay: 900ms; }
.js-plotly-plot .barlayer .point:nth-child(11) path { animation-delay: 1000ms; }
.js-plotly-plot .barlayer .point:nth-child(12) path { animation-delay: 1100ms; }
.js-plotly-plot .barlayer .point:nth-child(13) path { animation-delay: 1200ms; }
.js-plotly-plot .barlayer .point:nth-child(14) path { animation-delay: 1300ms; }
.js-plotly-plot .barlayer .point:nth-child(15) path { animation-delay: 1400ms; }
.js-plotly-plot .barlayer .point:nth-child(16) path { animation-delay: 1500ms; }
.js-plotly-plot .barlayer .point:nth-child(17) path { animation-delay: 1600ms; }
.js-plotly-plot .barlayer .point:nth-child(18) path { animation-delay: 1700ms; }
.js-plotly-plot .barlayer .point:nth-child(19) path { animation-delay: 1800ms; }
.js-plotly-plot .barlayer .point:nth-child(20) path { animation-delay: 1900ms; }
.js-plotly-plot .barlayer .point:nth-child(21) path { animation-delay: 2000ms; }
.js-plotly-plot .barlayer .point:nth-child(22) path { animation-delay: 2100ms; }
.js-plotly-plot .barlayer .point:nth-child(23) path { animation-delay: 2200ms; }
.js-plotly-plot .barlayer .point:nth-child(24) path { animation-delay: 2300ms; }
.js-plotly-plot .barlayer .point:nth-child(25) path { animation-delay: 2400ms; }

/* Stacked/trace variant — ensures 2024 (nth-child 16 in a 2009-2024 chart) syncs */
.js-plotly-plot .barlayer .trace .point:nth-child(1)  path { animation-delay: 0ms; }
.js-plotly-plot .barlayer .trace .point:nth-child(2)  path { animation-delay: 100ms; }
.js-plotly-plot .barlayer .trace .point:nth-child(3)  path { animation-delay: 200ms; }
.js-plotly-plot .barlayer .trace .point:nth-child(4)  path { animation-delay: 300ms; }
.js-plotly-plot .barlayer .trace .point:nth-child(5)  path { animation-delay: 400ms; }
.js-plotly-plot .barlayer .trace .point:nth-child(6)  path { animation-delay: 500ms; }
.js-plotly-plot .barlayer .trace .point:nth-child(7)  path { animation-delay: 600ms; }
.js-plotly-plot .barlayer .trace .point:nth-child(8)  path { animation-delay: 700ms; }
.js-plotly-plot .barlayer .trace .point:nth-child(9)  path { animation-delay: 800ms; }
.js-plotly-plot .barlayer .trace .point:nth-child(10) path { animation-delay: 900ms; }
.js-plotly-plot .barlayer .trace .point:nth-child(11) path { animation-delay: 1000ms; }
.js-plotly-plot .barlayer .trace .point:nth-child(12) path { animation-delay: 1100ms; }
.js-plotly-plot .barlayer .trace .point:nth-child(13) path { animation-delay: 1200ms; }
.js-plotly-plot .barlayer .trace .point:nth-child(14) path { animation-delay: 1300ms; }
.js-plotly-plot .barlayer .trace .point:nth-child(15) path { animation-delay: 1400ms; }
.js-plotly-plot .barlayer .trace .point:nth-child(16) path { animation-delay: 1500ms; }
.js-plotly-plot .barlayer .trace .point:nth-child(17) path { animation-delay: 1600ms; }
.js-plotly-plot .barlayer .trace .point:nth-child(18) path { animation-delay: 1700ms; }
.js-plotly-plot .barlayer .trace .point:nth-child(19) path { animation-delay: 1800ms; }
.js-plotly-plot .barlayer .trace .point:nth-child(20) path { animation-delay: 1900ms; }
.js-plotly-plot .barlayer .trace .point:nth-child(21) path { animation-delay: 2000ms; }
.js-plotly-plot .barlayer .trace .point:nth-child(22) path { animation-delay: 2100ms; }
.js-plotly-plot .barlayer .trace .point:nth-child(23) path { animation-delay: 2200ms; }
.js-plotly-plot .barlayer .trace .point:nth-child(24) path { animation-delay: 2300ms; }
.js-plotly-plot .barlayer .trace .point:nth-child(25) path { animation-delay: 2400ms; }

/* ── Pie / donut trace animation ───────────────────────────────────────── */
@keyframes pieSliceIn {
    from { opacity: 0; transform: scale(0.6); }
    to   { opacity: 1; transform: scale(1);   }
}
.js-plotly-plot .pielayer .trace {
    animation: pieSliceIn 1.0s cubic-bezier(0.34, 1.56, 0.64, 1) both;
}

/* ── Line chart draw animation ─────────────────────────────────────────── */
@keyframes lineDraw {
    from { stroke-dashoffset: 2000; opacity: 0.2; }
    to   { stroke-dashoffset: 0;    opacity: 1;   }
}
.js-plotly-plot .scatterlayer .trace .lines path {
    stroke-dasharray: 2000;
    animation: lineDraw 1.8s ease-out both;
}

/* ── Scatter dots pop in ────────────────────────────────────────────────── */
@keyframes dotPop {
    from { transform: scale(0); opacity: 0; }
    to   { transform: scale(1); opacity: 1; }
}
.js-plotly-plot .scatterlayer .trace .points path {
    transform-box: fill-box;
    transform-origin: center;
    animation: dotPop 0.7s cubic-bezier(0.34, 1.56, 0.64, 1) both;
}

/* ── Streamlit metric cards ────────────────────────────────────────────── */
[data-testid="stMetric"] {
    animation: tipFadeIn 400ms ease-out both;
}

/* ── Tab content slide-fade ────────────────────────────────────────────── */
[data-testid="stTabPanel"],
[role="tabpanel"] {
    animation: tipTabSlide 250ms ease-out !important;
}

/* ── Plotly modebar fade on hover ──────────────────────────────────────── */
[data-testid="stPlotlyChart"] .modebar-container {
    opacity: 0;
    transition: opacity 200ms;
}
[data-testid="stPlotlyChart"]:hover .modebar-container {
    opacity: 1;
}

/* ── Sidebar override with new nav ─────────────────────────────────────── */
[data-testid="stSidebar"] { background: #0A2240 !important; }
[data-testid="stSidebar"] * { color: rgba(255,255,255,0.75) !important; }
[data-testid="stSidebar"] h1,[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3,[data-testid="stSidebar"] strong
{ color: #ffffff !important; }
[data-testid="stSidebar"] hr { border-color: rgba(255,255,255,0.1) !important; }
[data-testid="stSidebarNav"] { display: none; }
[data-testid="stSidebar"] .stButton > button {
    background: transparent !important;
    color: rgba(255,255,255,0.75) !important;
    border: none !important;
    border-radius: 8px !important;
    font-size: 13px !important;
    font-weight: 500 !important;
    text-align: left !important;
    padding: 8px 12px !important;
    width: 100% !important;
    transition: background .15s, color .15s !important;
}
[data-testid="stSidebar"] .stButton > button:hover {
    background: rgba(255,255,255,.08) !important;
    color: #ffffff !important;
}
</style>
"""

# ── Counter-up JS ─────────────────────────────────────────────────────────────

COUNTER_JS = """
<script>
(function() {
  function easeOutQuart(t) { return 1 - Math.pow(1 - t, 4); }

  function countUp(el, target, duration, decimals) {
    var startTime = null;
    function step(ts) {
      if (!startTime) startTime = ts;
      var progress = Math.min((ts - startTime) / duration, 1);
      var val = target * easeOutQuart(progress);
      el.textContent = decimals > 0
        ? val.toFixed(decimals)
        : Math.round(val).toLocaleString();
      if (progress < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
  }

  function initCounters(doc) {
    var els = doc.querySelectorAll('[data-count-to]:not([data-counted])');
    els.forEach(function(el) {
      el.dataset.counted = '1';
      countUp(el,
        parseFloat(el.dataset.countTo  || '0'),
        parseInt(el.dataset.countDur   || '800'),
        parseInt(el.dataset.countDec   || '0')
      );
    });
  }

  // Run in main page via window.parent
  function run() {
    try { initCounters(window.parent.document); } catch(e) {}
    try { initCounters(document); } catch(e) {}
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', run);
  } else { run(); }

  // Poll every 1.5s for new elements injected by Streamlit re-renders
  setInterval(run, 1500);
})();
</script>
"""


def inject_global_css() -> None:
    """Inject the full design system CSS + counter-up JS + animation-force JS."""
    st.markdown(GLOBAL_CSS, unsafe_allow_html=True)
    st.components.v1.html(COUNTER_JS, height=0)
    # Force bar/line animations to restart whenever Streamlit swaps chart DOM nodes.
    # Streamlit replaces chart divs on key change, but the browser may reuse GPU layers
    # causing clip-path animations to skip.  This MutationObserver detects new plotly
    # chart nodes and explicitly resets + replays the animation.
    st.components.v1.html("""<script>
(function() {
  function forceAnim(root) {
    var doc = root || (window.parent && window.parent.document) || document;
    var els = doc.querySelectorAll(
      '.js-plotly-plot .barlayer .point path, ' +
      '.js-plotly-plot .scatterlayer .trace .lines path'
    );
    els.forEach(function(el) {
      el.style.animation = 'none';
      void el.offsetWidth;          // trigger reflow
      el.style.animation = '';
    });
  }
  // Run once after initial render
  setTimeout(function() { forceAnim(); }, 400);

  // Watch for any Streamlit chart replacement
  var doc = (window.parent && window.parent.document) || document;
  var obs = new MutationObserver(function(mutations) {
    mutations.forEach(function(m) {
      m.addedNodes.forEach(function(node) {
        if (node.nodeType === 1) {
          var charts = node.querySelectorAll
            ? node.querySelectorAll('.js-plotly-plot')
            : [];
          if (charts.length > 0 || (node.classList && node.classList.contains('js-plotly-plot'))) {
            setTimeout(function() { forceAnim(); }, 50);
          }
        }
      });
    });
  });
  obs.observe(doc.body || doc, { childList: true, subtree: true });
})();
</script>""", height=0)


def page_fade() -> None:
    """Inject a single-use page fade marker (the CSS handles the animation)."""
    pass  # Animation runs via .main .block-container CSS rule automatically


# ── Component helpers ─────────────────────────────────────────────────────────

def kpi_card_html(
    label: str,
    value: float,
    unit: str,
    delta_pct: float | None = None,
    lower_is_better: bool = True,
    decimals: int = 0,
    prefix: str = "",
    suffix: str = "",
    color: str = TEXT,
    anim_delay: int = 0,        # ms stagger delay
) -> str:
    """
    Returns HTML for an animated KPI card with counter-up.
    The number animates from 0 → value on render.
    """
    import html as _h
    safe_label = _h.escape(str(label))
    safe_unit  = _h.escape(str(unit))

    # Delta chip
    delta_html = ""
    if delta_pct is not None:
        is_good = (delta_pct <= 0) if lower_is_better else (delta_pct >= 0)
        cls     = "pos" if is_good else "neg"
        arrow   = "▼" if delta_pct < 0 else "▲"
        sign    = "+" if delta_pct > 0 else ""
        delta_html = f'<div class="tip-kpi-delta {cls}">{arrow} {sign}{delta_pct:.1f}% YoY</div>'

    # Counter-up data attributes
    data_attrs = (
        f'data-count-to="{value}" '
        f'data-count-dur="800" '
        f'data-count-dec="{decimals}" '
        f'data-count-pre="{_h.escape(prefix)}" '
        f'data-count-suf="{_h.escape(suffix)}"'
    )

    delay_style = f"animation-delay:{anim_delay}ms;" if anim_delay else ""

    return f"""
    <div class="tip-kpi-card" style="{delay_style}">
      <div class="tip-kpi-label">{safe_label}</div>
      <div>
        <span class="tip-kpi-num" style="color:{color}" {data_attrs}>
          {prefix}{value:,.{decimals}f}{suffix}
        </span>
        <span class="tip-kpi-unit">{safe_unit}</span>
      </div>
      {delta_html}
    </div>"""


def skeleton_card_html(n: int = 1) -> str:
    """Returns HTML for n skeleton loader cards (600ms shimmer)."""
    card = """
    <div class="tip-kpi-card" style="gap:10px">
      <div class="tip-skeleton tip-skeleton-row w60"></div>
      <div class="tip-skeleton tip-skeleton-row" style="height:28px;width:50%"></div>
      <div class="tip-skeleton tip-skeleton-row w40"></div>
    </div>"""
    return card * n


def skeleton_chart_html() -> str:
    return '<div class="tip-skeleton tip-skeleton-chart"></div>'


def status_chip_html(status: str) -> str:
    """
    status: 'complete' | 'review' | 'issue' | 'pending' | 'approved'
    """
    labels = {
        "complete": ("Complete", "✓"),
        "review":   ("In Review", "⟳"),
        "issue":    ("Issue", "!"),
        "pending":  ("Pending", "…"),
        "approved": ("Approved", "✓"),
    }
    label, icon = labels.get(status.lower(), (status.title(), ""))
    return f'<span class="tip-chip {status.lower()}">{icon} {label}</span>'


def section_header_html(
    title: str,
    subtitle: str = "",
    badge: str = "",
    badge_color: str = GREEN,
) -> str:
    import html as _h
    sub_html   = f'<div class="tip-section-sub">{_h.escape(subtitle)}</div>' if subtitle else ""
    badge_html = (
        f'<span style="background:{badge_color}20;color:{badge_color};'
        f'font-size:11px;font-weight:600;padding:3px 10px;border-radius:4px">'
        f'{_h.escape(badge)}</span>'
    ) if badge else ""
    return f"""
    <div class="tip-section-hdr">
      <div>
        <div class="tip-section-title">{_h.escape(title)}</div>
        {sub_html}
      </div>
      {badge_html}
    </div>"""


def empty_state_html(icon: str, title: str, subtitle: str, cta: str = "") -> str:
    import html as _h
    cta_html = (
        f'<div style="font-size:13px;color:{GREEN};font-weight:500;'
        f'margin-top:4px;cursor:pointer">{_h.escape(cta)}</div>'
    ) if cta else ""
    return f"""
    <div class="tip-empty">
      <div class="tip-empty-icon">{icon}</div>
      <div class="tip-empty-title">{_h.escape(title)}</div>
      <div class="tip-empty-sub">{_h.escape(subtitle)}</div>
      {cta_html}
    </div>"""


def co_card_html(
    company: str,
    status: str,
    year: int,
    kpis: dict,
    anim_delay: int = 0,
) -> str:
    """Company grid card for Portfolio page."""
    import html as _h
    chip  = status_chip_html(status)
    co2   = kpis.get("co2_kpi", 0)
    nrg   = kpis.get("energy_kpi", 0)
    h2o   = kpis.get("water_kpi", 0)
    delay = f"animation-delay:{anim_delay}ms;" if anim_delay else ""
    return f"""
    <div class="tip-co-card" style="{delay}">
      <div style="display:flex;justify-content:space-between;align-items:flex-start">
        <div class="tip-co-name">{_h.escape(company)}</div>
        {chip}
      </div>
      <div class="tip-co-meta">{year} data · 3 KPIs</div>
      <div style="display:flex;gap:12px;margin-top:4px">
        <div style="font-size:11px;color:{CAT_CO2}">
          CO₂ <strong style="font-size:13px">{co2:.3f}</strong> T/T
        </div>
        <div style="font-size:11px;color:{CAT_ENERGY}">
          Energy <strong style="font-size:13px">{nrg:.1f}</strong> GJ/T
        </div>
        <div style="font-size:11px;color:{CAT_WATER}">
          Water <strong style="font-size:13px">{h2o:.1f}</strong> m³/T
        </div>
      </div>
    </div>"""


def apply_chart_animation(fig: go.Figure, duration: int = 600) -> go.Figure:
    """
    Add Plotly transition + consistent styling to any figure.
    The transition animates when Streamlit re-renders on filter changes.
    Chart containers also get CSS fade-in from the global stylesheet.
    """
    fig.update_layout(
        transition=dict(
            duration=duration,
            easing="cubic-in-out",
            ordering="traces first",
        ),
        font=dict(family="Inter, -apple-system, sans-serif", size=11),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        hoverlabel=dict(
            bgcolor="#FFFFFF",
            bordercolor="#E2E8F0",
            font=dict(family="Inter, sans-serif", size=12),
        ),
        modebar=dict(
            bgcolor="rgba(0,0,0,0)",
            color="#94A3B8",
            activecolor="#0F172A",
        ),
    )
    # Consistent axis styling on all axes
    axis_style = dict(
        gridcolor="#F1F5F9",
        linecolor="#E2E8F0",
        tickfont=dict(size=11, color="#64748B"),
        zeroline=False,
    )
    fig.update_xaxes(**axis_style)
    fig.update_yaxes(**axis_style)
    return fig


def chart_layout_defaults(
    title: str = "",
    height: int = 320,
    showlegend: bool = True,
) -> dict:
    """Standard layout kwargs including properly visible axes for TIP report alignment."""
    return dict(
        title=dict(
            text=f"<b>{title}</b>" if title else "",
            font=dict(size=14, color="#1C2E3F", family="Arial, sans-serif"),
            x=0, xanchor="left",
        ),
        height=height,
        margin=dict(l=55, r=115, t=50, b=55),
        paper_bgcolor="#FFFFFF",
        plot_bgcolor="#FFFFFF",
        font=dict(family="Arial, sans-serif", color="#1C2E3F", size=12),
        showlegend=showlegend,
        legend=dict(
            orientation="h", y=-0.22, x=0.5, xanchor="center",
            font=dict(size=11, color="#1C2E3F"),
            bgcolor="rgba(0,0,0,0)",
        ),
        hoverlabel=dict(
            bgcolor="#FFFFFF", bordercolor="#E2E8F0",
            font=dict(family="Arial", size=12),
        ),
    )


def sparkline_html(values: list[float], color: str = GREEN, height: int = 36) -> str:
    """Tiny inline SVG sparkline for KPI cards."""
    if not values or len(values) < 2:
        return ""
    mn, mx = min(values), max(values)
    rng    = mx - mn or 1
    w, h   = 80, height
    step   = w / max(len(values) - 1, 1)
    pts    = " ".join(
        f"{i * step:.1f},{h - (v - mn) / rng * h:.1f}"
        for i, v in enumerate(values)
    )
    return (
        f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
        f'xmlns="http://www.w3.org/2000/svg" style="overflow:visible">'
        f'<polyline points="{pts}" fill="none" stroke="{color}" '
        f'stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>'
        f'</svg>'
    )