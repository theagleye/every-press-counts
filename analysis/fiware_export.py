# Writes each machine's latest state as a FIWARE Smart Data Models WasteContainer entity and validates it against the schema.
import argparse
import json
import os
import sys
import jsonschema
import pandas as pd
import yaml
from referencing import Registry, Resource

CTX = ["https://raw.githubusercontent.com/smart-data-models/dataModel.WasteManagement/master/context.jsonld",
       "https://uri.etsi.org/ngsi-ld/v1/ngsi-ld-core-context.jsonld"]
KIND = {"cardboard": "paper", "paper": "paper", "plastic_film": "plastic", "mixed_plastic": "plastic", "biowaste": "organic", "mixed_waste": "other"}
ORIGIN = {"hospitality_hotel": "hostelry", "manufacturing": "industrial", "food_processing": "industrial"}
SQL = """WITH last AS (SELECT device_id, max(actual_at) last_at FROM collection_events WHERE status = 'COMPLETED' GROUP BY 1),
now AS (SELECT max(measured_at) t FROM telemetry_dedup)
SELECT d.device_id, d.material_stream mat, d.container_volume_m3 vol, s.sector, l.last_at, n.t now_at,
  arg_max(x.fill_pct, x.measured_at) fill, sum(coalesce(x.compaction_cycles, 0)) cyc, count(x.measured_at) msgs
FROM devices d JOIN sites s USING (site_id) JOIN last l USING (device_id) CROSS JOIN now n
LEFT JOIN telemetry_dedup x ON x.device_id = d.device_id AND x.measured_at > l.last_at
GROUP BY ALL
ORDER BY d.device_id"""


# synthetic sites have no coordinates, so location is removed from the required fields
def drop_location(o):
    if isinstance(o, dict):
        if "location" in o.get("required", []):
            o["required"] = [x for x in o["required"] if x != "location"]
        for x in o.values():
            drop_location(x)
    elif isinstance(o, list):
        for x in o:
            drop_location(x)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--europress", required=True)
    p.add_argument("--schema", default="schema/WasteContainer.schema.json")
    p.add_argument("--common", default="schema/common-schema.json")
    p.add_argument("--results", default="results")
    p.add_argument("--high", type=float, default=1.1)
    a = p.parse_args()
    sys.path.insert(0, os.path.join(a.europress, "src"))
    from europress_data.sdk import open_dataset
    con = open_dataset(os.path.join(a.europress, "data", "competition", "public"))
    mats = yaml.safe_load(open(os.path.join(a.europress, "configs", "assumptions.yaml")))["materials"]
    kps = pd.read_csv(os.path.join(a.results, "kg_per_stroke.csv")).set_index("stream").kg_per_stroke
    d = con.sql(SQL).df()
    hrs = (d.now_at - d.last_at).dt.total_seconds() / 3600
    d["cover"] = d.msgs / hrs.clip(lower=1)
    schema, common = json.load(open(a.schema)), json.load(open(a.common))
    drop_location(schema)
    val = jsonschema.Draft202012Validator(schema, registry=Registry().with_resource(common["$id"], Resource.from_contents(common)))
    kv, nl, low = [], [], {"gap": 0, "over": 0}
    for r in d.itertuples():
        m = mats[r.mat]
        cap = r.vol * m["compacted_density"] * (1 + m["compressibility"] / 2)
        kg = round(r.cyc * kps[r.mat] * a.high)
        # confidence: a telemetry gap or an over-read makes the weight low confidence
        why = "telemetry gap, use fill" if r.cover < 0.95 else "above 1.3 x capacity, over-read" if kg > 1.3 * cap else None
        ok = why is None
        if not ok:
            low["gap" if r.cover < 0.95 else "over"] += 1
        e = {"id": f"urn:ngsi-ld:WasteContainer:{r.device_id}", "type": "WasteContainer",
             "fillingLevel": round(float(r.fill) / 100, 3) if pd.notna(r.fill) else None, "cargoWeight": kg if ok else None,
             "binMaxLoad": round(cap), "storedWasteKind": KIND[r.mat], "storedWasteOrigin": ORIGIN.get(r.sector, "other"),
             "dateLastEmptying": r.last_at.isoformat(), "status": "ok"}
        e = {k: v for k, v in e.items() if v is not None}
        val.validate(e)
        kv.append(e)
        n = {"id": e["id"], "type": "WasteContainer", "@context": CTX}
        for k in ("fillingLevel", "binMaxLoad", "storedWasteKind", "storedWasteOrigin", "status"):
            if k in e:
                n[k] = {"type": "Property", "value": e[k], "observedAt": r.now_at.isoformat()}
        n["dateLastEmptying"] = {"type": "Property", "value": {"@type": "DateTime", "@value": e["dateLastEmptying"]}}
        # NGSI-LD sub-properties say how the weight was made, so nobody mistakes it for a scale reading
        n["cargoWeight"] = {"type": "Property", "value": kg, "unitCode": "KGM", "observedAt": r.now_at.isoformat(),
                            "measurementMethod": {"type": "Property", "value": "estimated:stroke-count"},
                            "confidence": {"type": "Property", "value": "normal" if ok else "low: " + why},
                            "kgPerStroke": {"type": "Property", "value": round(float(kps[r.mat]) * a.high, 2)},
                            "compactionCycles": {"type": "Property", "value": int(r.cyc)}}
        nl.append(n)
    json.dump(kv, open(os.path.join(a.results, "fiware_keyvalues.json"), "w"), indent=1)
    json.dump(nl, open(os.path.join(a.results, "fiware_ngsild.json"), "w"), indent=1)
    json.dump(nl[:3], open(os.path.join(a.results, "fiware_sample.json"), "w"), indent=1)
    print(f"containers {len(kv)} | schema-valid {len(kv)} (location not required: synthetic sites have no coordinates) | low confidence {low}")
    print(json.dumps(nl[0], indent=1)[:1500])


if __name__ == "__main__":
    main()
