# Fills the demo template with the result files, so the page shows exactly what the scripts produced.
import json
import os
import pandas as pd

R = os.path.join(os.path.dirname(__file__), "..", "results")
D = os.path.dirname(__file__)


def csv(name):
    return pd.read_csv(os.path.join(R, name)).to_dict("records")


def main():
    d = json.load(open(os.path.join(R, "demo_data.json")))
    d["strokes_eval"] = csv("strokes_eval.csv")
    d["sim_value"] = csv("sim_value.csv")
    d["by_stream"] = csv("value_by_stream.csv")
    d["kps"] = csv("kg_per_stroke.csv")
    d["habits"] = csv("habits_eval.csv")
    d["habits_extra"] = csv("habits_extra.csv")
    d["replay"] = json.load(open(os.path.join(R, "replay_trace.json")))
    d["replay_summary"] = json.load(open(os.path.join(R, "replay_summary.json")))
    d["by_trigger"] = csv("replay_by_trigger.csv")
    c = pd.read_csv(os.path.join(R, "value_by_customer.csv")).set_index("customer_id")
    d["customers"] = dict(n=len(c), machines_median=float(c.machines.median()), median=float(c.eur_per_year.median()),
                          p90=round(float(c.eur_per_year.quantile(0.9))), top=c.eur_per_year.idxmax(), top_eur=float(c.eur_per_year.max()),
                          top_machines=int(c.machines[c.eur_per_year.idxmax()]), ex=d["replay"]["customer"], ex_eur=float(c.eur_per_year[d["replay"]["customer"]]),
                          ex_machines=int(c.machines[d["replay"]["customer"]]))
    f = json.load(open(os.path.join(R, "fiware_ngsild.json")))
    d["fiware"] = next(x for x in f if x["cargoWeight"]["confidence"]["value"] == "normal" and x["cargoWeight"]["value"] > 500)
    t = open(os.path.join(D, "template.html")).read()
    open(os.path.join(D, "index.html"), "w").write(t.replace("/*DATA*/null", json.dumps(d, separators=(",", ":"))))
    print("demo/index.html written")


if __name__ == "__main__":
    main()
