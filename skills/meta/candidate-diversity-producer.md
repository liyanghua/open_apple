# Candidate Diversity Producer

Use the ordinary workflow below for exploratory `candidate_batch` production
before paid assets or sample rendering. A single-project video keeps the normal
cinematic-fast creative lock flow. A preregistered controlled opening experiment
uses the separate routing section below; do not invent body changes merely to
satisfy the exploration rule. Diversity and the experimental variable must be
planned and approved before production, not relabeled after rendering.

## Fixed workflow

1. Call `lib.candidate_batch.create_candidate_batch(...)`. When a candidate does
   not provide a `variant_plan_ref`, the library assigns one of the five stable
   default directions: `result_first`, `problem_first`, `evidence_first`,
   `high_density`, or `product_craft`.
2. Call `lib.batch_fork.fork_candidate_projects(...)`. The fork writes
   `artifacts/candidate_variant_plan.json` with six dimensions and at least
   three structural shot differences. The write is deterministic and
   idempotent; an existing operator-authored plan is preserved.
3. Present the plans as part of the creative-lock review. The plan starts with
   `approval_status: awaiting_human`. Do not purchase, generate, or render
   candidate assets while the creative lock is awaiting approval.
4. Build and approve the normal `creative_lock` bundle. The bundle includes
   `candidate_variant_plan` and its semantic/artifact hashes. Approval of the
   bundle is the approval of the candidate's diversity strategy.
5. After approval, carry the plan into proposal, scene, asset, and sample
   execution inputs. Run `assert_candidate_variant_ready` before a paid call;
   `hard_gate` blocks failures, while `warning` records them and still requires
   the human approval step.

## Operator review

For ordinary exploration, review the six dimension values, the three structural
shot slots, and the opening-window flag. Changing only the first three seconds
is insufficient for this route. If rejected, revise the plan and create a new
`variant_revision`; never silently mutate the approved artifact.

## Controlled opening experiments

For an approved opening-only experiment, register the SKU, experiment, candidate
IDs and opening-package variable before generation. Use the existing cinematic-fast
stage directors and `skills/meta/production-brand-contract.md`: prepare and
approve the complete B0, then freeze its body from frame 90 and create the
variant experiment. Preserve body footage, captions, narration and BGM rules;
repair a word crossing the boundary before freezing. A changed body requires a
new baseline, experiment and approval. A planning registration or preview does
not establish a frozen baseline or authorize paid generation; creative-lock and
budget approvals still apply. Do not force this route through the five ordinary
default strategies or fabricate three changed shots.

After actual candidate production, the batch exception is resolved from
`artifacts/opening_batch_context.json` (`version: "1.0"`, `experiment_ref`,
`candidate_evidence_refs`) by `lib.opening_batch_context.resolve_opening_context`.
The server supplies the owning project, actual selected candidate ID and child
directory. Its evidence must bind that candidate's current record, rendered
media and canonical props to the approved B0 and verified body. H02 cannot reuse
H01's record identity. Pass the resolved context to the existing diversity
checks; a hand-written flag or user-supplied candidate alias is not authority.
This post-render exception never replaces pre-generation approvals.

If verification fails, keep the failure and repair the evidence or plan;
do not switch to warning mode to force selection. Verified opening variants
may vary in the preregistered variable without the ordinary three-dimension
rule. Identical media still fail, actual distinctness still needs review, and
the exception never automatically counts a preview, repeat export or reused
baseline as a new work. See `skills/meta/batch-production-contract.md` for
approval, evidence and independent-work counting requirements.
