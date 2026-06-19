"""
pdf_charts.py — TIP ESG Platform
Matplotlib chart generators for PDF embedding (no kaleido needed).
All functions return bytes (PNG).
"""
from __future__ import annotations
import io, numpy as np

C = {"navy":"#0A2240","green":"#16A34A","amber":"#F59E0B","red":"#DC2626",
     "water":"#0891B2","waste":"#7C3AED","energy":"#F59E0B","co2":"#475569",
     "muted":"#64748B","bg":"#F8FAFC","border":"#E2E8F0"}

def _mpl():
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.patches as mp
    return plt, mp

def _save(fig, dpi=150):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight",
                facecolor="white", edgecolor="none",
                pad_inches=0.15)   # padding so labels/legend are never clipped
    buf.seek(0); data = buf.read(); buf.close()
    try:
        import matplotlib.pyplot as plt; plt.close(fig)
    except: pass
    return data

def _base(ax, title="", ylabel="", xlabel="Year"):
    ax.set_facecolor("white")
    if title: ax.set_title(title, fontsize=9, fontweight="bold", color=C["navy"], pad=6, loc="left")
    if ylabel: ax.set_ylabel(ylabel, fontsize=7, color=C["muted"])
    if xlabel: ax.set_xlabel(xlabel, fontsize=7, color=C["muted"])
    ax.tick_params(colors=C["muted"], labelsize=7)
    for s in ax.spines.values(): s.set_edgecolor(C["border"]); s.set_linewidth(0.5)
    ax.yaxis.grid(True, color=C["border"], linewidth=0.4, linestyle="--"); ax.set_axisbelow(True)

def area_line(x, y, title="", ylabel="", color=None, fill_alpha=0.12):
    plt, _ = _mpl(); color = color or C["co2"]
    fig, ax = plt.subplots(figsize=(5.0, 2.4)); _base(ax, title, ylabel)
    ax.plot(x, y, color=color, linewidth=1.8, zorder=3)
    ax.fill_between(x, y, alpha=fill_alpha, color=color); ax.margins(x=0.02)
    return _save(fig)

def stacked_area(x, y_dict, title="", ylabel="", color_dict=None):
    plt, _ = _mpl()
    fig, ax = plt.subplots(figsize=(5.0, 2.4)); _base(ax, title, ylabel)
    labels = list(y_dict.keys())
    colors = [color_dict.get(l, C["co2"]) for l in labels] if color_dict else None
    ax.stackplot(x, *[y_dict[l] for l in labels], labels=labels, colors=colors, alpha=0.8)
    ax.legend(fontsize=7, loc="upper left", framealpha=0.6); ax.margins(x=0.02)
    return _save(fig)

def bar_chart(x, y, title="", ylabel="", color=None, hline=None, hline_label=""):
    plt, _ = _mpl(); color = color or C["water"]
    fig, ax = plt.subplots(figsize=(5.0, 2.4)); _base(ax, title, ylabel)
    ax.bar(x, y, color=color, width=0.6, alpha=0.85, edgecolor="white")
    if hline is not None:
        ax.axhline(hline, color=C["green"], linewidth=1.2, linestyle="--", label=hline_label)
        ax.legend(fontsize=7)
    ax.margins(x=0.04); return _save(fig)

def stacked_bar(x, y_dict, title="", ylabel="", color_dict=None, pct_mode=False):
    plt, _ = _mpl()
    fig, ax = plt.subplots(figsize=(5.0, 2.4)); _base(ax, title, ylabel)
    labels  = [l for l in y_dict if any(v > 0 for v in y_dict[l])]
    bottom  = np.zeros(len(x))
    for lbl in labels:
        vals = np.array(y_dict[lbl], dtype=float)
        col  = color_dict.get(lbl, C["co2"]) if color_dict else C["co2"]
        ax.bar(x, vals, bottom=bottom, label=lbl, color=col, width=0.6, alpha=0.9, edgecolor="white")
        bottom += vals
    ax.legend(fontsize=7, loc="upper left", ncol=2, framealpha=0.6)
    if pct_mode: ax.set_ylim(0, 105); ax.yaxis.set_major_formatter(lambda v,_: f"{v:.0f}%")
    ax.margins(x=0.04); return _save(fig)

def area_with_target(x, y, title="", ylabel="", color=None, target=90.0, target_label="Target 90%"):
    plt, _ = _mpl(); color = color or C["waste"]
    fig, ax = plt.subplots(figsize=(5.0, 2.4)); _base(ax, title, ylabel)
    ax.plot(x, y, color=color, linewidth=1.8, zorder=3)
    ax.fill_between(x, y, alpha=0.12, color=color)
    ax.axhline(target, color=C["green"], linewidth=1.2, linestyle="--", label=target_label)
    ax.legend(fontsize=7, loc="upper right"); ax.set_ylim(0, 110)
    ax.yaxis.set_major_formatter(lambda v,_: f"{v:.0f}%"); ax.margins(x=0.02)
    return _save(fig)

def line_vs_sector(x, co_y, sec_mean, sec_q25, sec_q75, company_name="You",
                   title="", ylabel="", color=None):
    plt, _ = _mpl(); color = color or C["co2"]
    fig, ax = plt.subplots(figsize=(5.0, 2.4)); _base(ax, title, ylabel)
    yr = list(x)
    q25 = [sec_q25.get(y) for y in yr]; q75 = [sec_q75.get(y) for y in yr]
    med = [sec_mean.get(y) for y in yr]
    ax.fill_between(yr, q25, q75, alpha=0.12, color=color, label="IQR")
    ax.plot(yr, q25, color=C["muted"], linewidth=0.8, linestyle=":", label="Q1")
    ax.plot(yr, med, color=C["muted"], linewidth=1.0, linestyle="-.", label="Median")
    ax.plot(yr, q75, color=C["muted"], linewidth=0.8, linestyle=":", label="Q3")
    co_clean = [v for v in co_y if v is not None]
    ax.plot(yr[:len(co_clean)], co_clean, color=color, linewidth=2.0,
            marker="o", markersize=3, label=company_name)
    ax.legend(fontsize=7, loc="upper right", ncol=2, framealpha=0.6); ax.margins(x=0.02)
    return _save(fig)

def radar_chart(dims, company_scores, sector_scores=None, company_name="You"):
    plt, _ = _mpl()
    N = len(dims); angles = np.linspace(0, 2*np.pi, N, endpoint=False).tolist(); angles += angles[:1]
    fig, ax = plt.subplots(figsize=(4.2, 4.2), subplot_kw={"projection":"polar"})
    ax.set_facecolor("white"); ax.spines["polar"].set_color(C["border"])
    def _draw(sc, col, lbl, alph=0.15):
        v = list(sc) + [sc[0]]; ax.plot(angles, v, "o-", linewidth=2, color=col, label=lbl, markersize=4)
        ax.fill(angles, v, alpha=alph, color=col)
    _draw(company_scores, C["green"], company_name)
    if sector_scores: _draw(sector_scores, C["muted"], "Sector Median", 0.08)
    ax.set_xticks(angles[:-1]); ax.set_xticklabels(dims, size=8, color=C["navy"])
    ax.set_ylim(0, 100); ax.set_yticks([25,50,75,100]); ax.set_yticklabels(["25","50","75","100"], size=6)
    ax.yaxis.grid(True, color=C["border"], linewidth=0.4); ax.xaxis.grid(True, color=C["border"], linewidth=0.4)
    ax.legend(loc="upper right", bbox_to_anchor=(1.35, 1.15), fontsize=7)
    return _save(fig)

def position_bar(kpi_names, positions, colors, title="Sector Percentile (100=best)"):
    plt, _ = _mpl()
    fig, ax = plt.subplots(figsize=(5.0, 0.5+0.42*len(kpi_names))); ax.set_facecolor("white")
    for s in ax.spines.values(): s.set_edgecolor(C["border"]); s.set_linewidth(0.5)
    for i,(name,pos,col) in enumerate(zip(kpi_names, positions, colors)):
        ax.barh(i, pos, color=col, height=0.55, alpha=0.85)
        ax.text(pos+1, i, f"{pos:.0f}%", va="center", fontsize=8, color=C["navy"])
    ax.set_yticks(range(len(kpi_names))); ax.set_yticklabels(kpi_names, fontsize=8)
    ax.set_xlim(0, 115); ax.set_xlabel("Percentile", fontsize=7)
    ax.set_title(title, fontsize=9, fontweight="bold", color=C["navy"], pad=4, loc="left")
    ax.xaxis.grid(True, color=C["border"], linewidth=0.4, linestyle="--"); ax.set_axisbelow(True)
    return _save(fig)


def grouped_bar_line(x, y1, y2, line1, line2, title="", ylabel="", ylabel2="",
                     bar1_label="TIP", bar2_label="Company",
                     line1_label="Intensity (TIP)", line2_label="Intensity (Co.)",
                     bar1_color="#3DBDB5", bar2_color="#1A1A2E"):
    """Grouped bars (TIP + Company) with dual y-axis intensity lines.
    Includes: values inside bars, annotation table below, full background box."""
    plt, _ = _mpl()
    fig = plt.figure(figsize=(7.5, 4.0), facecolor="#f5f4f2")

    # Chart area: leaves 38% at bottom for annotation table
    ax1 = fig.add_axes([0.09, 0.40, 0.78, 0.50], facecolor="white")
    ax2 = ax1.twinx()

    n = len(x); bw = 0.35; xn = np.arange(n)

    # ── Grouped bars ──────────────────────────────────────────────────────────
    bars1 = ax1.bar(xn - bw/2, y1, width=bw, color=bar1_color, alpha=0.9,
                    label=bar1_label, edgecolor="white")
    bars2 = ax1.bar(xn + bw/2, y2, width=bw, color=bar2_color, alpha=0.9,
                    label=bar2_label, edgecolor="white")

    # Values inside bars
    def _fmt_bar(v):
        if v is None or v == 0: return ""
        if abs(v) >= 1e6: return f"{v/1e6:.1f}M"
        if abs(v) >= 1e3: return f"{v/1e3:.0f}k"
        return f"{v:.1f}"

    for bars, col in [(bars1, "white"), (bars2, "white")]:
        for bar in bars:
            h = bar.get_height()
            if h > 0:
                ax1.text(bar.get_x() + bar.get_width()/2, h * 0.5,
                         _fmt_bar(h), ha="center", va="center",
                         fontsize=4.5, color=col, fontweight="bold")

    # ── Lines on right axis ───────────────────────────────────────────────────
    ax2.plot(xn, line1, color="#2a2825", linewidth=1.8, linestyle="-",
             marker="o", markersize=3, label=line1_label)
    ax2.plot(xn, line2, color="#F5A623", linewidth=1.8, linestyle="--",
             marker="o", markersize=3, label=line2_label)

    ax1.set_xticks(xn); ax1.set_xticklabels([str(v) for v in x], fontsize=6, color=C["muted"])
    ax1.set_ylabel(ylabel, fontsize=6, color=C["muted"])
    ax2.set_ylabel(ylabel2, fontsize=6, color=C["muted"])
    if title: ax1.set_title(title, fontsize=8, fontweight="bold", color=C["navy"], loc="left", pad=4)
    ax1.tick_params(colors=C["muted"], labelsize=6)
    ax2.tick_params(colors=C["muted"], labelsize=6)
    for s in ax1.spines.values(): s.set_edgecolor(C["border"]); s.set_linewidth(0.4)
    for s in ax2.spines.values(): s.set_edgecolor(C["border"]); s.set_linewidth(0.4)
    ax1.yaxis.grid(True, color=C["border"], linewidth=0.3, linestyle="--"); ax1.set_axisbelow(True)

    h1, l1 = ax1.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax1.legend(h1+h2, l1+l2, fontsize=5, loc="upper right", ncol=2,
               framealpha=0.7, edgecolor=C["border"])

    # ── Annotation table: label column LEFT, values RIGHT ─────────────────────
    # Use two separate axes to avoid overlap:
    #   lbl_ax: left 22% of width → row labels
    #   val_ax: right 78% of width → per-year values aligned with bars
    LABEL_W = 0.20   # fraction of figure width for label column

    lbl_ax = fig.add_axes([0.09, 0.01, LABEL_W, 0.36], facecolor="#f5f4f2")
    lbl_ax.axis("off")
    lbl_ax.set_xlim(0, 1); lbl_ax.set_ylim(0, 1)

    val_ax = fig.add_axes([0.09 + LABEL_W, 0.01, 0.78 - LABEL_W, 0.36], facecolor="#f5f4f2")
    val_ax.axis("off")
    val_ax.set_xlim(-0.5, n - 0.5); val_ax.set_ylim(0, 1)

    def _fmt_v(v, big=True):
        if v is None: return "—"
        if big and abs(v) >= 1e6: return f"{v/1e6:.1f}M"
        if big and abs(v) >= 1e3: return f"{v/1e3:.0f}k"
        return f"{v:.2f}"

    rows = [
        (f"■ {bar1_label}",   [_fmt_v(v) for v in y1],    bar1_color,   True),
        (f"■ {bar2_label}",   [_fmt_v(v) for v in y2],    bar2_color,   True),
        (f"— {line1_label}",  [_fmt_v(v,False) for v in line1], "#2a2825", False),
        (f"— {line2_label}",  [_fmt_v(v,False) for v in line2], "#F5A623", False),
    ]
    row_ys = [0.82, 0.57, 0.32, 0.07]

    for (lbl, vals, col, _), ry in zip(rows, row_ys):
        lbl_ax.text(0.95, ry, lbl, fontsize=5.5, color=col, va="center",
                    ha="right", fontweight="bold")
        for i, v in enumerate(vals):
            val_ax.text(i, ry, v, fontsize=5.5, color="#374151",
                        ha="center", va="center")

    fig.patch.set_linewidth(0.5); fig.patch.set_edgecolor(C["border"])
    return _save(fig, dpi=140)


def grouped_stacked_bar(x, tip_re, tip_nr, co_re, co_nr, title="",
                        tip_re_color="#2D4A5A", tip_nr_color="#D4C5A9",
                        co_re_color="#3DBDB5", co_nr_color="#B8CDD9",
                        tip_label="TIP", co_label="Company"):
    """Grouped stacked bars with % labels inside and full background.
    Matches the Electricity chart in the Streamlit benchmarking UI."""
    plt, _ = _mpl()
    fig, ax = plt.subplots(figsize=(7.0, 3.0), facecolor="#f5f4f2")
    ax.set_facecolor("white")

    n = len(x); bw = 0.35; xn = np.arange(n)

    # TIP stacked
    b1 = ax.bar(xn - bw/2, tip_re, width=bw, color=tip_re_color, alpha=0.9,
                label=f"Renewable ({tip_label})", edgecolor="white")
    b2 = ax.bar(xn - bw/2, tip_nr, width=bw, bottom=tip_re, color=tip_nr_color,
                alpha=0.9, label=f"Non-renewable ({tip_label})", edgecolor="white")
    # Company stacked
    b3 = ax.bar(xn + bw/2, co_re, width=bw, color=co_re_color, alpha=0.9,
                label=f"Renewable ({co_label})", edgecolor="white")
    b4 = ax.bar(xn + bw/2, co_nr, width=bw, bottom=co_re, color=co_nr_color,
                alpha=0.9, label=f"Non-renewable ({co_label})", edgecolor="white")

    # Value labels inside bars
    for bars, bases in [(b1, [0]*n), (b2, tip_re), (b3, [0]*n), (b4, co_re)]:
        for bar, base in zip(bars, bases):
            h = bar.get_height()
            if h > 4:
                ax.text(bar.get_x() + bar.get_width()/2,
                        base + h/2, f"{h:.1f}%",
                        ha="center", va="center", fontsize=5.5, color="white",
                        fontweight="bold")

    ax.set_xticks(xn); ax.set_xticklabels([str(v) for v in x], fontsize=6, color=C["muted"])
    ax.set_ylim(0, 105)
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0f}%")
    if title: ax.set_title(title, fontsize=8, fontweight="bold", color=C["navy"], loc="left", pad=4)
    ax.tick_params(colors=C["muted"], labelsize=6)
    for s in ax.spines.values(): s.set_edgecolor(C["border"]); s.set_linewidth(0.4)
    ax.yaxis.grid(True, color=C["border"], linewidth=0.3, linestyle="--"); ax.set_axisbelow(True)
    ax.legend(fontsize=5.5, loc="upper right", ncol=2, framealpha=0.7, edgecolor=C["border"])

    fig.tight_layout(pad=0.8)
    fig.patch.set_linewidth(0.5); fig.patch.set_edgecolor(C["border"])
    return _save(fig, dpi=140)