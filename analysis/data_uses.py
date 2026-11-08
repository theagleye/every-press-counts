# What else the stroke and fill data shows, beyond lift timing: usage spread, rain, right-sizing, wear.
import argparse
import json
import os
import sys
import pandas as pd
from strokes_eval import SQL


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--europress", required=True)
    ap.add_argument("--results", default="results")
    a = ap.parse_args()
    sys.path.insert(0, os.path.join(a.europress, "src"))
    from europress_data.sdk import open_dataset
    con = open_dataset(os.path.join(a.europress, "data", "competition", "public"))
    out = {}
    # strokes per machine over the year: a fixed service calendar treats a quiet and a busy machine the same
    y = con.sql("""SELECT device_id, sum(coalesce(compaction_cycles, 0)) s FROM telemetry_dedup GROUP BY 1""").df().s
    out["strokes_per_machine_year"] = dict(machines=len(y), p10=int(y.quantile(.1)), median=int(y.median()), p90=int(y.quantile(.9)),
                                           p90_over_p10=round(float(y.quantile(.9) / y.quantile(.1)), 1))
    # corrective work orders by stroke quartile: does wear follow use in this data?
    w = con.sql("""SELECT t.device_id, t.s, count(w.work_order_id) FILTER (WHERE w.work_order_type = 'CORRECTIVE') c
      FROM (SELECT device_id, sum(coalesce(compaction_cycles, 0)) s FROM telemetry_dedup GROUP BY 1) t
      LEFT JOIN maintenance_work_orders w USING (device_id) GROUP BY 1, 2""").df()
    w["q"] = pd.qcut(w.s, 4, labels=["Q1 least used", "Q2", "Q3", "Q4 most used"])
    out["corrective_orders_per_machine_by_use"] = w.groupby("q", observed=True).c.mean().round(2).to_dict()
    # rain: sites that stage material outdoors gain water mass without strokes, so kg per stroke runs higher
    con.sql("""CREATE TEMP TABLE tel AS SELECT device_id, measured_at,
      sum(coalesce(compaction_cycles, 0)) OVER (PARTITION BY device_id ORDER BY measured_at) cum_cyc,
      count(*) OVER (PARTITION BY device_id ORDER BY measured_at) cum_n FROM telemetry_dedup""")
    q = con.sql(SQL).df()
    q = q[(q.tm == "WEIGHED") & (q.lv == 1) & ~q.sw & (q.net > 200) & (q.cyc > 10) & (q.fb > 5)].copy()
    q = q.merge(con.sql("SELECT d.device_id, s.outdoor_material_staging od FROM devices d JOIN sites s USING (site_id)").df(), on="device_id")
    k = (q.net / q.cyc).groupby([q.mat, q.od]).median().unstack()
    out["kg_per_stroke_outdoor_vs_indoor"] = (k[True] / k[False]).round(3).to_dict()
    # right-sizing: machines that are usually lifted half empty, or past capacity
    c = pd.read_csv(os.path.join(a.results, "replay_cycles.csv"))
    m = c[c.ok_at_lift].groupby("device_id").frac_at_lift.median()
    out["machines_by_typical_load_at_lift"] = dict(machines=len(m), below_50pct=int((m < 0.5).sum()), between=int(((m >= 0.5) & (m <= 1.0)).sum()),
                                                   above_100pct=int((m > 1.0).sum()))
    km = con.sql("SELECT billable_round_trip_km FROM sites").df().billable_round_trip_km
    out["site_round_trip_km"] = dict(sites=len(km), median=float(km.median()))
    json.dump(out, open(os.path.join(a.results, "data_uses.json"), "w"), indent=1)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
