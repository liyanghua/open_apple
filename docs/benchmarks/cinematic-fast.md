# Cinematic Fastline Benchmark

This runbook turns measured `cinematic-fast` runs into a publishable SLA decision. The metrics tool is read-only: it aggregates existing run records and writes a JSON report. It never starts a render, pipeline, provider call, or paid generation.

## Required Sample Set

Use the normal `cinematic-fast` workflow to produce independent benchmark records:

- 3 cold runs with new reference and source media
- 5 warm runs for the same brand/profile with reusable caches available
- At least 3 audio-only revisions that keep the certified video master unchanged

Each full cold or warm run is normalized to two 10-minute gates. The reported benchmark wall time is therefore `active_seconds + 1200`. Audio-only revisions use zero normalized gates. Actual approval delay is retained separately as `observed_human_wait_seconds` and never changes the normalized SLA comparison.

Store each run at:

```text
projects/<project-id>/analysis/benchmark_runs/<run-id>.json
```

Minimum record shape:

```json
{
  "run_id": "cold-001",
  "run_type": "cold",
  "environment_fingerprint": "sha256 from the environment probe",
  "events": [],
  "checkpoints": []
}
```

`run_type` is `cold`, `warm`, or `audio_only`. `events` are snapshots from the run's append-only `events.jsonl`. `checkpoints` must include every `awaiting_human` and corresponding `completed` gate state from that run. Do not combine multiple executions into one record.

## Environment Controls

Keep the machine plugged in and record runs without another CPU-heavy render in parallel. Every report captures CPU model, core count, RAM, macOS/OS version, Node, Remotion, Chromium, FFmpeg, source count, source bytes, source duration, operation timing, and cache hit rate. A changed environment fingerprint starts a new benchmark cohort; do not pool it with the old cohort for an SLA claim.

Use `SOURCE_DIR` when source media lives outside the project workspace:

```bash
make benchmark-fastline \
  PROJECT_ID=transparent-table-mat-remix-01 \
  SOURCE_DIR=projects/viral-remix-01/inputs/source
```

Without benchmark run files, the target may summarize the project's current event history as an `observed` run. Observed runs do not count toward any SLA sample floor.

## Pass Rules

- Cold: median <= 4 hours and every run <= 5 hours
- Warm: median <= 75 minutes and every run <= 90 minutes
- Audio-only: median <= 10 minutes and every run <= 15 minutes

Each workflow is gated independently. It is publishable only when both its minimum sample count and both timing thresholds pass. If samples are insufficient or a threshold fails, the benchmark report remains valid, but that workflow must not be displayed as an SLA. Product surfaces should show measured rolling ETA and `estimate_confidence` instead.

Operation ETA uses the rolling median of the last five matching executions. Fewer than three observations must remain `estimate_confidence: low`; three or more may be `high`.

## Report Location

The aggregation target writes:

```text
projects/<project-id>/analysis/benchmarks/<UTC-timestamp>.json
```

Archive the report with the environment fingerprint and source inventory. Never edit a report to force an SLA pass; add new benchmark runs and aggregate again.
