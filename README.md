# Every Press Counts

Europress challenge, Since AI Hackathon 2026, Turku.

A Europress compactor already counts every stroke of its ram, and every stroke pushes one charge of waste into the container. The strokes since the last lift, multiplied by the kilos one stroke carries at that site, give the weight in the container. Each site is taught its kilos per stroke once with 3 weighed lifts, so the weight comes without a permanent scale and without daily operator data.

SMART then orders lifts by kilos instead of by fill percentage. In Europress's own simulator this adds 23% to the value of the best decision available without weight. When every site presses alike, a stroke count set to read 10% high keeps 99% of the value a real scale on every machine would give. When sites press 1 to 20 times as often as each other, one average per stream keeps only 33% of that value, while teaching each site with 3 weighed lifts keeps 94%. Replayed on a year of telemetry, the rules would have held 1,713 of the 1,777 labeled unnecessary lifts they could see, and a watchdog that compares mass with volume caught 274 of 312 labeled stuck fill sensors.

All data is synthetic, and all euro figures use the dataset's hypothetical prices.

## Where to read

- [Part 1, getting the weight](docs/concept.md): the idea, how a site is taught, how the estimate checks itself, accuracy, the pressing-habit stress test, retrofit and cost.
- [Part 2, value, SMART and business](docs/value.md): where money is lost today, what lifting by kilos adds, one machine and one lift traced in detail, the SMART workflow and replay, what the data makes possible for Europress, and the rollout.
- [What this work rests on](docs/limits.md): assumptions, weak spots and what remains untested.
- [Third-party components and licenses](LICENSES.md).
- Live demo: https://theagleye.github.io/every-press-counts/demo/index.html
- Video (2:09): https://youtu.be/PVGid5Sl44U
- [All three reports as one PDF](docs/report.pdf), built from the same markdown by `scripts/build_pdf.py`.

## What each script does

- `analysis/strokes_eval.py` measures how well the stroke count matches weighbridge tickets, always learning kilos per stroke on other machines.
- `analysis/value_by_stream.py` values lifting by kilos per waste stream and per customer, and totals the labeled unnecessary lifts.
- `smart/replay.py` runs the SMART Weight rules hour by hour on a year of telemetry for all 447 machines and scores them against the official labels.
- `analysis/habits.py` gives every site a random pressing habit and tests eight ways to recover the weight, from a Kalman filter and gradient boosting to per-site teaching with a drift alarm.
- `analysis/data_uses.py` looks at what else the data shows: use per machine, rain, right-sizing and wear.
- `analysis/fiware_export.py` writes each machine's record as a FIWARE Smart Data Models `WasteContainer` entity and validates it against the schema.
- `sim/experiments.py` rebuilds Europress's world 25 times with its public generator, changing one thing per run, and values each run.
- `analysis/demo_data.py`, `analysis/figures.py` and `demo/build.py` prepare the demo data, draw the report figures and build the demo page.
- `results/` holds every output the documents quote.

## Setup

The scripts need the Europress package `Europress_SMART_Material_Value_Engine_v1.0.1`, which is not included, and Python 3.11 or newer.

```bash
conda create -n sinceai -c conda-forge --override-channels python=3.12 -y
conda activate sinceai
pip install -e "/path/to/Europress_SMART_Material_Value_Engine_v1.0.1[dev]"
pip install jsonschema==4.23.0 matplotlib==3.10.7
bash scripts/get_schemas.sh
```

## Run

```bash
EP=/path/to/Europress_SMART_Material_Value_Engine_v1.0.1
python analysis/strokes_eval.py --europress $EP
python analysis/value_by_stream.py --europress $EP
python smart/replay.py --europress $EP
python analysis/habits.py --europress $EP
python analysis/data_uses.py --europress $EP
python analysis/fiware_export.py --europress $EP
python sim/experiments.py --europress $EP --work /tmp/ep_sim
python analysis/demo_data.py --europress $EP
python analysis/figures.py
python demo/build.py
```

`results/europress_accuracy_example.txt` is the output of Europress's own `examples/weighing_accuracy_value.py` with `--sigmas 1.5,10`, run from the package folder.

`sim/experiments.py` generates 25 worlds of 250 machines each, which took about one minute per world on two CPU cores. It copies the generator to the work folder and patches only the copy.
