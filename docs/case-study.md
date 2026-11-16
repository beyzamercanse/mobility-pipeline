# Case study: making a moving dataset trustworthy

Generated trip data (seed 4026), 1–14 January 2026. Numbers come from `dashboard/data.json` after a clean run.

## The problem

An operations analyst reports daily trips and fares. The feed resends records, delivers some trips late and corrects fares afterwards. With an append-only load, repeated deliveries inflate counts, late trips land on the wrong day, and yesterday's total changes without anyone knowing why.

## What I built

Raw batches stay immutable, with a checksum manifest. Each batch loads in one transaction into a canonical `trips` table (latest version per trip), with bad rows quarantined next to it and a ledger row describing what happened. Daily, zone and hourly marts are built by event date. The dashboard file is only replaced after reconciliation passes.

## What the run shows

- 7,679 rows delivered → 7,200 canonical trips. 297 duplicates suppressed, 80 rows quarantined, 102 corrections applied. Every input row is accounted for.
- Quarantine is 1.04% of input, just over the 1% threshold I'd use to open an investigation. The rejects split evenly across four causes (20 each): invalid fare, unknown zone, missing field, impossible duration. That pattern points to the source, so the response is to raise it with the provider and keep the evidence, not to loosen the rules.
- 475 current trips (6.60%) arrived more than 24 hours after dropoff. That count includes corrections, so it measures feed lateness, not pipeline runtime.

## Restatements

This was the part I added after the first version. Event-time marts are correct, but they also mean a published day can change. I snapshot every day's numbers after each batch (in the same transaction) and compare each day's first published value with its current one.

| Batch | Trips added to published days | Fare change | Days changed |
|---|---:|---:|---:|
| 02-late-arrivals | +379 | +$9,205.00 | 14 |
| 03-corrections | 0 | +$255.00 | 14 |

All 14 days moved after first publication, each by about 27 trips and 4.8–7.5% of fare. The biggest single change was 1 January, +$848.49 (+7.47%). With a p95 arrival lag of 50 hours, I'd label a day *provisional* for its first two days and *final* after that. The restatement table is the evidence for that rule.

## Engineering takeaways

- Skipping an already-loaded batch and deduplicating events are two separate protections. You need both.
- Corrections only work if the source has a stable ID and an update timestamp. Public TLC data has neither, so it needs a different adapter.
- Group by event date, not arrival date. Otherwise late trips distort daily demand.
- Rejected rows can bias the metrics, so quarantine counts belong on the same dashboard as the metrics.
- The transaction and the file write are separate boundaries. If the write fails after a commit, the database is ahead of the dashboard; the runbook covers replaying the export.

## Limits and next step

Single writer, local, small. No production throughput or cloud deployment. The next milestone is one real TLC month through a Parquet adapter, with source-file lineage and a measured runtime and cost.
