# Rebuilds Europress's world with its own generator, changing one thing per run, and values what lifting by kilos adds.
import argparse
import os
import shutil
import subprocess
import sys
import numpy as np
import pandas as pd

TRIG = "om = obs_mass(cumM[st_i:], slice(h + st_i, e), arr, A)"
RULE = "trig = (((om >= mass_target) | (np.isnan(om) & (obs_fill[st_i:] >= 90))) & onl[st_i:])"
GAIN = "g0 = 1 + rs.normal(0, 0.004)"
OFF = "o0 = rs.normal(0, 6)"
IND = "\n" + " " * 28
DEV = "(1 + 0.15 * float(np.random.default_rng(int(spec['cap_mass_kg'] * 1000) % 2**32).normal()))"
CAL = ([("fill_bias_sd_pp: 4.0", "fill_bias_sd_pp: 0.0"), ("fill_gain_sd: 0.07", "fill_gain_sd: 0.0")],
       [('mat_bias = {"plastic_film": 5.0, "mixed_plastic": 4.0, "cardboard": 1.0, "paper": -1.0, "mixed_waste": -2.0, "biowaste": -4.0}', "mat_bias = {}"),
        ("if rt.random() < 0.05:", "if rt.random() < 0.0:")])
HAB = "float(np.exp(np.random.default_rng(int(spec['device_id'][4:]) + 99).uniform(0, np.log(20))))"
FILLM = "om = spec['cap_mass_kg'] * {f}W_from_vol(np.minimum(obs_fill[st_i:], 100) / 100 * C, C, c) / W_from_vol(C, C, c)"


def noise(k, g=None):
    g = k if g is None else g
    y = [("mass_sigma_abs_kg: 15", f"mass_sigma_abs_kg: {max(15 * k, 0.001):g}"), ("mass_sigma_rel: 0.014", f"mass_sigma_rel: {0.014 * k:g}")]
    s = [(GAIN, f"g0 = 1 + rs.normal(0, {0.004 * g:g})"), (OFF, f"o0 = rs.normal(0, {6 * g:g})")]
    return y, s


# replaces the simulated scale with a stroke-count estimate; kind selects the fault or habit being tested
def strokes(kind):
    L = ["_ev = np.where(dn, 0, arr['n_ev'][sl]).astype(np.int64)",
         "_rg = np.random.default_rng(int(h) + 7)",
         "_cy = _rg.binomial(_ev, 0.85).astype(float)",
         "_dd = np.arange(h, e) // 24",
         "_kg = spec['input_event_kg'] / 0.85" + (" * 1.1" if kind == "hi" else "") + (" * " + DEV if kind == "dev15" else "")]
    if kind in ("hab", "habcal", "habcal12"):
        L.append("_hm = " + HAB)
        L.append("_cy = _rg.poisson(_cy * _hm).astype(float)")
        sd = "0.12" if kind == "habcal12" else "0.08"
        L.append("_kg = _kg * 1.1 / " + ("4.472" if kind == "hab" else "_hm * float(np.exp(np.random.default_rng(int(spec['device_id'][4:]) + 199).normal(0, " + sd + ")))"))
    if kind == "spur":
        L.append("_cy = _cy + _rg.binomial(_ev, 0.2) + (_rg.random(_ev.size) < 0.02)")
    if kind == "drift":
        L.append("_ph = float(np.random.default_rng(int(spec['cap_mass_kg'] * 1000) % 2**32).uniform(0, 6.283))")
        L.append("_cy = _cy * (1 + 0.2 * np.sin(6.283 * _dd / 365.0 + _ph))")
    if kind in ("miss", "missfb"):
        L.append("_lost = np.random.default_rng(4242).random(int(_dd.max()) + 1)[_dd] < 0.10")
        L.append("_cy = np.where(_lost, 0.0, _cy)")
    if kind == "missfb":
        L.append("om = np.where(np.cumsum(_lost) > 0, np.nan, Rm + np.cumsum(_cy * _kg))[st_i:]")
    else:
        L.append("om = (Rm + np.cumsum(_cy * _kg))[st_i:]")
    return [], [(TRIG, IND.join(L))]


V = {
    "perfect": ("sensor error ~0", noise(0)),
    "base": ("built-in gauge, their spec", noise(1)),
    "x2": ("gauge error x2", noise(2)),
    "x4": ("gauge error x4", noise(4)),
    "x7": ("gauge error x7", noise(7)),
    "x14": ("gauge error x14", noise(14)),
    "gain6": ("uncalibrated gauge, gain sd 6%", noise(1, 15)),
    "biasp6": ("every gauge reads 6% high", ([], [(GAIN, "g0 = 1.06 + 0 * rs.normal(0, 0.004)")])),
    "biasm6": ("every gauge reads 6% low", ([], [(GAIN, "g0 = 0.94 + 0 * rs.normal(0, 0.004)")])),
    "dual95": ("gauge + fill stop at 95%", ([], [(RULE, RULE.replace("(np.isnan(om) & (obs_fill[st_i:] >= 90))", "(obs_fill[st_i:] >= 95)"))])),
    "dual98": ("gauge + fill stop at 98%", ([], [(RULE, RULE.replace("(np.isnan(om) & (obs_fill[st_i:] >= 90))", "(obs_fill[st_i:] >= 98)"))])),
    "fillmass": ("software: kg from fill reading", ([], [(RULE, FILLM.format(f="") + IND + RULE)])),
    "fillmass15": ("software from fill, 15% density error", ([], [(RULE, FILLM.format(f=DEV + " * ") + IND + RULE)])),
    "strokes": ("stroke count", strokes("clean")),
    "strokes15": ("stroke count, 15% kg/stroke error", strokes("dev15")),
    "st_spur": ("stroke count, +20% empty strokes", strokes("spur")),
    "st_drift": ("stroke count, +-20% seasonal drift", strokes("drift")),
    "st_miss": ("stroke count, 10% days lost, undetected", strokes("miss")),
    "st_missfb": ("stroke count, 10% days lost, fill fallback", strokes("missfb")),
    "st_hi": ("stroke count, calibrated 10% high", strokes("hi")),
    "fillcal": ("fill sensors calibrated at the factory, gauge", CAL),
    "fillcal_fm": ("fill sensors calibrated at the factory, kg from fill", (CAL[0], CAL[1] + [(RULE, FILLM.format(f="") + IND + RULE)])),
    "st_hab": ("strokes, site habits 1-20x, stream calibration, 10% high", strokes("hab")),
    "st_habcal": ("strokes, site habits 1-20x, 3 weighed lifts per site (8% site error), 10% high", strokes("habcal")),
    "st_habcal12": ("strokes, site habits 1-20x, 3 weighed lifts per site (12% site error), 10% high", strokes("habcal12")),
}


def patch(path, reps):
    s = open(path).read()
    for a, b in reps:
        if s.count(a) != 1:
            sys.exit(f"patch target not found once in {path}: {a}")
        s = s.replace(a, b)
    open(path, "w").write(s)


# patches a copy of the generator, never the original, and generates one world
def build(src, work, name, seed, ndev, workers):
    out = os.path.join(work, "out_" + name)
    if os.path.exists(os.path.join(out, "private_evaluation", "labels_test", "decision_outcomes.parquet")):
        return out
    pkg = os.path.join(work, "pkg_" + name)
    shutil.rmtree(pkg, ignore_errors=True)
    shutil.copytree(src, pkg, ignore=shutil.ignore_patterns("data", "reports", "__pycache__"))
    y, s = V[name][1]
    patch(os.path.join(pkg, "configs", "assumptions.yaml"), y)
    patch(os.path.join(pkg, "src", "europress_data", "simulate.py"), s)
    env = dict(os.environ, PYTHONPATH=os.path.join(pkg, "src"))
    cmd = [sys.executable, "-m", "europress_data.generate", "--profile", "competition", "--seed", str(seed),
           "--max-devices", str(ndev), "--out", out, "--workers", str(workers)]
    with open(os.path.join(work, name + ".log"), "w") as f:
        subprocess.run(cmd, cwd=pkg, env=env, stdout=f, stderr=subprocess.STDOUT, check=True)
    return out


# per decision case: best permissible benefit with the kilo trigger minus the best without it
def value(out):
    t = pd.read_parquet(os.path.join(out, "private_evaluation", "truth", "truth_collections.parquet"))
    c = pd.read_parquet(os.path.join(out, "public", "operations", "collection_events.parquet"), columns=["collection_id", "status", "device_mass_kg_before"])
    m = c[c.status == "COMPLETED"].merge(t, on="collection_id")
    m = m[m.true_mass_before_kg > 200].dropna(subset=["device_mass_kg_before"])
    err = (m.device_mass_kg_before - m.true_mass_before_kg).abs() / m.true_mass_before_kg
    o = pd.concat([pd.read_parquet(os.path.join(out, "public", "labels_dev", "decision_outcomes.parquet")),
                   pd.read_parquet(os.path.join(out, "private_evaluation", "labels_test", "decision_outcomes.parquet"))], ignore_index=True)
    o["b"] = np.where(o.permissible.astype(bool), o.benefit_vs_no_action_cents / 100, -np.inf)
    o.loc[o.action == "NO_ACTION", "b"] = 0.0
    o = o[o.case_id.isin(set(o[o.action == "MASS_TARGET_TRIGGER"].case_id))]
    w = o.groupby("case_id").b.max().clip(lower=0)
    wo = o[o.action != "MASS_TARGET_TRIGGER"].groupby("case_id").b.max().clip(lower=0)
    mt = o[o.action == "MASS_TARGET_TRIGGER"]
    add = w - wo
    return dict(gauge_err_med=round(err.median(), 4), cases=len(w), best_without_eur=round(wo.sum()), weight_adds_eur=round(add.sum()),
                eur_per_machine_year=round(add.mean() * 365 / 56), without_per_machine_year=round(wo.mean() * 365 / 56), total_per_machine_year=round(w.mean() * 365 / 56), kilo_best_share=round((add > 0).mean(), 3),
                kilo_permissible=round(mt.permissible.astype(bool).mean(), 3), overflow_h=round(mt.overflow_open_hours.mean(), 2))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--europress", required=True)
    p.add_argument("--work", required=True)
    p.add_argument("--results", default="results")
    p.add_argument("--variants", default="all")
    p.add_argument("--seed", type=int, default=31337)
    p.add_argument("--devices", type=int, default=250)
    p.add_argument("--workers", type=int, default=2)
    a = p.parse_args()
    names = list(V) if a.variants == "all" else a.variants.split(",")
    os.makedirs(a.work, exist_ok=True)
    os.makedirs(a.results, exist_ok=True)
    rows = []
    for n in names:
        out = build(a.europress, a.work, n, a.seed, a.devices, a.workers)
        rows.append(dict(variant=n, description=V[n][0], **value(out)))
        print(rows[-1], flush=True)
    d = pd.DataFrame(rows)
    if "base" in set(d.variant):
        d["vs_gauge"] = (d.eur_per_machine_year / d.loc[d.variant == "base", "eur_per_machine_year"].iloc[0]).round(3)
    d.to_csv(os.path.join(a.results, "sim_value.csv"), index=False)
    print(d.to_string(index=False))


if __name__ == "__main__":
    main()
