# Incident runbook

## 1. Checksum mismatch or schema version change

**Symptom:** the pipeline exits before loading a batch. **Impact:** prior dashboard snapshot remains; no rows from that failed batch are committed.

1. Inspect the manifest and compare its expected SHA-256 with the stored bytes.
2. Preserve the suspect batch for diagnosis; do not “fix” the checksum to force a load.
3. Ask the source owner for a corrected export, saved under a new batch ID.
4. If the contract genuinely changed, version the adapter and tests before processing.
5. Replay with `--batch filename.manifest.json`, then verify the ledger and reconciliation.

## 2. Reject-rate alert

The proposed operational threshold is >1%; the synthetic fixture deliberately triggers it at 1.04%. No automated alert dispatch is implemented.

1. Inspect `dashboard/data.json` → `quarantine`, then query `quarantine` for raw lines.
2. Classify schema, unknown-zone, duration and fare defects separately.
3. Confirm the accepted facts are still fit for the intended use; high rejection may bias demand totals.
4. Fix the upstream data/contract. Submit a new correction batch; retain rejected evidence.
5. Do not delete the old reject ledger or quietly replace the original file.

## 3. Worker failure during a batch

`tests/test_pipeline.py::test_worker_failure_rolls_back_entire_batch` injects an exception after a row and asserts facts plus batch ledger remain empty. Rerunning the same batch then succeeds. The transaction handles SQLite commit atomicity; local raw files stay intact.

Run the drill:

```bash
python3 -m unittest discover -s tests -v
```

## 4. Late deliveries or corrections

Use the source update timestamp to choose the canonical row. Verify the original pickup date's total changes, not the arrival date's total. `test_new_version_corrects_prior_event_day` covers this behavior. Full views recompute locally; a cloud implementation must explicitly repair affected partitions.

## 5. Dashboard write failure

A failed atomic replace leaves the old published file. The database may already contain the new batch. Restore disk capacity/permissions and rerun: unchanged batches are skipped, the JSON is regenerated, then atomically replaced. `test_failed_atomic_replace_preserves_dashboard` covers the preservation behavior.

## 6. Full rebuild / disaster recovery

```bash
python3 src/pipeline.py --db data/rebuilt.sqlite --output dashboard/rebuilt.json
```

Compare canonical trip counts, fare total and quality checks with the expected snapshot. Operational correction/duplicate counters may differ if batches are deliberately replayed out of order, but the final fact state must agree. This repository retains raw versions, not managed backups; backup retention and access controls belong in the production extension.
