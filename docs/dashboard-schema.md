# Dashboard JSON schema

`dashboard/data.json` is reproducibly generated; never hand-edit its numbers.

- `project`, `data_kind`, `disclosure`, `currency`, `schema_version`: presentation metadata.
- `period`: `{start,end}` ISO event dates.
- `summary`: `{trips,fare_usd,avg_fare_usd,distance_miles,late_trips,late_trip_pct,period_start,period_end,raw_rows,rejected_rows,duplicate_rows,corrected_rows,committed_batches,rejection_pct,arrival_lag_p95_hours}`.
- `daily`: rows `{date,trips,fare_usd,avg_fare_usd,late_trips}`.
- `zones`: rows `{pickup_zone,zone,trips,fare_usd,avg_distance_miles,avg_duration_min,late_trips}`.
- `hourly`: rows `{hour,trips,fare_usd}`; hour is UTC 0–23 across the entire period.
- `batches`: committed ledger rows `{batch_id,sha256,raw_rows,accepted_rows,rejected_rows,duplicate_rows,corrected_rows,late_rows,received_at}`.
- `quarantine`: rows `{reason,rows}`.
- `quality_checks`: rows `{name,passed}`.
- `decision`: plain-language operating policy.
- `metric_notes`: key definitions for caveats and tooltips.

Recommended dashboard: top row canonical trips / quarantine share / duplicate deliveries / late share; daily trips plot; zone demand bar chart; batch ledger; quarantine reason breakdown; visible data provenance. A daily-date filter can aggregate `daily`; zone and hourly summaries remain full-period and must be labeled accordingly. No arbitrary joint date × zone filtering is available from these aggregate arrays.
