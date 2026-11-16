# Data dictionary and metric contract

All demo records are synthetic. Zone IDs 1–8 are local labels; they are not TLC LocationIDs.

| Field | Contract |
| --- | --- |
| `trip_id` | nonempty stable application-provided string; canonical fact key |
| `pickup_at`, `dropoff_at` | canonical UTC ISO strings; duration >0 and <=6 hours |
| `pickup_zone`, `dropoff_zone` | integer in the local demo mapping 1–8 |
| `distance_miles` | finite numeric value >0 and <=150 |
| `fare_usd` | finite numeric positive fare <=1,000; excludes extras |
| `updated_at` | source version timestamp, at or after dropoff |
| `received_at` | ingestion timestamp at or after source update |
| `arrival_lag_hours` | `(received_at - dropoff_at) / 3600`, computed |
| `source_batch` | most recent accepted source version's batch identifier |

Unexpected or missing record fields violate the schema. Booleans are not accepted as numeric values. The source-specific positive-fare rule does not imply that all legitimate real taxi records must have positive fare; a real-source adapter needs documented handling for refunds, reversals and adjustments.

Metric definitions:

- **Trips:** current canonical rows, one per `trip_id`.
- **Fare:** sum of positive fare amounts across canonical facts; USD. This is not company revenue.
- **Average fare:** fare / trips.
- **Late trip:** canonical record with arrival lag strictly greater than 24 hours. A later correction can make a previously timely trip qualify under this metric.
- **Late trip percentage:** late trips / canonical trips ×100.
- **P95 arrival lag:** nearest-rank percentile of current canonical lag; this is event-time delivery delay, not pipeline runtime.
- **Rejected rows:** quarantined source deliveries, including invalid JSON/schema/values and same-version conflicts.
- **Rejection percentage:** rejected input rows / all raw input deliveries ×100; duplicates remain in the denominator.
- **Duplicates:** identical or stale deliveries ignored after a matching trip key is present. Out-of-order processing may change operational counters while final canonical metrics remain invariant.
- **Corrections:** incoming newer versions that replace a trip already present; a correction arriving first is an initial insert, not a correction counter event.
- **Accepted rows:** inserted or updated deliveries. Includes corrections and is therefore not equal to canonical trips.

Row accounting: `raw_rows = accepted_rows + rejected_rows + duplicate_rows` for every committed batch. `corrected_rows` and `late_rows` are subsets of accepted rows, not additional categories.

All rates and totals are calculated from SQL/pipeline output. The dashboard must label synthetic data and use the original metric denominators when filtering. Zone and hourly arrays have distinct grains and cannot be freely cross-filtered without trip-level data.
