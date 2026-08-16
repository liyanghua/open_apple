# Sample TTS CLI Design

**Date:** 2026-08-16
**Status:** Approved for specification
**Scope:** A dedicated OpenMontage command for producing one governed TTS sample from both a user terminal and an internal pipeline agent.

## Problem

The cinematic fastline currently requires an agent to assemble several low-level operations to create a TTS sample: validate the creative lock, select a provider, check the cache, reserve cost, call the provider, reconcile spend, write outputs, and update the Operator-managed sample checkpoint. This orchestration is error-prone and cannot be invoked directly by a user when an agent runtime cannot obtain network execution approval.

OpenMontage needs one command and one shared service that perform the same governed workflow regardless of whether the caller is a user terminal or an agent.

## Goals

- Provide `openmontage sample-tts` and `python -m openmontage sample-tts`.
- Keep terminal and agent execution behavior identical by routing both through one service.
- Require a completed creative lock before provider execution for a managed production project.
- Use `tts_selector` for provider ranking, cache preparation, materialization, and generation.
- Preserve paid-call governance with an explicit live/paid authorization, cost reservation, and reconciliation.
- Write audio, provider metadata, a structured report, Operator activity, and sample checkpoint progress to the project workspace.
- Be safely resumable after cache misses, network failures, provider errors, or process interruption.
- Support machine-readable output and stable exit codes.

## Non-Goals

- Rendering the video sample, generating background music, or producing subtitles.
- Approving the creative lock or the final sample gate.
- Selecting a different concept, runtime, composition mode, script, or CTA.
- Replacing provider tools or bypassing `tts_selector`.
- Adding a TTS provider-specific CLI for every provider.
- Making Backlot a required runtime dependency for command execution.

## Approaches Considered

### Shared service with a thin CLI (selected)

Add a small `openmontage` command package and a reusable `SampleTTSService`. The CLI parses arguments and formats results; the service owns validation, selection, cache, cost, generation, persistence, and checkpoint behavior. Agents may call the service directly or invoke the CLI with `--json`.

This creates one behavior contract and keeps command presentation separate from production logic.

### CLI-only orchestration

Put all orchestration in the command function. This needs fewer files initially but makes internal agent use depend on subprocess parsing and encourages duplicate orchestration elsewhere. Rejected because cost and checkpoint governance would not have a reusable boundary.

### Backlot subcommand

Add sample generation under `python -m backlot`. This would couple a media generation operation to the observer/operator application and make a standalone terminal workflow depend on Backlot concepts. Rejected because Backlot must remain optional for production execution.

## Public Command Contract

Both invocation forms are supported:

```bash
openmontage sample-tts --project-id table-mat-mix-v4 --sample
python -m openmontage sample-tts --project-id table-mat-mix-v4 --sample
```

The default is a no-provider-call plan. A cache hit may be reported, but it is not materialized unless explicitly requested. A live provider call requires both flags:

```bash
openmontage sample-tts \
  --project-id table-mat-mix-v4 \
  --sample \
  --live \
  --approve-paid
```

### Required arguments

- `--project-id ID`: project directory name under the configured projects root.
- Exactly one text source:
  - `--sample`: use the approved script's `voice_performance.sample_section_id`, expanding to adjacent sections only when needed to meet the duration target.
  - `--section ID`: use one approved script section.
  - `--text TEXT`: use explicit text. For an Operator-managed production this must match text already covered by the approved production lock unless `--standalone` is used.

### Selection arguments

- `--provider NAME`: preferred provider; defaults to `auto` ranking.
- `--allowed-provider NAME`: repeatable allowlist.
- `--voice-id ID`: provider-specific voice override.
- `--model ID`: provider model/resource override.
- `--speech-rate VALUE`: provider-supported rate override.
- `--target-seconds N`: desired sample range, default 12 and constrained to 10-15 for pipeline sample mode.

Provider, voice, model, text, or rate values that differ from the production lock are rejected for managed projects unless the lock explicitly leaves that field open. The CLI never silently revises the lock.

### Execution arguments

- `--live`: permit a provider call after cache preparation.
- `--approve-paid`: record caller authorization for a positive estimated cost. It has no effect without `--live`.
- `--materialize`: permit cache-hit output materialization without a provider call.
- `--actor ID`: audit actor, defaulting to the current local username for terminal use and required when the service is called by an agent.
- `--projects-dir PATH`: override the repository `projects/` directory.
- `--standalone`: allow TTS generation without a managed project or creative lock. Standalone output does not mutate checkpoints or approval state.
- `--json`: print one JSON result and suppress human presentation text.

### Exit codes

- `0`: plan completed, cache materialized, or provider generation succeeded.
- `2`: invalid arguments, invalid project, or malformed locked artifacts.
- `3`: creative lock missing/unapproved, paid authorization missing, or requested override conflicts with the lock.
- `4`: provider, network, cache materialization, media validation, or output persistence failure.
- `5`: Operator transaction or checkpoint persistence failure after a media operation.

## Architecture

### `openmontage.cli`

Responsibilities:

- Build the top-level argument parser and `sample-tts` subparser.
- Convert CLI arguments into a typed request.
- Call `SampleTTSService.run()`.
- Render human-readable progress/results or one JSON object.
- Map typed service errors to stable exit codes.

It does not import provider implementations, write project files, or implement cost logic.

### `openmontage.sample_tts`

The shared service defines:

```python
@dataclass(frozen=True)
class SampleTTSRequest:
    project_id: str | None
    projects_dir: Path
    text_mode: Literal["sample", "section", "text"]
    text_value: str | None
    target_seconds: float
    preferred_provider: str
    allowed_providers: tuple[str, ...]
    voice_id: str | None
    model: str | None
    speech_rate: float | None
    live: bool
    approve_paid: bool
    materialize: bool
    standalone: bool
    actor: str

@dataclass(frozen=True)
class SampleTTSResult:
    status: Literal["planned", "cache_hit", "materialized", "generated", "failed"]
    provider: str | None
    tool: str | None
    model: str | None
    voice_id: str | None
    cache_key: str | None
    cache_status: str
    estimated_cost_usd: float
    actual_cost_usd: float
    audio_path: str | None
    metadata_path: str | None
    report_path: str | None
    duration_seconds: float | None
    error_code: str | None
    error: str | None
```

`run()` is the only public orchestration method. Provider-specific behavior remains in existing tools.

### Existing components reused

- `tools.tool_registry.registry` for tool discovery.
- `tools.audio.tts_selector.TTSSelector` for rank/prepare/materialize/generate.
- `tools.cost_tracker.CostTracker` for estimate, approval, reserve, reconcile, and refund.
- `backlot.project_commit.ProjectCommitStore` for Operator-managed atomic writes.
- `lib.checkpoint.write_checkpoint` for sample progress.
- Existing artifact hashing, schema validation, cache validators, and audio probing.

## Managed Project Preconditions

For a non-standalone request, the service must:

1. Resolve the project path below `projects_dir` without accepting traversal or an arbitrary absolute project id.
2. Load `project.json` and require a known pipeline.
3. Load `checkpoint_assets.json` and require `status=completed` and `human_approved=true` when the pipeline has the creative lock gate.
4. Resolve the latest approved creative approval bundle and verify its subject version/hash still match the checkpoint inputs.
5. Load the production lock and approved script using artifact references, not untrusted paths.
6. Verify requested text, provider constraints, voice/model/rate overrides, and sample duration against the lock.
7. Load or create `checkpoint_sample.json` as `in_progress` through an Operator transaction.

The command never approves a gate. A project awaiting creative approval exits with code 3.

## Text Resolution

`--sample` uses the approved script's `voice_performance.sample_section_id`. If that section is shorter than 10 seconds, the resolver adds contiguous approved sections, preferring forward sections, until the selected half-open time range is between 10 and 15 seconds. It never truncates a sentence merely to meet the target.

`--section` selects exactly one approved section and may be outside 10-15 seconds; the result includes a duration warning.

`--text` in managed mode is accepted only when its normalized text equals one or more contiguous approved script sections. `--standalone --text` accepts arbitrary text and bypasses project mutation, not provider cost governance.

The resolved report records section ids, text hash, script semantic hash, and the intended sample window.

## Execution Flow

1. Validate request and managed project preconditions.
2. Resolve approved text and output paths.
3. Discover the registry and call `tts_selector` with `operation=rank`.
4. Resolve the selected provider using the explicit preference/allowlist or the top available ranking.
5. Call `operation=prepare` with the exact generation request.
6. If cache hit:
   - with `--materialize`, call `operation=materialize`, validate the audio, and persist success;
   - otherwise return `cache_hit` without writing output.
7. If cache miss and `--live` is false, return `planned` with the selected provider and estimate.
8. If estimated cost is positive and `--approve-paid` is false, persist a blocked progress update and exit 3 before provider execution.
9. Create a `CostTracker` estimate, approve the exact selected provider tool for this caller-authorized operation, and reserve the estimate.
10. Call `tts_selector` with `operation=generate`, the reservation id, and the project cost log.
11. Reconcile actual cost on success. On a provider failure, reconcile as failed with actual cost returned by the tool; if the provider was never called, refund the reservation.
12. Validate output existence, nonzero size, decodability, duration, and provider metadata.
13. Persist the report and sample checkpoint progress in one Operator generation.
14. Return the typed result.

## Files And Artifacts

Managed output paths are deterministic and content-address aware:

```text
projects/<id>/
  assets/audio/sample-narration.<provider-format>
  assets/audio/sample-narration.metadata.json
  artifacts/sample_tts_report.json
  checkpoint_sample.json
  cost_log.json
  events.jsonl
```

`sample_tts_report` is a new schema-backed supporting artifact with:

- project and producer identity;
- approved lock/script hashes;
- resolved section ids and text hash, but not duplicated secret configuration;
- provider, tool, model/resource, and voice id;
- cache key/status;
- estimated and actual cost;
- output paths, SHA-256 hashes, probe data, and duration;
- status and sanitized error details;
- timestamps and caller actor.

It is registered as an allowed checkpoint artifact but is not a new pipeline stage or a replacement for `sample_report`. The later sample stage consumes it while building `asset_manifest`, `final_props`, and `sample_report`.

## Transactions And Failure Recovery

Media provider calls cannot be part of a filesystem transaction. The service uses three explicit phases:

1. **Start transaction:** write `checkpoint_sample` with rank/prepare progress and the selected provider plan.
2. **External operation:** reserve cost and generate/materialize media to deterministic project paths.
3. **Completion transaction:** write the report, append the activity event, and update checkpoint progress with output hashes and realized cost.

If phase 2 fails, a failure transaction records a sanitized blocker and leaves `sample` in progress. If phase 3 fails after valid media exists, rerunning detects and validates the deterministic output/cache before making another provider call. A successful existing output with matching request hash is adopted; a mismatched or invalid output is quarantined by using a new content-addressed cache entry and is never treated as a hit.

Cost log writes remain under `CostTracker`. Operator transactions record references and snapshots rather than attempting to rewrite the cost log.

## Security And Governance

- Never print or persist API keys, authorization headers, signed provider URLs, or raw exception objects containing secrets.
- Use provider `_safe_error()` output where available and apply final redaction in the service.
- Resolve project and artifact paths beneath their configured roots.
- Require explicit `--live --approve-paid` for a paid cache miss.
- Announce the exact tool, provider, model/resource, estimate, and sample mode before a live call in human output.
- `--json` includes the same decision data before execution through a progress callback/event; agents must surface it to users under the existing Decision Communication Contract.
- Do not silently fall back or switch provider after rank/prepare. A selected provider failure is returned as a blocker.
- Do not modify creative decisions, approval bundles, or `production_lock`.

## Agent Integration

Stage directors and agents use `SampleTTSService` directly when running inside the Python process. Shell-based agents may invoke:

```bash
openmontage sample-tts --project-id <id> --sample --json --live --approve-paid --actor codex-agent
```

The cinematic-fast sample director is updated to reference this command/service instead of manually composing selector and cost tracker calls. The service remains optional for other pipelines; they may adopt it when their gate and script artifacts satisfy the same contract.

## Repository Changes

### Add

- `openmontage/__init__.py`
- `openmontage/__main__.py`
- `openmontage/cli.py`
- `openmontage/sample_tts.py`
- `schemas/artifacts/sample_tts_report.schema.json`
- `tests/cli/test_sample_tts_cli.py`
- `tests/openmontage/test_sample_tts_service.py`
- `docs/sample-tts.md`

### Modify

- `setup.py`: add the `openmontage` console entry point.
- `lib/checkpoint.py`: register `sample_tts_report` as a recognized supporting artifact.
- `schemas/artifacts/__init__.py` or the current schema registry: register the new schema.
- `skills/pipelines/cinematic-fast/sample-director.md`: route TTS sample work through the shared service/CLI.
- `Makefile`: add an optional `sample-tts` convenience target and help text without embedding orchestration.
- `docs/PROVIDERS.md`: link provider configuration to the command.
- `tools/audio/tts_selector.py`: only if required to expose the selected provider/model from prepare consistently or to distinguish provider-not-called failures. Provider routing remains in the selector.
- `tools/cost_tracker.py`: only if required to expose an idempotent reservation/adoption helper. Existing cost semantics remain authoritative.

No Backlot server change is required. Existing board state already reads `checkpoint_sample.metadata.partial_progress`; the service supplies useful progress fields through that contract.

## Testing

### CLI tests

- Both entry forms parse the same command contract.
- Dry-run never calls a provider.
- `--live` without `--approve-paid` exits 3 on a positive estimate.
- `--json` emits one valid JSON document with no presentation text.
- Exit codes distinguish validation, approval, provider, and persistence failures.

### Service tests

- Creative lock must be completed and human-approved.
- Stale approval bundle or production-lock hashes fail before selector generation.
- `--sample`, `--section`, and managed `--text` resolve only approved text.
- Explicit provider/voice/model changes conflicting with the lock fail.
- Rank and prepare always precede materialize/generate.
- Cache hit materializes with zero provider calls and zero cost.
- Cache miss dry-run returns a plan.
- Paid generation creates an exact reservation and reconciles success.
- Provider-not-called failure refunds; provider-called failure reconciles returned actual cost.
- A selected provider failure never invokes a fallback.
- Output validation rejects empty or undecodable audio.
- Successful rerun adopts matching output/cache without duplicate provider spend.
- Operator-managed projects write start/failure/completion through `ProjectCommitStore`.
- Standalone mode never writes project checkpoints or approvals.

### Integration tests

- Fake paid Doubao provider: approved cinematic-fast project through report/checkpoint update.
- Fake network failure: sample remains resumable and cost is released/reconciled correctly.
- Existing `tts_selector` and Doubao cache contract tests remain passing.
- Existing cinematic-fast end-to-end test consumes the report without adding another human gate.

No live provider call is part of the automated test suite.

## Acceptance Criteria

- A user and an agent can execute the same TTS sample workflow through stable public interfaces.
- A managed paid cache miss cannot reach a provider without approved creative lock and explicit live/paid flags.
- Cache hits do not call providers or reserve paid budget.
- Every managed attempt is visible as sample checkpoint progress, including sanitized failures.
- A provider failure never triggers a silent provider switch.
- Successful output is validated, hashed, reported, and reusable by the remaining sample pipeline.
- Existing pipeline, cost, Operator transaction, and TTS cache tests remain green.
