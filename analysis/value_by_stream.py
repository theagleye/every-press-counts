# Value of lifting by kilos on the official decision cases, per waste stream and per customer, and the labeled unnecessary lifts.
import argparse
import os
import sys
import numpy as np
import pandas as pd


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--europress", required=True)
    p.add_argument("--results", default="results")
    a = p.parse_args()
    sys.path.insert(0, os.path.join(a.europress, "src"))
    from europress_data.sdk import open_dataset
    pub = os.path.join(a.europress, "data", "competition", "public")
    con = open_dataset(pub)
    o = pd.read_parquet(os.path.join(pub, "labels_dev", "decision_outcomes.parquet"))
    # benefit of each action; actions that break the interval or overflow rules cannot be chosen
    o["b"] = np.where(o.permissible.astype(bool), o.benefit_vs_no_action_cents / 100, -np.inf)
    o.loc[o.action == "NO_ACTION", "b"] = 0.0
    o = o[o.case_id.isin(set(o[o.action == "MASS_TARGET_TRIGGER"].case_id))]
    w = o.groupby("case_id").b.max().clip(lower=0)
    wo = o[o.action != "MASS_TARGET_TRIGGER"].groupby("case_id").b.max().clip(lower=0)
    # what weight adds: best benefit with the kilo trigger minus best benefit without it
    d = pd.DataFrame({"add": w - wo, "tot": w}).reset_index()
    d = d.merge(con.sql("SELECT case_id, device_id FROM decision_cases").df(), on="case_id")
    d = d.merge(con.sql("SELECT device_id, material_stream stream FROM devices").df(), on="device_id")
    g = d.groupby("stream").agg(cases=("add", "size"), weight_adds_eur=("add", "sum"), per_case_eur=("add", "mean"))
    g["eur_per_machine_year"] = (g.per_case_eur * 365 / 56).round(0)
    g = g.round(2).sort_values("eur_per_machine_year", ascending=False)
    os.makedirs(a.results, exist_ok=True)
    g.to_csv(os.path.join(a.results, "value_by_stream.csv"))
    m = d.groupby("device_id")["add"].mean().mul(365 / 56).rename("eur_per_year").reset_index()
    m = m.merge(con.sql("SELECT device_id, customer_id FROM devices").df(), on="device_id")
    c = m.groupby("customer_id").agg(machines=("device_id", "size"), eur_per_year=("eur_per_year", "sum")).round(0)
    c.sort_values("eur_per_year", ascending=False).to_csv(os.path.join(a.results, "value_by_customer.csv"))
    print("customers", len(c), "| machines per customer median", c.machines.median(), "max", c.machines.max(),
          "| EUR per customer-year median", c.eur_per_year.median(), "p90", c.eur_per_year.quantile(.9), "max", c.eur_per_year.max())
    lab = con.sql("""SELECT explanation_code, count(*) n, round(sum(value_at_stake_eur)) eur, min(event_at)::DATE d0, max(event_at)::DATE d1
      FROM anomaly_labels WHERE label_family = 'PREMATURE_UNJUSTIFIED' GROUP BY 1 ORDER BY eur DESC""").df()
    lab.to_csv(os.path.join(a.results, "premature_lifts.csv"), index=False)
    print(g.to_string())
    print(f"all streams: per machine-year {d['add'].mean() * 365 / 56:.0f} | weight share of decision value {d['add'].sum() / d.tot.sum():.3f} | cases {len(d)}")
    print(lab.to_string(index=False), "| total", lab.eur.sum())


if __name__ == "__main__":
    main()
