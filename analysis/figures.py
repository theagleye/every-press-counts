# Draws the report figures in docs/fig from the result files, so every chart traces back to a CSV or JSON.
import json
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

R = os.path.join(os.path.dirname(__file__), "..", "results")
F = os.path.join(os.path.dirname(__file__), "..", "docs", "fig")
KILO, FILL, BAD, GREY, GOOD = "#b06a00", "#237a78", "#b53c2c", "#6b7682", "#2d7a47"
plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False, "figure.dpi": 150})


def hbars(ax, labels, vals, colors, fmt):
    y = range(len(labels))[::-1]
    ax.barh(list(y), vals, color=colors, height=0.6)
    ax.set_yticks(list(y), labels)
    for yy, v in zip(y, vals):
        ax.text(v, yy, " " + fmt(v), va="center", fontsize=9)


def main():
    os.makedirs(F, exist_ok=True)
    se = pd.read_csv(os.path.join(R, "strokes_eval.csv"))
    # error falls as more strokes go into one lift
    b = se[se.subset.str.startswith("strokes ") & (se.subset != "strokes >400")]
    fig, ax = plt.subplots(figsize=(6, 2.6))
    ax.bar(b.subset.str.replace("strokes ", ""), b.med_err * 100, color=KILO, width=0.6)
    for i, v in enumerate(b.med_err * 100):
        ax.text(i, v, f"{v:.1f}%", ha="center", va="bottom", fontsize=9)
    ax.set_xlabel("strokes per lift")
    ax.set_ylabel("median error, %")
    fig.tight_layout()
    fig.savefig(os.path.join(F, "error_by_strokes.png"))
    # pressing-habit stress test: median error and lifts off by 2x, per method and scenario
    h = pd.read_csv(os.path.join(R, "habits_eval.csv"))
    rows = [("all fleet lifts", "stream", "Stream average", BAD), ("all fleet lifts", "fill_curve", "Fill x compaction curve", FILL),
            ("all fleet lifts", "ml_fusion", "ML fusion", GREY), ("after 3 weighed lifts", "weigh3", "3 weighed lifts per site", KILO),
            ("after 3 weighed lifts", "weigh3_drift", "3 weighed lifts + drift alarm", KILO)]
    sc = [("none", "Real data"), ("habits", "0.25-4x"), ("banana", "1-20x"), ("chaos", "Chaos")]
    fig, axs = plt.subplots(1, 2, figsize=(9, 3.4))
    w = 0.16
    for k, (col, title) in enumerate([("med_err", "median error, %"), ("off_2x", "lifts off by more than 2x, %")]):
        ax = axs[k]
        for i, (sub, m, lab, c) in enumerate(rows):
            v = [h[(h.scenario == s) & (h.subset == sub) & (h.method == m)][col].iloc[0] * 100 for s, _ in sc]
            ax.bar([j + (i - 2) * w for j in range(4)], v, w, color=c, alpha=0.55 if m == "weigh3" else 1, label=lab)
        ax.set_xticks(range(4), [t for _, t in sc])
        ax.set_title(title, fontsize=10)
    axs[0].legend(fontsize=8, frameon=False, loc="upper left")
    fig.tight_layout()
    fig.savefig(os.path.join(F, "habits.png"))
    # value in Europress's simulator
    v = pd.read_csv(os.path.join(R, "sim_value.csv")).set_index("variant")
    pick = [("base", "Real gauge, dataset spec", GREY), ("st_hi", "Strokes x1.1, same habit everywhere", KILO),
            ("st_habcal", "Strokes, sites 1-20x, 3 weighed lifts (8%)", KILO), ("st_habcal12", "Strokes, sites 1-20x, 3 weighed lifts (12%)", KILO),
            ("st_missfb", "Strokes, 10% days lost, caught", KILO), ("fillmass", "Kilos from the fill reading", FILL),
            ("fillcal_fm", "Fill, sensors calibrated at factory", FILL), ("st_miss", "Strokes, 10% days lost, missed", BAD),
            ("st_hab", "Strokes, sites 1-20x, stream average", BAD)]
    fig, ax = plt.subplots(figsize=(7, 3.6))
    hbars(ax, [p[1] for p in pick], [v.eur_per_machine_year[p[0]] for p in pick], [p[2] for p in pick], lambda x: f"EUR {x:.0f}")
    ax.set_xlabel("EUR per machine-year that lifting by kilos adds")
    fig.tight_layout()
    fig.savefig(os.path.join(F, "sim_value.png"))
    # value by waste stream on the official decision cases
    s = pd.read_csv(os.path.join(R, "value_by_stream.csv"))
    fig, ax = plt.subplots(figsize=(6, 2.6))
    hbars(ax, s.stream.str.replace("_", " "), s.eur_per_machine_year, [FILL if x == "biowaste" else KILO for x in s.stream], lambda x: f"EUR {x:.0f}")
    ax.set_xlabel("EUR per machine-year")
    fig.tight_layout()
    fig.savefig(os.path.join(F, "streams.png"))
    # the frozen fill sensor on CMP-00168, replayed hour by hour
    t = json.load(open(os.path.join(R, "replay_trace.json")))
    fig, ax = plt.subplots(figsize=(8, 3.2))
    w0 = t["windows"][0]
    ax.axvspan(w0["h0"] / 24, w0["h1"] / 24, color=BAD, alpha=0.1, label="fill sensor stuck (official label)")
    ax.plot([x / 24 for x in t["hours"]], t["fill"], color=FILL, lw=1.4, label="fill reading, %")
    ax.plot([x / 24 for x in t["hours"]], [f * 100 for f in t["frac"]], color=KILO, lw=2, label="kilos from strokes, % of capacity")
    ax.axhline(80, color=KILO, ls="--", lw=1)
    for e in t["events"]:
        ax.axvline(e["h"] / 24, color=BAD if e["label"] else GREY, lw=1)
    ax.set_xlabel("days from 15 Apr 2026, 09:00 UTC")
    ax.set_ylabel("%")
    ax.legend(fontsize=8, frameon=False, loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=3)
    fig.tight_layout()
    fig.savefig(os.path.join(F, "frozen_sensor.png"))
    print("figures written to docs/fig")


if __name__ == "__main__":
    main()
