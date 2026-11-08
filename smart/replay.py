# Replays the SMART Weight rules hour by hour on a year of telemetry. Each hour uses only readings up to that hour.
import argparse
import json
import os
import sys
import numpy as np
import pandas as pd
import yaml


# one machine: split its hours into fill cycles at completed lifts, then apply the rules to every hour
def run(tel, lifts, kps, cap, high, fill_fallback):
    t = tel.sort_values("measured_at").reset_index(drop=True)
    lt = lifts.actual_at.values
    c = np.searchsorted(lt, t.measured_at.values, side="left")
    t["cycle"] = c
    t["start"] = pd.Series(pd.to_datetime(lt, utc=True)).reindex(c - 1).set_axis(t.index)
    g = t.groupby("cycle")
    t["strokes"] = g.compaction_cycles.cumsum()
    t["msgs"] = g.cumcount() + 1
    t["hrs"] = ((t.measured_at - t.start).dt.total_seconds() / 3600).clip(lower=1)
    t["kg"] = t.strokes * kps * high
    t["frac"] = t.kg / cap
    # normal confidence needs 95% of hourly messages and an estimate below 1.3 x capacity
    t["ok"] = (t.msgs / t.hrs >= 0.95) & (t.frac <= 1.3)
    # watchdog: fill says nearly full while the strokes say under 40%, so the fill sensor is stuck
    t["suspect"] = t.ok & (t.hrs >= 6) & (t.fill_pct >= 85) & (t.frac < 0.4)
    # lift call: kilos at 80%, fill stop at 98% unless the fill sensor is suspect, fill fallback when confidence is low
    t["rec"] = np.select([t.ok & (t.frac >= 0.8), ~t.suspect & (t.fill_pct >= 98), ~t.ok & (t.fill_pct >= fill_fallback)], ["kilos", "fill stop", "fill fallback"], "")
    return t[t.start.notna() & (t.cycle < len(lt))]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--europress", required=True)
    p.add_argument("--results", default="results")
    p.add_argument("--high", type=float, default=1.1)
    p.add_argument("--fill-fallback", type=float, default=90.0)
    p.add_argument("--trace-device", default="CMP-00168")
    p.add_argument("--trace-from", default="2026-04-15 09:00")
    p.add_argument("--trace-to", default="2026-04-27 06:00")
    a = p.parse_args()
    sys.path.insert(0, os.path.join(a.europress, "src"))
    from europress_data.sdk import open_dataset
    con = open_dataset(os.path.join(a.europress, "data", "competition", "public"))
    mats = yaml.safe_load(open(os.path.join(a.europress, "configs", "assumptions.yaml")))["materials"]
    kps = pd.read_csv(os.path.join(a.results, "kg_per_stroke.csv")).set_index("stream").kg_per_stroke
    dev = con.sql("SELECT device_id, material_stream mat, container_volume_m3 vol, equipment_class eq, customer_id cust FROM devices").df().set_index("device_id")
    lifts = con.sql("SELECT device_id, collection_id, actual_at, original_trigger_type trig FROM collection_events WHERE status = 'COMPLETED' ORDER BY device_id, actual_at").df()
    tel = con.sql("SELECT device_id, measured_at, fill_pct, coalesce(compaction_cycles, 0) compaction_cycles FROM telemetry_dedup").df()
    lg, rows, traces, hours = lifts.groupby("device_id"), [], {}, []
    for d, td in tel.groupby("device_id"):
        if d not in lg.groups:
            continue
        m = mats[dev.mat[d]]
        cap = dev.vol[d] * m["compacted_density"] * (1 + m["compressibility"] / 2)
        ld = lg.get_group(d).reset_index(drop=True)
        r = run(td, ld, kps[dev.mat[d]], cap, a.high, a.fill_fallback)
        traces[d] = r
        hours.append(r[["measured_at", "suspect"]].assign(device_id=d))
        for c, x in r.groupby("cycle"):
            last, rec = x.iloc[-1], x[x.rec != ""]
            first = rec.iloc[0] if len(rec) else None
            rows.append(dict(device_id=d, stream=dev.mat[d], cycle=int(c), collection_id=ld.collection_id[c], trigger=ld.trig[c], fill_at_lift=round(float(last.fill_pct), 1), hours=round(float(last.hrs), 1), strokes=int(last.strokes), kg_at_lift=round(float(last.kg)),
                             frac_at_lift=round(float(last.frac), 3), ok_at_lift=bool(last.ok), first_rec=first.rec if first is not None else "none",
                             rec_hours_before_lift=round(float(last.hrs - first.hrs), 1) if first is not None else None))
    cy = pd.DataFrame(rows)
    os.makedirs(a.results, exist_ok=True)
    cy.to_csv(os.path.join(a.results, "replay_cycles.csv"), index=False)
    sm = dict(machines=int(cy.device_id.nunique()), fill_cycles=len(cy), low_confidence_at_lift=round(float((~cy.ok_at_lift).mean()), 3),
             median_kg_share_of_capacity_at_lift=round(float(cy.frac_at_lift[cy.ok_at_lift].median()), 3),
             lifts_before_kilo_target=round(float((cy.frac_at_lift[cy.ok_at_lift] < 0.8).mean()), 3),
             first_call=cy.first_rec.value_counts(normalize=True).round(3).to_dict())
    print(json.dumps(sm, indent=1))
    tg = cy[cy.ok_at_lift].groupby("trigger").agg(cycles=("cycle", "size"), kg_share_at_lift=("frac_at_lift", "median"), fill_at_lift=("fill_at_lift", "median"),
                                                  before_target=("frac_at_lift", lambda x: (x < 0.8).mean())).round(3).sort_values("cycles", ascending=False)
    tg.to_csv(os.path.join(a.results, "replay_by_trigger.csv"))
    print(tg.to_string())
    # score against the official labels: would the strokes have held the labeled unnecessary lifts?
    lab = con.sql("SELECT entity_id collection_id, explanation_code why, value_at_stake_eur eur FROM anomaly_labels WHERE label_family = 'PREMATURE_UNJUSTIFIED'").df()
    j = cy.merge(lab, on="collection_id", how="left")
    j["held"] = j.ok_at_lift & (j.frac_at_lift < 0.8)
    pr = j[j.why.notna()].groupby("why").agg(lifts=("held", "size"), eur=("eur", "sum"), held=("held", "sum"),
                                            eur_held=("eur", lambda e: e[j.loc[e.index, "held"]].sum())).round(2)
    pr.loc["all"] = pr.sum()
    pr.to_csv(os.path.join(a.results, "replay_premature.csv"))
    print(pr.to_string())
    oc = j[j.trigger == "ON_CALL_ORDER"]
    print("on-call lifts held: labeled premature", round(oc[oc.why.notna()].held.mean(), 3), "| not labeled", round(oc[oc.why.isna()].held.mean(), 3))
    # how many labeled stuck-sensor periods the watchdog catches
    win = con.sql("SELECT device_id, event_at, end_at FROM anomaly_labels WHERE label_family = 'FILL_SENSOR_FALSE_HIGH' AND entity_type = 'device_period'").df()
    h = pd.concat(hours)
    h["inwin"], caught = False, 0
    for w in win.itertuples():
        k = (h.device_id == w.device_id) & (h.measured_at >= w.event_at) & (h.measured_at < w.end_at)
        h.loc[k, "inwin"] = True
        caught += bool(h.suspect[k].any())
    wd = dict(windows=len(win), caught=caught, caught_share=round(caught / len(win), 3), alarm_hours=int(h.suspect.sum()),
              alarm_hours_in_windows=round(float(h.inwin[h.suspect].mean()), 3), machines_alarmed_outside=int(h.device_id[h.suspect & ~h.inwin].nunique()))
    sm["watchdog"] = wd
    ah = cy[(cy.trigger == "AD_HOC_CUSTOMER") & cy.ok_at_lift]
    sm["ad_hoc_customer_lifts"] = dict(lifts=len(ah), kilo_call_first=round(float((ah.first_rec == "kilos").mean()), 3),
                                       median_hours_ahead=float(ah.rec_hours_before_lift[ah.first_rec == "kilos"].median()))
    sm["labeled_premature"] = dict(lifts=int(pr.loc["all", "lifts"]), held=int(pr.loc["all", "held"]), eur=float(pr.loc["all", "eur"]), eur_held=float(pr.loc["all", "eur_held"]),
                                   on_call_held_labeled=round(float(oc[oc.why.notna()].held.mean()), 3), on_call_held_not_labeled=round(float(oc[oc.why.isna()].held.mean()), 3))
    json.dump(sm, open(os.path.join(a.results, "replay_summary.json"), "w"), indent=1)
    print("watchdog", wd)
    st = cy[cy.ok_at_lift].groupby("stream").agg(cycles=("cycle", "size"), kg_share_at_lift=("frac_at_lift", "median"),
                                                 before_target=("frac_at_lift", lambda x: (x < 0.8).mean())).round(3)
    st.to_csv(os.path.join(a.results, "replay_by_stream.csv"))
    print(st.to_string())
    # the frozen-sensor example for the demo
    d, t0, t1 = a.trace_device, pd.Timestamp(a.trace_from, tz="UTC"), pd.Timestamp(a.trace_to, tz="UTC")
    x = traces[d][(traces[d].measured_at >= t0) & (traces[d].measured_at < t1)]
    hr = lambda v: round((v - t0).total_seconds() / 3600, 1)
    ev = con.sql(f"""SELECT collection_id, actual_at, status, original_trigger_type trig, device_mass_kg_before gauge_kg FROM collection_events
                     WHERE device_id = '{d}' AND actual_at >= '{t0}' AND actual_at < '{t1}' ORDER BY actual_at""").df()
    ev = ev.merge(lab, on="collection_id", how="left")
    pre = [x[x.measured_at < v] for v in ev.actual_at]
    ev["kg_at_lift"] = [round(float(q.kg.iloc[-1])) if len(q) else np.nan for q in pre]
    ev["frac_at_lift"] = [float(q.frac.iloc[-1]) if len(q) else np.nan for q in pre]
    ev["held"] = [bool(q.ok.iloc[-1] and q.frac.iloc[-1] < 0.8) if len(q) else np.nan for q in pre]
    lw = con.sql(f"""SELECT label_family, explanation_code, event_at, end_at FROM anomaly_labels
                     WHERE device_id = '{d}' AND entity_type <> 'collection' AND end_at > '{t0}' AND event_at < '{t1}'""").df()
    m = mats[dev.mat[d]]
    tr = dict(device=d, customer=dev.cust[d], stream=dev.mat[d], equipment=dev["eq"][d], volume_m3=float(dev.vol[d]), kg_per_stroke=round(float(kps[dev.mat[d]] * a.high), 2),
              capacity_kg=round(float(dev.vol[d] * m["compacted_density"] * (1 + m["compressibility"] / 2))), t0=str(t0),
              hours=[hr(v) for v in x.measured_at], frac=x.frac.round(3).tolist(), fill=x.fill_pct.round(1).tolist(), ok=x.ok.astype(int).tolist(), suspect=x.suspect.astype(int).tolist(),
              events=[dict(id=e.collection_id, h=hr(e.actual_at), at=str(e.actual_at)[:16], status=e.status, trigger=e.trig,
                           gauge_kg=None if pd.isna(e.gauge_kg) else float(e.gauge_kg), est_kg=None if pd.isna(e.kg_at_lift) else float(e.kg_at_lift),
                           frac=None if pd.isna(e.frac_at_lift) else round(e.frac_at_lift, 3), held=bool(e.held) if e.held == e.held else None,
                           label=None if pd.isna(e.why) else e.why, eur=None if pd.isna(e.eur) else round(float(e.eur), 2)) for e in ev.itertuples()],
              windows=[dict(label=w.label_family, why=w.explanation_code, h0=hr(w.event_at), h1=hr(w.end_at)) for w in lw.itertuples()])
    json.dump(tr, open(os.path.join(a.results, "replay_trace.json"), "w"), indent=1)
    print("trace", d, dev.mat[d], "points", len(tr["hours"]), "events", len(tr["events"]), "windows", len(tr["windows"]))


if __name__ == "__main__":
    main()
