# How well does strokes x kg per stroke match the weighbridge? Kilos per stroke are always learned on other machines.
import argparse
import os
import sys
import numpy as np
import pandas as pd
import yaml
from sklearn.model_selection import GroupKFold

# one row per completed lift with a ticket: strokes and hourly messages since the previous lift come from cumulative telemetry
SQL = """WITH ev AS (
  SELECT c.collection_id, c.device_id, c.actual_at, lag(c.actual_at) OVER (PARTITION BY c.device_id ORDER BY c.actual_at) prev_at,
    w.allocated_net_kg net, w.tare_method tm, w.loads_on_vehicle lv, coalesce(c.driver_reported_side_waste, false) sw,
    c.device_fill_pct_before fb, c.device_estimated_collected_kg dev, d.material_stream mat, d.equipment_class eq, d.container_volume_m3 vol
  FROM collection_events c JOIN weighbridge_tickets w USING (operator_job_ref) JOIN devices d USING (device_id)
  WHERE c.status = 'COMPLETED')
SELECT ev.*, t1.cum_cyc - t0.cum_cyc cyc, t1.cum_n - t0.cum_n msgs, date_diff('hour', ev.prev_at, ev.actual_at) hrs FROM ev
ASOF JOIN tel t1 ON ev.device_id = t1.device_id AND ev.actual_at >= t1.measured_at
ASOF JOIN tel t0 ON ev.device_id = t0.device_id AND ev.prev_at >= t0.measured_at"""


def stats(r):
    e = (r - 1).abs()
    return dict(lifts=len(r), med_err=round(e.median(), 3), p90_err=round(e.quantile(.9), 3), bias=round(r.median() - 1, 3),
                under20=round((r < 0.8).mean(), 3), over20=round((r > 1.2).mean(), 3))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--europress", required=True)
    p.add_argument("--results", default="results")
    a = p.parse_args()
    sys.path.insert(0, os.path.join(a.europress, "src"))
    from europress_data.sdk import open_dataset
    con = open_dataset(os.path.join(a.europress, "data", "competition", "public"))
    con.sql("""CREATE TEMP TABLE tel AS SELECT device_id, measured_at,
      sum(coalesce(compaction_cycles, 0)) OVER (PARTITION BY device_id ORDER BY measured_at) cum_cyc,
      count(*) OVER (PARTITION BY device_id ORDER BY measured_at) cum_n FROM telemetry_dedup""")
    q = con.sql(SQL).df()
    # clean lifts only: freshly weighed truck, one load on it, no side waste, enough strokes and a fill reading
    q = q[(q.tm == "WEIGHED") & (q.lv == 1) & ~q.sw & (q.net > 200) & (q.cyc > 10) & (q.fb > 5)].copy()
    q["V"] = q.fb / 100 * q.vol
    q["gap"] = q.msgs / q.hrs.clip(lower=1) < 0.95
    ps, pf = np.zeros(len(q)), np.zeros(len(q))
    # machines in the test fold never teach their own kilos per stroke or density
    for tr, te in GroupKFold(5).split(q, groups=q.device_id):
        t, s = q.iloc[tr], q.iloc[te]
        ps[te] = s.cyc * s.mat.map((t.net / t.cyc).groupby(t.mat).median())
        pf[te] = s.V * s.mat.map((t.net / t.V).groupby(t.mat).median())
    q["r_strokes"], q["r_fill"], q["r_gauge"] = ps / q.net, pf / q.net, q.dev / q.net
    rows = []
    for n, c in [("stroke count", "r_strokes"), ("stroke count x1.1", None), ("fill x density", "r_fill"), ("built-in gauge (simulated)", "r_gauge")]:
        r = q.r_strokes * 1.1 if c is None else q[c].dropna()
        rows.append(dict(method=n, subset="all", **stats(r)))
    for g, m in [("full telemetry", ~q.gap), ("telemetry gaps", q.gap)]:
        rows.append(dict(method="stroke count", subset=g, **stats(q.r_strokes[m])))
    mats = yaml.safe_load(open(os.path.join(a.europress, "configs", "assumptions.yaml")))["materials"]
    cap = np.array([v * mats[m]["compacted_density"] * (1 + mats[m]["compressibility"] / 2) for v, m in zip(q.vol, q.mat)])
    # capacity check: an estimate above 1.3 x capacity is an over-read
    ok = ps * 1.1 <= 1.3 * cap
    rows.append(dict(method="stroke count", subset="capacity check passed", **stats(q.r_strokes[ok])))
    rows.append(dict(method="stroke count x1.1", subset="capacity check passed", **stats(q.r_strokes[ok] * 1.1)))
    rows.append(dict(method="stroke count", subset="capacity check failed", **stats(q.r_strokes[~ok])))
    for b, d in q.groupby(pd.cut(q.cyc, [10, 50, 100, 200, 400, np.inf], labels=["11-50", "51-100", "101-200", "201-400", ">400"]), observed=True):
        rows.append(dict(method="stroke count", subset=f"strokes {b}", **stats(d.r_strokes)))
    # what each use needs: the brief's +-100 kg target and the error of cost per tonne
    use = []
    for n, est, m in [("stroke count, capacity check passed", ps, ok), ("built-in gauge (simulated)", q.dev.to_numpy(), q.dev.notna().to_numpy())]:
        e, w = est[m], q.net.to_numpy()[m]
        b = (w >= 2500) & (w <= 3500)
        c = np.abs(w / e - 1)
        use.append(dict(method=n, lifts=int(m.sum()), loads_2500_3500kg=int(b.sum()), within_100kg=round(float((np.abs(e[b] - w[b]) <= 100).mean()), 3),
                        median_eur_per_t_error=round(float(np.median(c)), 3), p95_eur_per_t_error=round(float(np.quantile(c, 0.95)), 3)))
    use = pd.DataFrame(use)
    use.to_csv(os.path.join(a.results, "accuracy_use_cases.csv"), index=False)
    print(use.to_string(index=False))
    for s, d in q.groupby("mat"):
        rows.append(dict(method="stroke count", subset=s, **stats(d.r_strokes)))
        rows.append(dict(method="fill x density", subset=s, **stats(d.r_fill)))
    out = pd.DataFrame(rows)
    os.makedirs(a.results, exist_ok=True)
    out.to_csv(os.path.join(a.results, "strokes_eval.csv"), index=False)
    k = (q.net / q.cyc).groupby(q.mat).median().round(3).rename("kg_per_stroke").rename_axis("stream").reset_index()
    k.to_csv(os.path.join(a.results, "kg_per_stroke.csv"), index=False)
    print(k.to_string(index=False))
    print(f"lifts {len(q)} | machines {q.device_id.nunique()} | with telemetry gaps {q.gap.mean():.3f} | fail capacity check {(~ok).mean():.3f}")
    print(q.groupby("mat").cyc.median().rename("median strokes per lift").to_string())
    print(out.to_string(index=False))


if __name__ == "__main__":
    main()
