# Picks one typical cardboard fill cycle and one simulator decision case for the demo page.
import argparse
import json
import os
import sys
import pandas as pd
from strokes_eval import SQL

CASE = "DC-00373-05382"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--europress", required=True)
    p.add_argument("--results", default="results")
    p.add_argument("--stream", default="cardboard")
    a = p.parse_args()
    sys.path.insert(0, os.path.join(a.europress, "src"))
    from europress_data.sdk import open_dataset
    pub = os.path.join(a.europress, "data", "competition", "public")
    con = open_dataset(pub)
    con.sql("""CREATE TEMP TABLE tel AS SELECT device_id, measured_at,
      sum(coalesce(compaction_cycles, 0)) OVER (PARTITION BY device_id ORDER BY measured_at) cum_cyc,
      count(*) OVER (PARTITION BY device_id ORDER BY measured_at) cum_n FROM telemetry_dedup""")
    q = con.sql(SQL).df()
    # a typical cycle: weighed truck, one load, full telemetry, 5 to 25 days long
    q = q[(q.tm == "WEIGHED") & (q.lv == 1) & ~q.sw & (q.net > 500) & (q.cyc > 60) & (q.mat == a.stream)].copy()
    q = q[(q.msgs >= 0.98 * q.hrs) & q.hrs.between(120, 600)].sort_values(["device_id", "actual_at"])
    pick = None
    for r in q.itertuples():
        o = q[q.device_id != r.device_id]
        k = float((o.net / o.cyc).median())
        if abs(r.cyc * k / r.net - 1) <= 0.08:
            pick = (r, k)
            break
    r, k = pick
    t = con.sql(f"""SELECT measured_at, fill_pct, mass_kg, compaction_cycles FROM telemetry_dedup
      WHERE device_id = '{r.device_id}' AND measured_at > '{r.prev_at}' AND measured_at <= '{r.actual_at}' ORDER BY measured_at""").df()
    h = ((t.measured_at - r.prev_at).dt.total_seconds() / 3600).round(1)
    trace = dict(device=r.device_id, stream=r.mat, equipment=r.eq, volume_m3=float(r.vol), start=str(r.prev_at), lift=str(r.actual_at),
                 kg_per_stroke=round(k, 2), ticket_kg=float(r.net), hours=h.tolist(), fill=t.fill_pct.round(1).tolist(),
                 gauge=t.mass_kg.round(0).tolist(), strokes_kg=(t.compaction_cycles.fillna(0).cumsum() * k).round(0).tolist())
    o = pd.read_parquet(os.path.join(pub, "labels_dev", "decision_outcomes.parquet"))
    o = o[o.case_id == CASE].set_index("action")
    n, m = o.loc["NO_ACTION"], o.loc["MASS_TARGET_TRIGGER"]
    case = dict(case_id=CASE, lifts_fill=float(n.n_completed_lifts), lifts_kilo=float(m.n_completed_lifts),
                cost_fill=float(n.adjusted_cost_cents) / 100, cost_kilo=float(m.adjusted_cost_cents) / 100,
                saving=float(m.benefit_vs_no_action_cents) / 100, saving_se=float(m.benefit_se_cents) / 100, overflow_h=float(m.overflow_open_hours))
    out = dict(trace=trace, case=case)
    json.dump(out, open(os.path.join(a.results, "demo_data.json"), "w"), default=float)
    print({k: v for k, v in trace.items() if k not in ("hours", "fill", "gauge", "strokes_kg")}, "| points", len(trace["hours"]))
    print("strokes estimate at lift", trace["strokes_kg"][-1], "| gauge at lift", trace["gauge"][-1], "| ticket", trace["ticket_kg"])
    print(case)


if __name__ == "__main__":
    main()
