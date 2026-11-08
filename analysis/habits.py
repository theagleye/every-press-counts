# Stress test: every site gets its own pressing habit, then several methods try to recover the weight. 20% of machines teach, 80% are scored.
import argparse
import os
import sys
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.model_selection import GroupKFold

LIFTS = """SELECT c.device_id, c.collection_id, c.actual_at, c.device_fill_pct_before fb, c.device_fill_pct_after fa,
  w.allocated_net_kg net, w.tare_method tm, w.loads_on_vehicle lv, coalesce(c.driver_reported_side_waste, false) sw,
  d.material_stream mat, d.container_volume_m3 vol
  FROM collection_events c LEFT JOIN weighbridge_tickets w USING (operator_job_ref) JOIN devices d USING (device_id)
  WHERE c.status = 'COMPLETED' ORDER BY c.device_id, c.actual_at"""
SCEN = ["none", "habits", "banana", "chaos"]


def lu(rs, a, b, n):
    return np.exp(rs.uniform(np.log(a), np.log(b), n))


# turns real hourly stroke counts into what a site with a different habit would log
def presses(c, dev, t, kind, seed):
    if kind == "none":
        return c.astype(float)
    rs = np.random.default_rng(seed)
    u, inv = np.unique(dev, return_inverse=True)
    if kind == "habits":
        return rs.poisson(c * lu(rs, 0.25, 4, len(u))[inv]).astype(float)
    if kind == "banana":
        return rs.poisson(c * lu(rs, 1, 20, len(u))[inv]).astype(float)
    m = lu(rs, 0.25, 20, len(u))[inv]
    t0, t1 = t.min(), t.max()
    for _ in range(3):
        cut = rs.uniform(t0, t1, len(u))[inv]
        on = rs.random(len(u))[inv] < 0.7
        m = m * np.where(on & (t > cut), lu(rs, 1 / 3, 3, len(u))[inv], 1)
    m = m * np.exp(rs.normal(0, 0.7, len(c)))
    return (rs.poisson(c * m) + rs.poisson(0.5 * m * (c > 0)) + rs.poisson(0.05, len(c))).astype(float)


# strokes, messages and fill rise for every completed lift
def cycles(tel, lifts, cc):
    out = []
    for d, ld in lifts.groupby("device_id", sort=False):
        lo, hi = tel.attrs["span"][d]
        tt, cs = tel.t.values[lo:hi], np.concatenate([[0], np.cumsum(cc[lo:hi])])
        at = ld.actual_at.values.astype("datetime64[ns]").astype(np.int64)
        i = np.searchsorted(tt, at, side="right")
        s, n = cs[i], i
        x = ld.copy()
        x["cyc"] = np.diff(np.concatenate([[np.nan], s]))
        x["msgs"] = np.diff(np.concatenate([[np.nan], n.astype(float)]))
        out.append(x)
    q = pd.concat(out)
    q["prev"] = q.groupby("device_id").actual_at.shift()
    q["hrs"] = ((q.actual_at - q.prev).dt.total_seconds() / 3600).clip(lower=1)
    q["cov"] = q.msgs / q.hrs
    fa = q.groupby("device_id").fa.shift().fillna(0)
    q["V"] = ((q.fb - fa) / 100 * q.vol).clip(lower=0.01 * q.vol)
    return q[q.prev.notna()].copy()


def robvar(x):
    x = x[np.isfinite(x)]
    return float((1.4826 * np.median(np.abs(x - np.median(x)))) ** 2)


# stream-level values learned on the reference machines only
def params(r):
    p = {}
    for s, g in r.groupby("mat"):
        dk = np.log(g.net / g.cyc)
        p[s] = dict(kps=float(np.exp(np.median(dk))), rho=float(np.median(g.net / g.V)),
                    R=robvar(np.log(g.V * np.median(g.net / g.V) / g.net)),
                    S=robvar(dk - g.assign(dk=dk).groupby("device_id").dk.transform("median")),
                    B=max(robvar(g.assign(dk=dk).groupby("device_id").dk.median().values), 0.01))
    return p


# per-site kg per stroke as a slowly drifting state, corrected by the fill estimate after every lift
def kalman(q, p, Q, reset, obs, R):
    est, var, nup = np.full(len(q), np.nan), np.full(len(q), np.nan), np.zeros(len(q))
    pos = 0
    for d, g in q.groupby("device_id", sort=False):
        a = p[g.mat.iloc[0]]
        x, P, bad, n = np.log(a["kps"]), a["B"], 0, 0
        for cyc, f, r, cov in zip(g.cyc.values, obs[pos:pos + len(g)], R[pos:pos + len(g)], g["cov"].values):
            P += Q
            est[pos], var[pos], nup[pos] = cyc * np.exp(x), P + a["S"], n
            if cov >= 0.95 and cyc > 0 and f > 0:
                z, sv = np.log(f / cyc), P + r + a["S"]
                e = z - x
                if reset and abs(e) > 3 * np.sqrt(sv):
                    bad += 1
                    if bad >= 2:
                        x, P, bad = z, r + a["S"], 0
                else:
                    bad, K = 0, P / sv
                    x, P, n = x + K * e, (1 - K) * P, n + 1
            pos += 1
    return est, var, nup


# teach each site from its first K weighed lifts; with drift on, 3 lifts in a row off by 2x ask for one new weighing
def commission(q, fc, K, drift):
    est, el, alarms, pos = np.full(len(q), np.nan), np.zeros(len(q), bool), 0, 0
    for d, g in q.groupby("device_id", sort=False):
        ks, zs, k, z0, bad, done = [], [], None, 0.0, 0, False
        for cyc, net, cl, f, cov in zip(g.cyc.values, g.net.values, g.clean.values, fc[pos:pos + len(g)], g["cov"].values):
            if drift and k is not None and cov >= 0.95 and cyc > 0 and f > 0:
                bad = bad + 1 if abs(np.log(cyc * k / f) - z0) > np.log(2.0) else 0
                if bad >= 3:
                    k, ks, zs, bad, alarms = None, [], [], 0, alarms + 1
            el[pos] = done
            est[pos] = cyc * k if k is not None else f
            if cl and k is None:
                ks.append(net / cyc)
                zs.append(np.log(net / f))
                if len(ks) >= (1 if done else K):
                    k, z0, done = float(np.median(ks)), float(np.median(zs)), True
            pos += 1
    return est, el, alarms


def score(r):
    e = (r - 1).abs()
    return dict(lifts=int(len(r)), med_err=round(float(e.median()), 3), p90_err=round(float(e.quantile(.9)), 3),
                under20=round(float((r < 0.8).mean()), 3), over20=round(float((r > 1.2).mean()), 3),
                off_2x=round(float(((r > 2) | (r < 0.5)).mean()), 4))


def run(q, ref, Q):
    p = params(q[ref & q.clean])
    m = q.mat.map(lambda s: p[s]["kps"]).values
    rho, R = q.mat.map(lambda s: p[s]["rho"]).values, q.mat.map(lambda s: p[s]["R"]).values
    o = pd.DataFrame(index=q.index)
    o["stream"] = q.cyc * m
    o["fill"] = q.V * rho
    v, tr = (q.V / q.vol).values, (ref & q.clean).values
    fc = np.full(len(q), np.nan)
    for s_, g in q[tr].groupby("mat"):
        vv = (g.V / g.vol).values
        c, *_ = np.linalg.lstsq(np.c_[vv, vv ** 2], (g.net / g.vol).values, rcond=None)
        k = (q.mat == s_).values
        fc[k] = q.vol.values[k] * (c[0] * v[k] + c[1] * v[k] ** 2)
    o["fill_curve"] = np.clip(fc, 1, None)
    Rc = {s_: robvar(np.log(o.fill_curve[tr & (q.mat == s_).values] / q.net[tr & (q.mat == s_).values])) for s_ in p}
    R = q.mat.map(Rc).values
    o["kalman"], kv, nup = kalman(q, p, Q, False, o.fill_curve.values, R)
    o["kalman_reset"], kv2, _ = kalman(q, p, Q, True, o.fill_curve.values, R)
    w1, w2 = 1 / kv2, 1 / R
    o["fusion"] = np.exp((np.log(o.kalman_reset) * w1 + np.log(o.fill_curve) * w2) / (w1 + w2))
    fv = 1 / (w1 + w2)
    dens = o.stream / o.fill
    o["stream_gated"] = np.where((dens > 2) | (dens < 0.5), o.fill, o.stream)
    f = pd.DataFrame({"ls": np.log1p(q.cyc), "lf": np.log(o.fill), "lk": np.log(o.kalman_reset), "lv": np.log(kv2), "fb": q.fb, "hrs": q.hrs,
                      "rate": np.log1p(q.cyc / q.hrs), "vol": q.vol, "cov": q["cov"], "n": nup, "mis": np.log(o.kalman_reset / o.fill_curve), "lc": np.log(o.fill_curve),
                      "m": q.mat.astype("category").cat.codes})
    tr = ref & q.clean
    # gradient boosting learns how to blend strokes, fill and the Kalman estimate, trained on reference machines
    ml = HistGradientBoostingRegressor(max_iter=300, learning_rate=0.05, max_leaf_nodes=15, min_samples_leaf=20, l2_regularization=1.0, random_state=0)
    ml.fit(f[tr], np.log(q.net[tr]))
    o["ml_fusion"] = np.exp(ml.predict(f))
    c = ref & q.clean
    # split conformal: a 90% range scaled by each estimate's own uncertainty
    sc = np.abs(np.log(q.net[c] / o.fusion[c])) / np.sqrt(fv[c])
    qq = np.quantile(sc, np.ceil(0.9 * (len(sc) + 1)) / len(sc))
    half = qq * np.sqrt(fv)
    o["lo"], o["hi"] = o.fusion * np.exp(-half), o.fusion * np.exp(half)
    al = {}
    for K in (1, 3, 5):
        o[f"weigh{K}"], o[f"el{K}"], _ = commission(q, o.fill_curve.values, K, False)
    o["weigh3_drift"], _, al = commission(q, o.fill_curve.values, 3, True)
    return o, al


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--europress", required=True)
    ap.add_argument("--results", default="results")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--Q", type=float, default=0.003)
    a = ap.parse_args()
    sys.path.insert(0, os.path.join(a.europress, "src"))
    from europress_data.sdk import open_dataset
    con = open_dataset(os.path.join(a.europress, "data", "competition", "public"))
    tel = con.sql("SELECT device_id, measured_at, coalesce(compaction_cycles, 0) c FROM telemetry_dedup ORDER BY device_id, measured_at").df()
    tel["t"] = tel.measured_at.values.astype("datetime64[ns]").astype(np.int64)
    dv = tel.device_id.values
    b = np.flatnonzero(np.r_[True, dv[1:] != dv[:-1], True])
    tel.attrs["span"] = {dv[b[i]]: (b[i], b[i + 1]) for i in range(len(b) - 1)}
    lifts = con.sql(LIFTS).df()
    lifts = lifts[lifts.device_id.isin(tel.attrs["span"])]
    base = cycles(tel, lifts, tel.c.values.astype(float))
    clean = ((base.tm == "WEIGHED") & (base.lv == 1) & ~base.sw.astype(bool) & (base.net > 200) & (base.cyc > 10) & (base.fb > 5)).values
    rows, cov, extra = [], [], []
    for k, kind in enumerate(SCEN):
        q = cycles(tel, lifts, presses(tel.c.values, dv, tel.t.values, kind, a.seed + k))
        q["clean"] = clean
        q = q.reset_index(drop=True)
        dev = q.device_id.values
        res, alarms, fleet = [], 0, 0
        for f, (_, ri) in enumerate(GroupKFold(5).split(q, groups=dev)):
            ref = np.zeros(len(q), bool)
            ref[ri] = True
            o, al = run(q, ref, a.Q)
            m = ~ref & q.clean.values
            alarms += al
            fleet += len(set(dev[~ref]))
            res.append(o[m].assign(net=q.net[m].values, cov=q["cov"][m].values, device_id=dev[m]))
        r = pd.concat(res)
        for meth in ["stream", "fill", "fill_curve", "stream_gated", "kalman", "kalman_reset", "fusion", "ml_fusion"]:
            rows.append(dict(scenario=kind, subset="all fleet lifts", method=meth, **score(r[meth] / r.net)))
        e3 = r.el3.astype(bool)
        for meth in ["stream", "fill_curve", "fusion", "ml_fusion", "weigh3", "weigh3_drift"]:
            rows.append(dict(scenario=kind, subset="after 3 weighed lifts", method=meth, **score(r[meth][e3] / r.net[e3])))
        for K in (1, 5):
            e = r[f"el{K}"].astype(bool)
            rows.append(dict(scenario=kind, subset=f"after {K} weighed lifts", method=f"weigh{K}", **score(r[f"weigh{K}"][e] / r.net[e])))
        lr = np.log(r.weigh3[e3] / r.net[e3]).groupby(r.device_id[e3]).median()
        extra.append(dict(scenario=kind, reweigh_per_machine_year=round(alarms / fleet, 2), site_calibration_sd=round(float(np.sqrt(robvar(lr.values))), 3)))
        print(extra[-1], flush=True)
        cov.append(dict(scenario=kind, coverage_90=round(float(((r.net >= r.lo) & (r.net <= r.hi)).mean()), 3),
                        median_width=round(float((r.hi / r.lo).median()), 2)))
        sp = q.groupby("device_id").cyc.sum() / base.groupby("device_id").cyc.sum()
        print(kind, "strokes vs original, per machine: median", round(float(sp.median()), 2), "min", round(float(sp.min()), 2), "max", round(float(sp.max()), 2), flush=True)
    out = pd.DataFrame(rows)
    os.makedirs(a.results, exist_ok=True)
    out.to_csv(os.path.join(a.results, "habits_eval.csv"), index=False)
    pd.DataFrame(cov).merge(pd.DataFrame(extra), on="scenario").to_csv(os.path.join(a.results, "habits_extra.csv"), index=False)
    print(out.to_string(index=False))
    print(pd.DataFrame(cov).to_string(index=False))


if __name__ == "__main__":
    main()
