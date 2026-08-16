# Sample TTS CLI Design

**Date:** 2026-08-16
**Status:** Approved for implementation
**Scope:** A dedicated OpenMontage command for producing one governed TTS sample for an Operator-managed `cinematic-fast` project from either a user terminal or an internal pipeline agent.

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
- Be safely resumable after cache misses, network failures, provider errors, or process interruption without risking a duplicate paid call.
- Support machine-readable output and stable exit codes.

## Non-Goals

- Rendering the video sample, generating background music, or producing subtitles.
- Approving the creative lock or the final sample gate.
- Selecting a different concept, runtime, composition mode, script, or CTA.
- Replacing provider tools or bypassing `tts_selector`.
- Adding a TTS provider-specific CLI for every provider.
- Making Backlot a required runtime dependency for command execution.
- Supporting unmanaged projects, other pipelines, or arbitrary standalone TTS in v1.

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

The default is a no-provider-call plan. A cache hit may be reported, but it is not materialized unless explicitly requested. In an interactive terminal, a live provider call requires both flags and an exact-provider confirmation prompt:

```bash
openmontage sample-tts \
  --project-id table-mat-mix-v4 \
  --sample \
  --live \
  --approve-paid
```

### Required arguments

- `--project-id ID`: Operator-managed `cinematic-fast` project directory name under the configured projects root.
- Exactly one text source:
  - `--sample`: use the approved script's `voice_performance.sample_section_id`, expanding to adjacent sections only when needed to meet the duration target.
  - `--section ID`: use one approved script section as the anchor and expand to a valid contiguous sample range.
  - `--text TEXT`: use explicit text that matches a contiguous approved 10-15 second range covered by the production lock.

### Selection arguments

- `--provider NAME`: preferred provider; defaults to `auto` ranking.
- `--allowed-provider NAME`: repeatable allowlist.
- `--voice-id ID`: provider-specific voice override.
- `--model ID`: provider model/resource override.
- `--speech-rate VALUE`: provider-supported rate override.
- `--target-seconds N`: desired sample range, default 12 and constrained to 10-15 for pipeline sample mode.

The v1 production-lock interpretation is explicit: `locked_values.tts` must be an object; an empty object means provider, model, voice, and rate are delegated to post-lock sample selection; a present non-empty key is locked to its exact value. Missing/non-object `tts`, `null`, wildcard strings, and empty values inside a non-empty object are invalid. Provider, voice, model, text, or rate values that differ from a locked value are rejected. The CLI never silently revises the lock.

The only allowed TTS lock keys are `provider` (non-empty string), `model`
(non-empty string), `voice_id` (non-empty string), and `speech_rate` (finite
number from 0.25 through 4.0). Provider aliases, `tool`, `resource_id`, `voice`,
`rate`, and string numbers are invalid rather than implicitly converted. The
selector may map `model` and `speech_rate` to provider-specific request fields,
but the lock is always compared in this canonical form.

### Execution arguments

- `--live`: permit a provider call after cache preparation.
- `--approve-paid`: record caller intent to authorize a positive estimated cost. It has no effect without `--live`; authorization is complete only after the exact immutable plan is acknowledged.
- `--materialize`: permit cache-hit output materialization without a provider call.
- `--actor ID`: audit actor, defaulting to the current local username for terminal use and required when the service is called by an agent.
- `--approval-reason TEXT`: required for every paid live execution, interactive or non-interactive, and persisted as authorization provenance.
- `--approved-plan-hash HASH`: required for non-interactive paid live execution. It must equal the plan-only result's immutable plan hash; a changed provider/model/request/estimate invalidates it.
- `--projects-dir PATH`: override the repository `projects/` directory.
- `--json`: print one final JSON result to stdout and treat execution as non-interactive even when stdin is a TTY. A paid live JSON invocation therefore requires caller-supplied authorization bound to the disclosed plan hash through the service API; the CLI form first runs a plan-only invocation so the caller can obtain that hash.

Reconciliation is a separate command and never runs implicitly:

```bash
openmontage sample-tts reconcile \
  --project-id table-mat-mix-v4 \
  --operation-key <key> \
  --outcome not-called|failed|succeeded \
  --actual-cost-usd <amount> \
  [--staged-audio <path> --staged-metadata <path>]
```

`succeeded` requires validated retained staging files whose real paths are
inside the exact operation-key staging directory, are regular non-symlink files,
and whose SHA-256 values and normalized metadata match the durable
`provider_succeeded` receipt. `not-called` refunds an active reservation.
`failed` reconciles the supplied actual cost. Every reconciliation requires
`--actor` and `--reason`, is recorded in the operation attempt history, and uses
an Operator transaction.

### Exit codes

- `0`: plan completed, cache materialized, or provider generation succeeded.
- `2`: invalid arguments, incompatible project, or malformed locked artifacts.
- `3`: creative lock missing/unapproved, paid authorization missing, or requested override conflicts with the lock.
- `4`: provider, network, cache materialization, media validation, or output persistence failure.
- `5`: Operator transaction or checkpoint persistence failure after a media operation.

Expected validation, authorization, provider, and persistence failures raise a typed `SampleTTSError` carrying `code`, `message`, `exit_code`, and a sanitized partial result. `SampleTTSService.run()` returns `SampleTTSResult` only for `planned`, `cache_hit`, `materialized`, or `generated`. The CLI catches typed errors and maps their declared exit code; unexpected exceptions are redacted and map to 5.

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
    project_id: str
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
    actor: str
    approval_reason: str | None

@dataclass(frozen=True)
class PaidAuthorization:
    actor: str
    source: Literal["terminal", "agent"]
    reason: str
    approved_at: str
    provider: str
    selected_tool: str
    model: str
    operation_key: str
    plan_hash: str
    maximum_cost_usd: float

@dataclass(frozen=True)
class DecisionAcknowledgment:
    plan_hash: str
    acknowledged_by: str
    acknowledged_at: str

@dataclass(frozen=True)
class SampleTTSResult:
    status: Literal["planned", "cache_hit", "materialized", "generated"]
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

class SampleTTSError(Exception):
    code: str
    exit_code: int
    partial: SampleTTSResult | None
```

The public service signature is:

```python
run(
    request: SampleTTSRequest,
    *,
    authorization: PaidAuthorization | None = None,
    on_decision: Callable[[ImmutablePaidPlan], DecisionAcknowledgment] | None = None,
) -> SampleTTSResult
```

For a paid live call, `on_decision` is mandatory and must return an acknowledgment whose plan hash and actor match the scoped authorization. The immutable plan hash covers provider, selected tool, effective model/resource, voice, canonical request hash, operation key, mode, and estimated cost. Any mismatch exits 3 before reservation/provider execution. Interactive CLI mode builds the authorization and acknowledgment only after displaying the plan and collecting exact provider plus reason; JSON mode cannot prompt and must receive a previously constructed authorization/acknowledgment through the Python service caller.

`run()` is the only public generation orchestration method. Provider-specific behavior remains in existing tools. The service is scoped to `cinematic-fast` projects with an Operator marker in v1; a future generic command can add a separate compatibility predicate without weakening this contract.

### Existing components reused

- `tools.tool_registry.registry` for tool discovery.
- `tools.audio.tts_selector.TTSSelector` for rank/prepare/materialize/generate.
- `tools.cost_tracker.CostTracker` for estimate, approval, reserve, reconcile, and refund.
- `backlot.project_commit.ProjectCommitStore` for Operator-managed atomic writes.
- `lib.checkpoint.write_checkpoint` for sample progress.
- Existing artifact hashing, schema validation, cache validators, and audio probing.

### New shared support

- `SampleTTSOperationStore` persists one canonical operation record keyed by the exact request hash. It records `planned`, `reserved`, `provider_call_started`, `provider_succeeded`, `committed`, `failed`, or `reconciliation_required`, plus reservation id, provider-called state, staging paths, and commit generation.
- A provider-argument adapter in `tts_selector` normalizes the generic request into provider-specific fields (`resource_id/model`, `voice/voice_id`, `speed/speaking_rate/speech_rate`) and returns the effective request in `prepare` and `generate` results.
- `CostTracker` gains transaction-aware, operation-key-aware idempotent estimate/reserve/reconcile methods. For an Operator-managed project, every mutation receives the active project sink and stages `cost_log.json` in the same generation as the operation record; direct mutation without a sink is rejected. The `ProjectCommitStore` lock therefore serializes concurrent CLI/agent ledger changes. Existing unmanaged callers retain the current atomic-file path.

## Managed Project Preconditions

For every request, the service must:

1. Resolve the project path below `projects_dir` without accepting traversal or an arbitrary absolute project id.
2. Load `project.json`, require `pipeline_type=cinematic-fast`, and require the Operator-managed marker.
3. Load `checkpoint_assets.json` and require `status=completed`, `human_approved=true`, and a non-empty `approval_bundle_id`/`approval_bundle_version`.
4. Resolve the latest state for that bundle id, require the referenced version and latest status to be `approved`, call `inspect_bundle_reconciliation(project_dir, checkpoint_assets)`, require action `unchanged`, and verify every approval-bundle artifact reference hash against the current canonical artifact.
5. Load the production lock and approved script using artifact references, not untrusted paths.
6. Verify requested text, provider constraints, voice/model/rate overrides, and sample duration against the lock.
7. Inspect `checkpoint_sample.json`. Missing or `in_progress` may proceed. `awaiting_human` or an approved/completed sample is immutable here and exits 3; reopening it must use the existing change-impact/review workflow.

The command never approves a gate. A project awaiting creative approval exits with code 3.

## Text Resolution

The resolver validates unique non-empty section ids, finite monotonic half-open timings, contiguous section order, and non-empty text before selecting anything. The provider text for a section is `delivery_cues.provider_text` when it is a non-empty string; otherwise it is the section `text`. Joining uses one ASCII space only when adjacent strings do not already end/start with Chinese or Western punctuation; no Unicode normalization beyond NFC is applied. The exact resolved string and its SHA-256 are part of the canonical request.

`--sample` uses the approved script's `voice_performance.sample_section_id`. It evaluates every contiguous section range containing that section and chooses the range whose approved timing is within 10-15 seconds and closest to `target_seconds`, breaking ties by earliest start. If no whole-section range fits, it exits 2 with `sample_window_unresolvable`; it does not truncate approved text or exceed the invariant.

`--section` uses the named section as the anchor and applies the same whole-section range search as `--sample`. An unresolvable anchor exits 2.

`--text` is accepted only when its NFC-normalized value exactly equals the resolver output for a contiguous approved section range whose timing is 10-15 seconds under the joining rule above. It cannot introduce alternate punctuation or use section `text` when a locked `provider_text` exists.

The resolved report records section ids, text hash, script semantic hash, and the intended sample window.

## Execution Flow

1. Validate request and managed project preconditions.
2. Resolve approved text and output paths.
3. Discover the registry and call `tts_selector` with `operation=rank`.
4. Filter candidates to available providers whose cache artifact contract supplies required audio plus required timestamp metadata. Resolve the selected provider using the explicit preference/allowlist or the top compatible ranking. V1 therefore supports Doubao and any later provider that satisfies the same declared contract; an incompatible provider exits 2.
5. Adapt generic provider arguments, call `operation=prepare` with an allowlist containing only the selected provider, and require `selected_tool`, `provider`, `effective_request`, `cache_enabled`, `cache_status`, `cache_key`, and estimate in the result. Reject any provider mismatch before materialization or generation.
6. Compute the operation key from the approved lock/script hashes plus the selector's canonical request hash. Under an Operator transaction, create or inspect the operation record and merge an `in_progress` heartbeat into a missing/existing in-progress sample checkpoint without dropping existing artifacts or metadata.
7. If cache hit:
   - with `--materialize`, call `operation=materialize`, validate the audio, and persist success;
   - otherwise return `cache_hit` without writing output.
8. If cache miss and `--live` is false, return `planned` with the selected provider and estimate.
9. If estimated cost is positive and authorization is absent, incomplete, or not scoped to this provider/request hash, persist a blocked progress update and exit 3 before reservation or provider execution.
10. Use the operation-key-aware `CostTracker` API to create or adopt one active reservation attempt. Commit the reservation id, authorization provenance, and `provider_call_started` state before the external call.
11. Generate/materialize into a retained, content-addressed staging directory under `OPENMONTAGE_STAGING_DIR` (default outside `projects/<id>`) and use an external shared cache root (`OPENMONTAGE_CACHE_DIR`, also rejected when inside or symlinked into the managed project). Do not pass a canonical project path to the selector, so BaseTool instrumentation cannot write unversioned project events.
12. Require the selector result envelope on success and failure to preserve `selected_tool`, `provider`, `effective_request`, `provider_called`, `cache_status`, `cache_key`, estimated cost, actual cost, and any produced artifact paths. The selector must retain provider cost/state even when cache storage fails.
13. Reconcile actual cost on success. If `provider_called=false`, refund the reservation. If `provider_called=true`, reconcile the returned actual cost even when the result failed. An ambiguous interruption after `provider_call_started` is marked `reconciliation_required` and is never retried automatically.
14. Validate staged output existence, nonzero size, decodability, duration, required timestamp metadata, and provider metadata.
15. Before the final media commit, write a durable `provider_succeeded` receipt transaction containing the attempt result, hashes, sanitized metadata, staging paths, and reconciled cost. This receipt is the recovery boundary after a successful provider response.
16. In the next Operator transaction, stage the validated audio/metadata bytes, report, operation record, merged sample checkpoint, and semantic activity event. Record the committed generation id in the operation record. The operation record's attempt list supports a new paid attempt only after a previous attempt is terminal and the caller supplies a new authorization; it never creates a second active reservation for the same request.
17. Return the typed result.

## Files And Artifacts

Managed output paths are deterministic and content-address aware:

```text
projects/<id>/
  assets/audio/sample-narration-<operation-key-prefix>.<provider-format>
  assets/audio/sample-narration-<operation-key-prefix>.metadata.json
  artifacts/sample_tts_report.json
  checkpoint_sample.json
  cost_log.json
  events.jsonl
  operator/operations/sample-tts/<operation-key>.json
```

The normalized provider metadata written beside the audio is a
`sample_tts_metadata` document. It contains `schema_version`, `provider`,
`tool`, `model`, `voice_id`, `duration_seconds`, `sample_rate_hz`, `channels`,
`audio_sha256`, and a `timestamps` array. Each timestamp has `kind` (`word`,
`phoneme`, or `character`), `text`, `start_seconds`, and `end_seconds`; ranges
are finite, monotonic, half-open, and contained by the probed duration. A
provider is cache-compatible only when its result can be normalized to this
shape. Raw provider metadata is never copied to the cache or project.

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

The operation record validates against a dedicated Backlot schema. It contains no credentials or signed URLs and is the authoritative recovery state for one canonical request. Project output filenames are content-addressed so a changed approved request cannot overwrite earlier valid media.

### Operation Record Contract

`sample_tts_operation.schema.json` requires `schema_version`, `operation_key`,
`project_id`, `request_hash`, `plan_hash`, `status`, `created_at`, `updated_at`,
the approved lock/script hashes, the selected provider/tool/model, the exact
estimated cost, and a non-empty `attempts` array once reservation begins. Each
attempt has a stable `attempt_id`, status, actor, authorization provenance,
reservation id when applicable, provider-called tri-state (`true`, `false`, or
`unknown`), estimated/actual cost, staging evidence, sanitized error, and
timestamps. Status transitions are monotonic except that `failed` may begin a
new attempt only with a new authorization. `reconciliation_required` may move
only through the explicit reconcile command.

All timestamps in reports, operations, events, and checkpoints use RFC 3339 UTC
with an explicit `Z` suffix. Provider metadata is allowlisted before persistence:
provider request ids, model/resource, voice id, duration, codec, sample rate,
channel count, and word/phoneme timestamps are allowed. Credentials, headers,
cookies, signed URLs, request bodies, environment values, and raw exceptions are
discarded. Unknown provider metadata keys are not persisted.

### Approval Bundle Validation

The service loads `pipeline_defs/cinematic-fast.yaml` and requires the checkpoint
bundle to have `group=creative_lock`, `terminal_stage=assets`, and members exactly
equal to the manifest group members. Every manifest `required_artifacts` entry
must occur exactly once in `artifact_refs`; duplicate names or paths are invalid.
Each reference path must resolve beneath the project, name the current canonical
artifact, and match both its artifact and semantic hashes. The checkpoint's
bundle id/version must identify the latest approved state; an awaiting, rejected,
superseded, older, or structurally incomplete bundle fails closed.

## Transactions And Failure Recovery

Media provider calls cannot be part of a filesystem transaction. The service uses three explicit phases:

1. **Start transaction:** merge `checkpoint_sample` progress and persist the operation plan/reservation state.
2. **External operation:** generate/materialize into a temporary staging directory and an external shared cache. No media or tool event is written directly under the managed project.
3. **Completion transaction:** use `stage_bytes`, `stage_json`, and `append_event` to commit media, metadata, report, operation state, and the merged checkpoint atomically.

If phase 2 fails, a failure transaction records a sanitized blocker and leaves `sample` in progress. If phase 3 fails after valid staged media exists, the provider/cache result and cost are recorded as far as the operation record permits. Rerunning first consults the operation record and external cache. `committed` is returned idempotently after validating current project output. `provider_succeeded` may be recommitted from validated cache/staging evidence without another provider call. `provider_call_started` without a terminal provider result becomes `reconciliation_required`; it cannot be adopted or retried automatically because the provider may already have charged the request.

The default staging root is `${TMPDIR}/openmontage-staging`, never the repository
or project tree. The service creates `sample-tts/<project-id>/<operation-key>/`
with mode `0700`, rejects symlinked roots or any resolved component that enters
the project, and opens retained files without following symlinks. Validated
`provider_succeeded` evidence is retained for seven days after commit; unresolved
or reconciliation-required evidence is retained for 30 days. Cleanup is an
explicit best-effort pass at command start: it removes only terminal operation
directories older than their policy, never follows symlinks, and never removes
unknown files or active/unresolved operations.

`CostTracker` owns `cost_log.json` and serializes its own sidecar lock. The
operation key guarantees at most one ledger entry/reservation per exact request.
Operator transactions record reservation references and cost snapshots in the
operation record; they do not stage or rewrite `cost_log.json`. A failed cost
mutation therefore fails before the external provider call, while a failed
Operator commit after reconciliation is recovered from the operation receipt.

Semantic activity uses `sink.append_event("events", event)`. The default Operator
outbox materializer appends those events to the canonical `events.jsonl` after
commit; the service never writes that file directly. Preconditions that fail
before a transaction emit a sanitized structured stderr/JSON result only. Once
the project is validated as Operator-managed, authorization blocks and all later
failures also append a `sample_tts_blocked` or `sample_tts_failed` event and merge
the same code into `checkpoint_sample.metadata.partial_progress`.

Checkpoint merge rules are narrow: only a missing or `in_progress` sample checkpoint can be written. Existing artifacts, progress keys, cost data, and approval bookkeeping are preserved unless this operation owns the exact key being updated. `awaiting_human`, `completed`, or human-approved sample checkpoints are never replaced or reopened by this command.

## Security And Governance

- Never print or persist API keys, authorization headers, signed provider URLs, or raw exception objects containing secrets.
- Use provider `_safe_error()` output where available and apply final redaction in the service.
- Resolve project and artifact paths beneath their configured roots.
- Require explicit `--live --approve-paid` for a paid cache miss.
- Announce the exact tool, provider, model/resource, estimate, and sample mode before a live call in human output.
- Human CLI mode prints the pre-call plan to stderr and requires the exact-provider confirmation before execution. Stdout remains the final result.
- `--json` writes exactly one final JSON document to stdout; pre-call decision data is emitted as a structured JSON event on stderr. `SampleTTSService.run()` requires an `on_decision(plan)` callback for live calls. Agent callers must surface that callback before allowing it to return; this is an explicit caller contract and is tested with a blocking acknowledgment callback.
- Terminal authorization provenance is the interactive confirmation plus actor/reason. Agent authorization provenance is the typed `PaidAuthorization` supplied by the trusted orchestration caller. OpenMontage records this provenance but does not claim to authenticate an external agent identity.
- Do not silently fall back or switch provider after rank/prepare. A selected provider failure is returned as a blocker.
- Do not modify creative decisions, approval bundles, or `production_lock`.

## Agent Integration

Stage directors and agents use `SampleTTSService` directly when running inside the Python process and must provide a blocking decision callback plus authorization provenance. Shell-based agents may invoke:

```bash
openmontage sample-tts --project-id <id> --sample --json --live --approve-paid --actor codex-agent --approval-reason "user approved exact provider and estimate"
```

The cinematic-fast sample director is updated to reference this command/service instead of manually composing selector and cost tracker calls. Other pipelines are rejected in v1.

## Repository Changes

### Add

- `openmontage/__init__.py`
- `openmontage/__main__.py`
- `openmontage/cli.py`
- `openmontage/sample_tts.py`
- `openmontage/sample_tts_operation.py`
- `schemas/artifacts/sample_tts_report.schema.json`
- `schemas/backlot/sample_tts_operation.schema.json`
- `tests/cli/test_sample_tts_cli.py`
- `tests/openmontage/test_sample_tts_service.py`
- `tests/openmontage/test_sample_tts_recovery.py`
- `tests/tools/test_cost_tracker_concurrency.py`
- `tests/tools/test_tts_selector_sample_contract.py`
- `docs/sample-tts.md`

### Modify

- `setup.py`: add the `openmontage` console entry point.
- `lib/checkpoint.py`: register `sample_tts_report` as a recognized supporting artifact.
- `schemas/artifacts/__init__.py` or the current schema registry: register the new schema.
- `skills/pipelines/cinematic-fast/sample-director.md`: route TTS sample work through the shared service/CLI.
- `Makefile`: add an optional `sample-tts` convenience target and help text without embedding orchestration.
- `docs/PROVIDERS.md`: link provider configuration to the command.
- `tools/audio/tts_selector.py`: required provider-argument normalization, strict selected-provider verification, compatible-provider filtering, effective-request reporting, and a consistent success/failure envelope that preserves provider-called and cost state. Provider routing remains in the selector.
- `tools/cost_tracker.py`: required cross-process sidecar lock, atomic writes, operation keys, and idempotent reservation/reconciliation helpers. Existing budget semantics remain authoritative.
- `lib/events.py` or selector invocation conventions: ensure service staging calls do not directly attribute tool events to an Operator-managed project; semantic events are appended through the transaction sink.

No Backlot server change is required. Existing board state already reads `checkpoint_sample.metadata.partial_progress`; the service supplies useful progress fields through that contract.

## Testing

### CLI tests

- Both entry forms parse the same command contract.
- Dry-run never calls a provider.
- `--live` without `--approve-paid` exits 3 on a positive estimate.
- Interactive live mode requires the exact provider confirmation.
- Non-interactive live mode requires actor and approval reason.
- `--json` emits one valid stdout JSON document; structured pre-call events use stderr.
- Exit codes distinguish validation, approval, provider, and persistence failures.

### Service tests

- Creative lock must be completed and human-approved.
- Non-cinematic-fast and non-Operator projects are rejected.
- Bundle id/version/status, reconciliation state, artifact refs, and production-lock hashes fail closed before selector generation.
- Empty `locked_values.tts` is open; non-empty values are exact locks; missing, null, wildcard, and partial-empty forms fail validation.
- `--sample`, `--section`, and managed `--text` resolve only approved text.
- Provider-text precedence, punctuation joining, NFC handling, duplicate ids, invalid timing, and unresolvable 10-15 second windows are deterministic.
- Explicit provider/voice/model changes conflicting with the lock fail.
- Generic model/voice/rate arguments map to each supported provider's effective request or fail; ignored overrides are forbidden.
- Rank and prepare always precede materialize/generate.
- Explicit/locked provider unavailable never falls back, and prepare/provider mismatch is rejected.
- Providers without required audio/timestamp metadata contracts are rejected in v1.
- Cache hit materializes with zero provider calls and zero cost.
- Cache-disabled providers report a supported planning error rather than pretending to offer resumability.
- Cache miss dry-run returns a plan.
- Paid generation creates an exact reservation and reconciles success.
- Provider-not-called failure refunds; provider-called failure reconciles returned actual cost.
- Selector cache-store failure retains provider-called and actual-cost evidence.
- A selected provider failure never invokes a fallback.
- Output validation rejects empty or undecodable audio.
- Concurrent CLI/agent runs produce one operation and one ledger reservation.
- Interruptions before reserve, after reserve, before provider call, during an ambiguous provider call, after provider success, and during Operator commit have explicit recovery tests.
- Ambiguous `provider_call_started` state requires reconciliation and never duplicates spend.
- Successful rerun adopts a committed output or validated cache without duplicate provider spend.
- Operator-managed projects write start/failure/completion through `ProjectCommitStore`.
- Missing/in-progress checkpoints merge without data loss; awaiting-human/completed checkpoints are immutable.
- Start-transaction, cost-ledger, provider, validation, and completion-transaction errors map to stable typed errors/exit codes.

### Integration tests

- Fake paid Doubao provider: approved cinematic-fast project through report/checkpoint update.
- Fake network failure: sample remains resumable and cost is released/reconciled correctly.
- Fake provider without metadata/cache support is rejected before any call.
- Two concurrent fake paid invocations verify operation/ledger serialization.
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
