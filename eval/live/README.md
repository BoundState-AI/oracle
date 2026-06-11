# Live-Fire Evaluation (Release Gate)

Runs seeded-defect and known-sound cases against **real vendors** and scores:

- **Detection** — every planted defect must be *raised* by at least one reviewer
  (`detection_raised`), and separately scored on whether it *survived synthesis*
  (`detection_surfaced`). A raised-but-lost defect is a dissent-fidelity failure,
  not a detection failure.
- **False positives** — the known-sound spec has a critical/high budget; inventing
  defects fails the gate.
- **Retention / drift** — per-oracle round-1→round-2 finding retention plus
  `oracle.drift` events. This is the live measurement of the anchoring/sycophancy
  findings the static audit could only assert structurally.

## Running

```bash
# All cases (~$5–15 at 2 rounds, nondeterministic):
python -m eval.live.run_live_eval

# One case, custom output dir:
python -m eval.live.run_live_eval --case seeded_payment_spec --output-dir eval_runs/pre-release
```

Requires all four vendor keys; refuses to run otherwise. Exit 0 = all gates
passed. **Never runs in CI** — it gates releases, not commits.

## Adding a case

1. `cases/<name>.md` — the document (note planted defects in the title).
2. `cases/<name>.expected.json` — `expected_defects` with distinctive
   `required_keywords` (ALL must appear in a finding's text) and a
   `min_severity` floor; or `max_false_critical_high` for sound specs.

Keep keywords distinctive, not exhaustive — a generously graded eval is a
lie about quality.
