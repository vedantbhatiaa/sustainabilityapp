"""
pdf_report.py  —  TIP ESG Platform · One-Page Executive PDF Report
===================================================================
Generates a professional one-page A4 PDF matching the TIP ESG design system.

Layout (matches design spec):
  Top band   : TIP logo area · Company · Reporting Year · Verification stamp
  Row 1      : 4 KPI cards (CO₂ intensity, Renewable %, Water intensity, Waste recovery)
  Row 2      : CO₂ trend sparkline (5-year) · Fuel mix donut (text-based)
  Row 3      : Benchmark bands (all 6 KPI families)
  Footer     : Methodology · Data quality score · Platform link

Usage:
    from pdf_report import generate_executive_pdf
    pdf_bytes = generate_executive_pdf(company, year, kpi_data, bench_data)
    st.download_button("⬇ Download PDF", pdf_bytes, "ESG_Report.pdf", "application/pdf")

Dependencies: reportlab (pip install reportlab)
"""

from __future__ import annotations
import io
from datetime import date
from typing import Optional

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib.colors import (
        HexColor, white, black, Color
    )
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
        HRFlowable
    )
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib import colors as rl_colors
    from reportlab.graphics.shapes import (
        Drawing, Rect, String, Line, Circle, PolyLine
    )
    from reportlab.graphics import renderPDF
    from reportlab.pdfgen import canvas as rl_canvas
    REPORTLAB_OK = True
except ImportError:
    REPORTLAB_OK = False


# ── Colour palette ────────────────────────────────────────────────────────────
C_GREEN  = HexColor("#16A34A") if REPORTLAB_OK else None
C_AMBER  = HexColor("#F59E0B") if REPORTLAB_OK else None
C_RED    = HexColor("#DC2626") if REPORTLAB_OK else None
C_NAVY   = HexColor("#0A2240") if REPORTLAB_OK else None
C_BG     = HexColor("#F8FAFC") if REPORTLAB_OK else None
C_BORDER = HexColor("#E2E8F0") if REPORTLAB_OK else None
C_TEXT   = HexColor("#0F172A") if REPORTLAB_OK else None
C_MUTED  = HexColor("#64748B") if REPORTLAB_OK else None
C_CARD   = white if REPORTLAB_OK else None
C_CO2    = HexColor("#475569") if REPORTLAB_OK else None
C_ENERGY = HexColor("#F59E0B") if REPORTLAB_OK else None
C_WATER  = HexColor("#0891B2") if REPORTLAB_OK else None
C_WASTE  = HexColor("#7C3AED") if REPORTLAB_OK else None
C_RENEW  = HexColor("#16A34A") if REPORTLAB_OK else None


# ── Page geometry ─────────────────────────────────────────────────────────────
PAGE_W, PAGE_H = A4 if REPORTLAB_OK else (595, 842)
# Guard: mm is only available when reportlab imported successfully
_mm     = mm if REPORTLAB_OK else 2.8346   # 1 mm in points fallback
MARGIN  = 14 * _mm
CONTENT_W = PAGE_W - 2 * MARGIN
CONTENT_H = PAGE_H - 2 * MARGIN


def _draw_rounded_rect(c, x, y, w, h, r=None,
                        fill_color=None, stroke_color=None, stroke_width=0.5):
    """Draw a rounded rectangle on a canvas."""
    if fill_color:
        c.setFillColor(fill_color)
    if stroke_color:
        c.setStrokeColor(stroke_color)
        c.setLineWidth(stroke_width)
    if r is None: r = 3 * _mm
    c.roundRect(x, y, w, h, r,
                fill=1 if fill_color else 0,
                stroke=1 if stroke_color else 0)


def _draw_kpi_card(c, x, y, w, h, label, value_str, unit, delta_str,
                   delta_ok: bool = True, label_color=None):
    """Draw a single KPI card."""
    # Card background
    _draw_rounded_rect(c, x, y, w, h, r=2 * _mm,
                       fill_color=C_CARD, stroke_color=C_BORDER)

    # Label
    c.setFont("Helvetica", 7)
    c.setFillColor(C_MUTED)
    c.drawString(x + 8, y + h - 16, label.upper())

    # Value
    c.setFont("Helvetica-Bold", 20)
    c.setFillColor(label_color or C_TEXT)
    c.drawString(x + 8, y + h - 34, value_str)

    # Unit
    c.setFont("Helvetica", 8)
    c.setFillColor(C_MUTED)
    c.drawString(x + 8 + c.stringWidth(value_str, "Helvetica-Bold", 20) + 2,
                 y + h - 32, unit)

    # Delta chip
    if delta_str:
        chip_color = C_GREEN if delta_ok else C_RED
        chip_bg    = HexColor("#DCFCE7") if delta_ok else HexColor("#FEE2E2")
        cw = c.stringWidth(delta_str, "Helvetica", 7) + 8
        _draw_rounded_rect(c, x + 8, y + 7, cw, 12, r=1.5 * _mm, fill_color=chip_bg)
        c.setFont("Helvetica", 7)
        c.setFillColor(chip_color)
        c.drawString(x + 12, y + 11, delta_str)


def _draw_benchmark_band(c, x, y, w, label, value, q25, median, q75,
                          unit, lower_is_better=True):
    """Draw a horizontal benchmark band row."""
    bar_h   = 7
    track_h = 6
    label_w = 80

    # Label
    c.setFont("Helvetica", 7.5)
    c.setFillColor(C_MUTED)
    c.drawString(x, y + bar_h, label)

    # Track background
    tx = x + label_w
    tw = w - label_w - 40
    c.setFillColor(HexColor("#F1F5F9"))
    c.roundRect(tx, y, tw, track_h, 2, fill=1, stroke=0)

    # All values — compute safe range
    all_vals = [q25, median, q75, value]
    lo, hi = min(all_vals) * 0.85, max(all_vals) * 1.15
    rng = hi - lo or 1

    def px(v): return tx + (v - lo) / rng * tw

    # IQR band (Q1–Q3)
    iq_x1 = px(q25)
    iq_x2 = px(q75)
    c.setFillColor(HexColor("#DCFCE7"))
    c.roundRect(iq_x1, y, iq_x2 - iq_x1, track_h, 1.5, fill=1, stroke=0)

    # Median line
    mx = px(median)
    c.setStrokeColor(C_GREEN)
    c.setLineWidth(1.5)
    c.line(mx, y - 1, mx, y + track_h + 1)

    # Company marker (diamond)
    vx = px(value)
    c.setFillColor(C_NAVY)
    pts = [vx, y + track_h + 4,
           vx + 4, y + track_h / 2,
           vx, y - 3,
           vx - 4, y + track_h / 2]
    from reportlab.graphics.shapes import Polygon
    p = rl_canvas.Canvas.__new__(rl_canvas.Canvas)  # just need the circle
    c.setFillColor(C_NAVY)
    c.circle(vx, y + track_h / 2, 4, fill=1, stroke=0)

    # Value label
    c.setFont("Helvetica-Bold", 7)
    c.setFillColor(C_TEXT)
    c.drawString(tx + tw + 4, y + bar_h - 2, f"{value:.2f} {unit}")


def _draw_sparkline(c, x, y, w, h, values, color=None):
    """Draw a mini sparkline on the canvas."""
    if not values or len(values) < 2:
        return
    color = color or C_GREEN
    mn, mx = min(values), max(values)
    rng = mx - mn or 1
    step = w / (len(values) - 1)

    pts = []
    for i, v in enumerate(values):
        px = x + i * step
        py = y + (v - mn) / rng * h
        pts.append((px, py))

    c.setStrokeColor(color)
    c.setLineWidth(1.5)
    c.setLineCap(1)
    path = c.beginPath()
    path.moveTo(pts[0][0], pts[0][1])
    for px, py in pts[1:]:
        path.lineTo(px, py)
    c.drawPath(path, stroke=1, fill=0)

    # Dots at ends
    c.setFillColor(color)
    c.circle(pts[0][0], pts[0][1], 2, fill=1, stroke=0)
    c.circle(pts[-1][0], pts[-1][1], 2, fill=1, stroke=0)


def generate_executive_pdf(
    company: str,
    year: int,
    kpis: dict,
    bench: dict | None = None,
    co2_trend: list[float] | None = None,
    trend_years: list[int] | None = None,
    fuel_mix: dict | None = None,
    data_quality_score: int = 85,
    verified: bool = False,
    verified_date: str = "",
) -> bytes:
    """
    Generate the one-page executive PDF report.

    kpis dict keys:
        co2_kpi, energy_kpi, water_kpi, waste_recovery_pct,
        renew_elec_pct, total_co2, production,
        yoy_co2_pct, yoy_energy_pct, yoy_water_pct, yoy_waste_pct

    bench dict keys:
        {kpi_name: {q25, median, q75, unit, lower_is_better}}

    Returns: PDF as bytes (pass to st.download_button)
    """
    if not REPORTLAB_OK:
        return _fallback_pdf(company, year, kpis)

    buf = io.BytesIO()
    c   = rl_canvas.Canvas(buf, pagesize=A4)
    W, H = A4

    # ─── TOP BAND ─────────────────────────────────────────────────────────────
    band_h = 52
    c.setFillColor(C_NAVY)
    c.rect(0, H - band_h, W, band_h, fill=1, stroke=0)

    # TIP dot + name
    c.setFillColor(C_GREEN)
    c.circle(MARGIN, H - band_h / 2, 6, fill=1, stroke=0)
    c.setFont("Helvetica-Bold", 14)
    c.setFillColor(white)
    c.drawString(MARGIN + 12, H - band_h / 2 - 5, "TIP ESG Platform")
    c.setFont("Helvetica", 8)
    c.setFillColor(HexColor("#94A3B8"))
    c.drawString(MARGIN + 12, H - band_h / 2 + 9, "WBCSD Tire Industry Project")

    # Company + year (right side)
    c.setFont("Helvetica-Bold", 13)
    c.setFillColor(white)
    right_x = W - MARGIN
    c.drawRightString(right_x, H - band_h / 2 - 4, company)
    c.setFont("Helvetica", 9)
    c.setFillColor(HexColor("#94A3B8"))
    c.drawRightString(right_x, H - band_h / 2 + 12, f"Reporting Year {year}")

    # Verification stamp
    if verified:
        stamp_x = W / 2 - 40
        _draw_rounded_rect(c, stamp_x, H - band_h + 10, 80, 22, r=3 * _mm,
                           fill_color=HexColor("#166534"), stroke_color=None)
        c.setFont("Helvetica-Bold", 7)
        c.setFillColor(white)
        c.drawCentredString(stamp_x + 40, H - band_h + 22, "✓ DSS+ VERIFIED")
        c.setFont("Helvetica", 6)
        c.drawCentredString(stamp_x + 40, H - band_h + 13, verified_date or date.today().strftime("%d %b %Y"))

    cursor = H - band_h - 14   # top of content area

    # ─── ROW 1: 4 KPI CARDS ──────────────────────────────────────────────────
    card_h = 58
    card_w = (CONTENT_W - 9) / 4
    cards = [
        {
            "label":   "CO₂ Intensity",
            "value":   f"{kpis.get('co2_kpi', 0):.3f}",
            "unit":    "T.CO₂/T",
            "delta":   (f"{'▼' if kpis.get('yoy_co2_pct',0)<0 else '▲'} "
                        f"{abs(kpis.get('yoy_co2_pct',0)):.1f}%"),
            "ok":      kpis.get("yoy_co2_pct", 0) <= 0,
            "color":   C_CO2,
        },
        {
            "label":   "Renewable Electricity",
            "value":   f"{kpis.get('renew_elec_pct', 0):.1f}",
            "unit":    "%",
            "delta":   (f"{'▲' if kpis.get('yoy_renew_pct',0)>0 else '▼'} "
                        f"{abs(kpis.get('yoy_renew_pct',0)):.1f}%") if kpis.get('yoy_renew_pct') else "",
            "ok":      kpis.get("yoy_renew_pct", 0) >= 0,
            "color":   C_RENEW,
        },
        {
            "label":   "Water Intensity",
            "value":   f"{kpis.get('water_kpi', 0):.2f}",
            "unit":    "m³/T",
            "delta":   (f"{'▼' if kpis.get('yoy_water_pct',0)<0 else '▲'} "
                        f"{abs(kpis.get('yoy_water_pct',0)):.1f}%") if kpis.get('yoy_water_pct') else "",
            "ok":      kpis.get("yoy_water_pct", 0) <= 0,
            "color":   C_WATER,
        },
        {
            "label":   "Waste Recovery Rate",
            "value":   f"{kpis.get('waste_recovery_pct', 0):.1f}",
            "unit":    "%",
            "delta":   (f"{'▲' if kpis.get('yoy_waste_pct',0)>0 else '▼'} "
                        f"{abs(kpis.get('yoy_waste_pct',0)):.1f}%") if kpis.get('yoy_waste_pct') else "",
            "ok":      kpis.get("yoy_waste_pct", 0) >= 0,
            "color":   C_WASTE,
        },
    ]

    for i, card in enumerate(cards):
        cx = MARGIN + i * (card_w + 3)
        cy = cursor - card_h
        _draw_kpi_card(c, cx, cy, card_w, card_h,
                       card["label"], card["value"], card["unit"],
                       card["delta"], card["ok"], card["color"])

    cursor -= card_h + 10

    # ─── ROW 2: CO2 TREND + FUEL MIX ─────────────────────────────────────────
    row2_h = 80
    half_w = (CONTENT_W - 6) / 2

    # CO₂ trend card
    _draw_rounded_rect(c, MARGIN, cursor - row2_h, half_w, row2_h, r=2 * _mm,
                       fill_color=C_CARD, stroke_color=C_BORDER)
    c.setFont("Helvetica-Bold", 8)
    c.setFillColor(C_TEXT)
    c.drawString(MARGIN + 8, cursor - 12, "CO₂ Intensity Trend (5 Year)")
    c.setFont("Helvetica", 7)
    c.setFillColor(C_MUTED)
    c.drawString(MARGIN + 8, cursor - 22, "T.CO₂ per tonne of production")

    if co2_trend and len(co2_trend) >= 2:
        _draw_sparkline(c,
                        MARGIN + 8, cursor - row2_h + 10,
                        half_w - 16, row2_h - 38,
                        co2_trend[-5:], color=C_CO2)
        # Year labels
        yrs = (trend_years or list(range(year - len(co2_trend) + 1, year + 1)))[-5:]
        c.setFont("Helvetica", 6)
        c.setFillColor(C_MUTED)
        sp = (half_w - 16) / max(len(yrs) - 1, 1)
        for j, yr in enumerate(yrs):
            c.drawCentredString(MARGIN + 8 + j * sp, cursor - row2_h + 4, str(yr))

    # Fuel mix card
    fm_x = MARGIN + half_w + 6
    _draw_rounded_rect(c, fm_x, cursor - row2_h, half_w, row2_h, r=2 * _mm,
                       fill_color=C_CARD, stroke_color=C_BORDER)
    c.setFont("Helvetica-Bold", 8)
    c.setFillColor(C_TEXT)
    c.drawString(fm_x + 8, cursor - 12, "Energy Mix")
    c.setFont("Helvetica", 7)
    c.setFillColor(C_MUTED)
    c.drawString(fm_x + 8, cursor - 22, "Share of total energy by source")

    fuel_default = fuel_mix or {
        "Electricity": kpis.get("renew_elec_pct", 30),
        "Natural Gas":  40,
        "Other fuels":  30,
    }
    fm_colors = [C_RENEW, C_ENERGY, C_CO2, C_WATER, C_WASTE, C_AMBER]
    fy = cursor - 32
    for j, (fname, fval) in enumerate(list(fuel_default.items())[:5]):
        if fy < cursor - row2_h + 8: break
        bar_w = (half_w - 80) * fval / 100
        c.setFillColor(fm_colors[j % len(fm_colors)])
        c.rect(fm_x + 8, fy - 5, bar_w, 6, fill=1, stroke=0)
        c.setFont("Helvetica", 6.5)
        c.setFillColor(C_TEXT)
        c.drawString(fm_x + 8 + bar_w + 3, fy - 2, f"{fname} {fval:.0f}%")
        fy -= 12

    cursor -= row2_h + 10

    # ─── ROW 3: BENCHMARK BANDS ───────────────────────────────────────────────
    bm_label_h = 14
    bench_data = bench or {}
    default_bench = {
        "CO₂ Intensity (T.CO₂/T)":    {"q25":0.55, "median":0.68, "q75":0.82, "unit":"T/T",  "lib":True,  "val": kpis.get("co2_kpi", 0.65)},
        "Energy Intensity (GJ/T)":     {"q25":8.0,  "median":9.2,  "q75":10.5, "unit":"GJ/T", "lib":True,  "val": kpis.get("energy_kpi", 9.0)},
        "Water Intensity (m³/T)":      {"q25":5.5,  "median":7.0,  "q75":9.0,  "unit":"m³/T", "lib":True,  "val": kpis.get("water_kpi", 7.0)},
        "Waste Recovery Rate (%)":     {"q25":85,   "median":90,   "q75":95,   "unit":"%",    "lib":False, "val": kpis.get("waste_recovery_pct", 88)},
        "Renewable Electricity (%)":   {"q25":30,   "median":50,   "q75":72,   "unit":"%",    "lib":False, "val": kpis.get("renew_elec_pct", 45)},
    }

    # Benchmark section header
    _draw_rounded_rect(c, MARGIN, cursor - 16, CONTENT_W, 16, r=0,
                       fill_color=HexColor("#F8FAFC"), stroke_color=C_BORDER)
    c.setFont("Helvetica-Bold", 8)
    c.setFillColor(C_MUTED)
    c.drawString(MARGIN + 4, cursor - 12, "BENCHMARKING — TIP SECTOR QUARTILES")
    c.setFont("Helvetica", 7)
    c.setFillColor(C_MUTED)
    c.drawRightString(MARGIN + CONTENT_W - 4, cursor - 12, "● Company  ── Median  ▓ IQR band")
    cursor -= 16

    for bm_label, bd in default_bench.items():
        row_h = 22
        if cursor - row_h < MARGIN + 50: break
        _draw_benchmark_band(
            c, MARGIN + 4, cursor - row_h + 4,
            CONTENT_W - 8, bm_label,
            bd["val"], bd["q25"], bd["median"], bd["q75"],
            bd["unit"], bd["lib"],
        )
        cursor -= row_h

    # ─── FOOTER ───────────────────────────────────────────────────────────────
    foot_y = MARGIN + 4
    c.setFillColor(HexColor("#F1F5F9"))
    c.rect(0, foot_y - 4, W, 28, fill=1, stroke=0)

    c.setFont("Helvetica", 6.5)
    c.setFillColor(C_MUTED)
    c.drawString(MARGIN,
                 foot_y + 14,
                 "Methodology: GHG Protocol (Scope 1+2) · TIP KPI definitions v3.1 · "
                 "Emission factors: IEA 2023")
    c.drawString(MARGIN, foot_y + 5, f"Generated {date.today().strftime('%d %b %Y')} · TIP ESG Platform powered by dss+")

    # Data quality pill
    dq_color = C_GREEN if data_quality_score >= 80 else (C_AMBER if data_quality_score >= 60 else C_RED)
    pill_w = 70
    _draw_rounded_rect(c, W - MARGIN - pill_w, foot_y + 1, pill_w, 18, r=3 * _mm,
                       fill_color=HexColor("#DCFCE7") if data_quality_score >= 80
                                  else HexColor("#FEF3C7"),
                       stroke_color=None)
    c.setFont("Helvetica-Bold", 7)
    c.setFillColor(dq_color)
    c.drawCentredString(W - MARGIN - pill_w / 2, foot_y + 9,
                        f"Data Quality: {data_quality_score}%")

    c.save()
    buf.seek(0)
    return buf.read()


def _fallback_pdf(company: str, year: int, kpis: dict) -> bytes:
    """Minimal fallback if reportlab is not installed."""
    content = (
        f"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        f"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        f"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]"
        f"/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj\n"
        f"4 0 obj<</Length 44>>stream\nBT /F1 12 Tf 72 720 Td "
        f"(Install reportlab for full PDF) Tj ET\nendstream\nendobj\n"
        f"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
        f"xref\n0 6\n0000000000 65535 f\n"
        f"trailer<</Size 6/Root 1 0 R>>\nstartxref\n9\n%%EOF"
    )
    return content.encode()


def build_kpi_dict_from_outputs(inp, out, prev_out=None) -> dict:
    """
    Helper: build the kpis dict for generate_executive_pdf()
    directly from formula_engine TemplateInputs/Outputs.
    """
    def yoy(cur, prev):
        if prev and abs(prev) > 0:
            return (cur - prev) / abs(prev) * 100
        return None

    total_elec = inp.renew_elec_purchased + inp.nonrenew_elec_purchased + inp.self_gen_elec
    renew_pct  = (inp.renew_elec_purchased / total_elec * 100) if total_elec else 0

    kpis = {
        "co2_kpi":            out.co2_kpi,
        "energy_kpi":         out.energy_kpi,
        "water_kpi":          out.water_kpi,
        "waste_recovery_pct": out.waste_recovery_pct * 100,
        "renew_elec_pct":     renew_pct,
        "total_co2":          out.total_co2,
        "production":         inp.production,
    }
    if prev_out:
        kpis["yoy_co2_pct"]    = yoy(out.co2_kpi,    prev_out.co2_kpi)
        kpis["yoy_energy_pct"] = yoy(out.energy_kpi, prev_out.energy_kpi)
        kpis["yoy_water_pct"]  = yoy(out.water_kpi,  prev_out.water_kpi)
        kpis["yoy_waste_pct"]  = yoy(out.waste_recovery_pct, prev_out.waste_recovery_pct)
    return kpis