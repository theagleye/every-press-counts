# What this work rests on, and what it does not show

## What it assumes

The concept assumes that real SMART controllers log the number of compaction strokes, as the dataset's `compaction_cycles` field does. Every stroke is started by the controller, so a machine generation that does not report the count needs a firmware change, not new hardware, but this has not been confirmed with Europress.

It also assumes that each site can be taught once with 3 weighed lifts, either from 3 weighbridge tickets asked for at setup or from a mobile calibration kit, and that a site's pressing habit stays stable between drift alarms. The waste stream configured in SMART is assumed to be correct, because it sets the start value before the site is taught.

The kilo trigger, a lift at 80% of the container's capacity in kilos, is the rule Europress's simulator uses. Capacity in kilos comes from the generator's own formula, volume x compacted density x (1 + compressibility / 2).

## Where the evidence is weaker than it looks

All data is synthetic, and all euro figures use the dataset's hypothetical prices. The simulator creates strokes from waste deposits with a fixed mean mass per deposit for each stream, so stroke counting works there partly by construction. The pressing-habit stress test exists to break that, but its habits are injected by this work, not observed, so only a pilot can show how far real sites differ. The scenario where sites press less often per kilo thins strokes at random, which overstates the error of sites that wait for a full hopper.

In the simulator, site habits stay stable and the error left after teaching a site is a fixed spread of 8% or 12%, taken from the stress test. The value of the drift alarm under changing habits is not in the euro figures. The stroke estimate in the simulator also starts each fill from the true leftover mass after the previous lift, which is a small advantage over real operation.

Several settings were chosen by hand on this dataset: the 1.1 safety factor, the stuck-sensor watchdog (fill at 85%, kilos under 40%, 6 hours after a lift, picked from three tried settings), the drift alarm (2 times for 3 lifts, picked from four tried settings), the Kalman drift setting and the gradient-boosting settings. They need confirming on real data. The watchdog's alarms fall outside labeled stuck-sensor periods in 14.6% of alarm hours.

The replay learns kilos per stroke on all machines, so it is in-sample, while the accuracy figures always learn on other machines. A partial lift does not reset the stroke count in the replay, so the estimate reads high until the next completed lift.

## What the stroke count cannot do

The stroke count misses the brief's simulation target of about ±100 kg on a 3 t load: only 34.0% of loads between 2.5 and 3.5 t are within it. It is good enough to decide when to lift and to report cost per tonne, but not to check an operator's tonnage, which needs a reference gauge or a weighbridge ticket. On all lifts, 1 in 10 is off by more than 61%, mostly overestimates, and the capacity check brings that to 24.7%. Underestimation by more than 20% happens in 2.5% of lifts, mostly where telemetry has gaps.

The conformal 90% ranges covered only 86% to 87% of true weights, so they are not used.

## What was not priced

The mobile calibration kit, the reference gauges, their installation, kit transport, the firmware change and cloud compute were not priced. The kit price comes from one listed container scale. The technician time, kit life and kit use per year are assumptions, and the software effort is a guess.

## What remains untested

- Stroke counting, per-site teaching and the drift alarm on real Europress machines.
- The mobile calibration kit, and gauge designs for COMBI feet and DUO rails.
- Reading each stroke's hydraulic pressure curve to size the charge and catch empty presses. It measures charge volume, not mass, and the dataset has no pressure curves.
- Heavy single items and rain, which make the estimate read low. In this dataset, sites that store material outdoors show no visible effect on kilos per stroke.
- Stroke counting from pump motor current on machines without a cycle counter.
- Use-based service planning, which the synthetic data cannot test because it does not link breakdowns to use.
- Weather and holiday forecasts of kilos, data products for haulers, recyclers and cities, and the customer consent they need.
- A live FIWARE context broker. The records were validated against the Smart Data Models schema only. The synthetic sites have no coordinates, so the records leave out `location`, which a site address or GPS fix would fill in production.
