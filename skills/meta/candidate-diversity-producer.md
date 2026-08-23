# Candidate Diversity Producer

Use this skill only for `candidate_batch` production before any paid asset or
sample render. A single-project video does not enter this contract and keeps
the normal cinematic-fast creative lock flow. Diversity is planned at the
candidate level and approved by a human; it is not a post-render opening
rewrite.

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

Review the six dimension values, the three structural shot slots, and the
opening-window flag. A plan that only changes the first three seconds is not a
valid candidate direction. If the plan is rejected, revise the plan and create
a new `variant_revision`; never silently mutate the approved artifact.
