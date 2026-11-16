# Case study: make a changing operational dataset trustworthy

**Setting:** portfolio simulation, 1–14 January 2026, deterministic seed 4026. These findings describe generated data and tested behavior, not a real taxi operator.

## Question and approach

Can an analyst trust daily trip totals when the provider resends records and later changes fare values? I separated raw delivery history from the current business fact, then published a dashboard only after reconciliation.

The fixture contains a primary delivery, late arrivals and fare corrections. I deliberately injected invalid fare values, unknown zones, missing fields and impossible trip durations. Each batch is checksum-verified and processed transactionally.

## Measured evidence

The normal ordered run processes 7,679 delivery rows into 7,200 canonical trips. It suppresses 297 duplicate deliveries, quarantines 80 invalid records, and applies 102 corrections. Every input row is accounted for. Canonical positive fare totals $170,755.66; this is a fixture check, not platform revenue.

The quarantine rate is 1.04%, exceeding the proposed 1% investigation threshold. Twenty records occur in each of four categories: invalid fare, unknown zone, missing schema field and invalid duration. The appropriate response is to inspect and repair the source, retaining the rejected evidence.

The final canonical dataset has 475 late records (6.60%). The count includes newer corrections arriving more than 24 hours after dropoff. It should not be interpreted as a customer-service delay or pipeline execution latency.

## Engineering conclusions

- Batch idempotency prevents reloading the same immutable file; event deduplication prevents repeated records across different files.
- Source update version and stable business identity are necessary for safe correction logic. Neither can be assumed for a public dataset that lacks them.
- Event-time marts correct the original business date. Using arrival date would misstate daily demand.
- Input rejection can bias analytics, so quality evidence belongs beside the business metrics.
- Transaction rollback and atomic publication are different boundaries. A failed dashboard write can leave a newer database with an older view; the documented replay procedure repairs that gap.

## Five-slide interview story

1. **Problem:** repeated and delayed deliveries make yesterday's trip total move.
2. **Design:** immutable raw evidence → canonical fact → reconciled marts → atomic snapshot.
3. **Evidence:** input accounting, 297 suppressed deliveries, 80 visible rejects, 102 applied corrections.
4. **Failure demo:** deliberately crash a batch and rerun it without partial or duplicate facts.
5. **Next step:** process one real public monthly source with explicit lineage and benchmark the actual environment.

## Limitations and next experiment

The pipeline is single-writer, local and small. It models a source with stable trip identifiers and update timestamps; official TLC data requires a different source adapter. No production throughput, cloud deployment, real-time SLA or business savings are claimed. The most valuable next milestone is a documented real-source ingestion with source-specific data quality and a measured cost/runtime report.
