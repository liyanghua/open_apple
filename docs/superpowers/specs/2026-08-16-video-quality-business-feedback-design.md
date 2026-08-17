# Video Quality and Business Feedback Design

**Date:** 2026-08-16  
**Revision:** 2026-08-17
**Status:** Ready for user review  
**Scope:** Define a business-oriented quality system for OpenMontage videos, covering intrinsic video quality, user acceptance, online performance feedback, attribution, and the generation lifecycle for social content and performance marketing.

## Problem

OpenMontage currently has stage-level review focuses, artifact validation, human approval gates, and final render checks. These controls answer whether a stage completed correctly, but they do not yet provide a unified business answer to three questions:

1. Is the generated video usable and publishable?
2. Did the user accept and publish it?
3. Did it achieve the intended online result at an acceptable cost?

Without this separation, a technically valid render may be treated as a successful video even when the user rejects it, while a good video may be blamed for low reach caused by distribution. The system also lacks a consistent feedback path from online results to the generation stage that should improve.

## Business Scope

The first design serves two external-distribution scenarios:

- **A: Social content** — optimize effective viewing, completion, interaction, sharing, and follower growth.
- **B: Performance marketing** — optimize CTA reach, click-through, attributed leads or purchases, acquisition cost, and conversion value.

For any order whose destination is Douyin e-commerce, the minimum content
quality baseline is the platform's published "什么是抖音电商优质短视频？" standard
(retrieved 2026-08-17):

<https://school.jinritemai.com/doudian/web/articlev0/aHd3psfsVEY6>

This platform baseline is a release prerequisite. It is not a promise of
traffic allocation, search placement, or conversion; online effectiveness is
still evaluated separately.

The system balances three result families:

- content effectiveness;
- user satisfaction;
- production efficiency.

The primary north-star metric is **Effective Video Rate**. Other metrics explain its scale, cost, and long-term impact.

## Goals

- Define a north-star metric with an auditable numerator, denominator, and settlement state.
- Separate intrinsic quality, user acceptance, online outcomes, and attribution.
- Support mixed benchmarks across established accounts and cold-start users.
- Connect business outcomes to actionable generation stages.
- Preserve comparable measurements across platforms, account sizes, durations, and objectives.
- Expose where videos leave the business funnel and why.
- Define an MVP that can work before every publishing platform and conversion system is integrated.

## Non-Goals

- Produce one universal score that hides the underlying quality dimensions.
- Guarantee that online performance is caused only by the generated video.
- Define provider- or model-specific prompt optimization.
- Automate global generation-policy changes from one video's results.
- Build ad buying, landing pages, attribution networks, or a full customer data platform.
- Replace existing stage review, schema validation, or human approval protocols.

## Approaches Considered

### One composite score

Combine technical quality, creative quality, retention, conversion, and cost into one 0-100 score. This is easy to rank and display but makes different failure modes indistinguishable and encourages arbitrary weights. It is rejected as the primary decision model.

### Layered business funnel (selected)

Evaluate each production order through distinct stages:

`generation success -> quality pass -> user acceptance -> publication -> sufficient data -> business effectiveness`

This preserves diagnosis and creates a direct link between a failed business stage and the team able to improve it.

### Incremental-value experiments

Compare OpenMontage output with account history, human-made content, or alternate generation strategies through controlled experiments. This is the strongest evidence of causal business value but requires stable traffic and experimentation infrastructure. It is retained as a later validation layer, not the cold-start foundation.

## Core Principles

1. **Quality and performance are separate facts.** A high-quality video can underperform because of targeting or distribution; a low-quality video can receive high reach.
2. **Hard gates precede scores.** A compliance, factual, or playback failure cannot be compensated for by a high creative score.
3. **One production order is one denominator unit.** Internal retries and render versions measure efficiency but do not inflate video counts.
4. **Insufficient data is not failure.** Online effectiveness is settled only after the minimum sample requirement is met or the evaluation window expires.
5. **Compare like with like.** Platform, objective, account size, content class, duration, audience, and paid/organic distribution determine the benchmark cohort.
6. **Feedback changes policy only with evidence.** Individual videos produce diagnoses; cohort trends and experiments justify policy changes.
7. **Cheap decisions precede expensive production.** Business intent, strategy, script, and a representative sample are approved before full asset generation.
8. **Platform policy is a floor, not a performance score.** A video must first meet the destination's published quality standard; only then can business outcomes determine effectiveness.

## North-Star Metric

### Effective Video Rate

```text
Settled Effective Video Rate = settled effective production orders
                               / settled eligible production orders

Settlement Coverage = settled eligible production orders
                      / all formal production orders in the reporting cohort
```

The rate is reported together with Settlement Coverage. Pending orders never
silently depress the rate. A production order enters the settled denominator
when it reaches a terminal state; orders still inside a production,
publication, or observation window remain visible in the funnel but do not
enter the settled rate. Cohort reports freeze membership by the order's formal
production authorization time.

A production order is effective only when all of the following are true:

1. the final video passes every hard quality gate;
2. the user accepts the video and publishes it;
3. the observation reaches the minimum valid sample or another approved validity condition;
4. the objective-specific primary metric meets its mixed benchmark;
5. every required guardrail passes its policy-defined comparator.

### Denominator

The denominator counts unique formal production orders after the user approves the business brief and authorizes production. It includes:

- successful orders;
- generation or render failures;
- quality-gate failures;
- user-rejected orders;
- accepted but unpublished orders;
- published orders that settle below benchmark.

It excludes unapproved explorations, strategy alternatives, and sample-only drafts. Their time and cost remain visible as exploration metrics.

### Settlement states

Each order has exactly one current business state:

- `in_production`
- `quality_rework`
- `awaiting_user_decision`
- `user_revision_requested`
- `accepted_unpublished`
- `published_collecting`
- `production_failed` (terminal)
- `quality_failed` (terminal)
- `user_rejected` (terminal)
- `settled_insufficient_data` (terminal and ineffective)
- `settled_effective` (terminal)
- `settled_ineffective` (terminal)
- `excluded_invalid_observation` (terminal and excluded from the denominator)

Exclusion requires a structured reason, such as corrupted analytics, deleted publication, or an approved campaign cancellation. It cannot be used merely because performance was poor.

#### State transitions

| Current state | Event | Next state | Rule |
|---|---|---|---|
| `in_production` | render produced and hard gates pass | `awaiting_user_decision` | The passing hard-gate evaluation is attached before user review. |
| `in_production` | render produced and a hard gate fails | `quality_rework` or `quality_failed` | The failed version is never exposed for user acceptance; rework requires remaining budget. |
| `in_production` | attempt fails and retry budget remains | `in_production` | Attempt count increases; no new order is created. |
| `in_production` | retry budget exhausted or order cancelled for production failure | `production_failed` | Terminal ineffective result. |
| `quality_rework` | rework is authorized | `quality_rework` | Rework remains in the same order and starts from the failed evaluation. |
| `quality_rework` | replacement render produced and hard gates pass | `awaiting_user_decision` | A new `video_version` and its passing hard-gate evaluation are linked to the same order. |
| `quality_rework` | replacement render produced and a hard gate fails | `quality_rework` or `quality_failed` | The version remains hidden from user acceptance; the retry budget determines the next state. |
| `quality_rework` | rework budget exhausted | `quality_failed` | Terminal ineffective result. |
| `awaiting_user_decision` | user requests changes | `user_revision_requested` | Structured reasons are required. |
| `user_revision_requested` | revised render produced and hard gates pass | `awaiting_user_decision` | A new version and its passing hard-gate evaluation are created. |
| `user_revision_requested` | revised render produced and a hard gate fails | `quality_rework` or `quality_failed` | The failed version is hidden from user acceptance; the retry budget determines the next state. |
| `awaiting_user_decision` | user rejects or approval deadline expires | `user_rejected` | Terminal ineffective result. |
| `awaiting_user_decision` | user accepts | `accepted_unpublished` | Publication deadline starts. |
| `accepted_unpublished` | exact accepted version is published | `published_collecting` | One or more publication records may be created. |
| `accepted_unpublished` | publication deadline expires | `settled_ineffective` | Reason is `not_published`. |
| `published_collecting` | window closes with valid sample | `settled_effective` or `settled_ineffective` | Evaluation policy determines the result. |
| `published_collecting` | window closes without minimum valid sample | `settled_insufficient_data` | Remains in the settled denominator and is reported separately from measured underperformance. |
| any nonterminal state | approved invalidation event | `excluded_invalid_observation` | Requires actor, reason code, evidence, and audit timestamp. |

Terminal states never reopen. A resumed production after a terminal state creates
a new production order linked through `supersedes_order_id`. Late metrics create
a new monitoring-only evaluation that references the frozen settlement; they do
not rewrite the north-star result. A documented data-correction operation may
supersede a settlement, but it must preserve both evaluations and the actor,
reason, and correction timestamp.

## Intrinsic Video Quality

### Hard quality gates

Any failure blocks delivery:

- playable output with correct resolution, aspect ratio, frame rate, codec, duration, and file integrity;
- no black frames, broken frames, clipping, unintended truncation, or severe generation artifacts;
- intelligible speech, valid loudness, no destructive clipping, and acceptable audio-video sync;
- accurate subtitles within the platform-safe area;
- stable identity for people, products, logos, and other continuity-critical elements;
- verified factual claims, numbers, quotations, and required disclaimers;
- copyright, privacy, platform policy, and brand compliance;
- no missing required CTA, product, attribution, or disclosure element.

### Douyin e-commerce platform baseline

The following checks are mandatory when `platform=douyin` and the order is an
e-commerce short video. They are encoded as the versioned
`douyin_ecommerce_quality_v1` evaluation policy. A failed item blocks the
platform publication decision and prevents `settled_effective`.

**P0: platform and e-commerce safety**

- no illegal content, pornography, vulgarity, harmful values, or other content
  that violates platform or law;
- no false or exaggerated advertising, prohibited external diversion, illegal
  marketing, prohibited goods, counterfeit goods, or other e-commerce safety
  violations.

**P1: audio and visual quality**

- speech/audio is clear, stable, and at a normal level; persistent distracting
  noise, clipping, electrical noise, stutter, or large volume swings fail;
- preferred resolution is at least `1920x1080`; resolution below `1280x720`
  fails the baseline;
- no material blur, noise, light spots, freezing, or dropped frames;
- unreasonable shake or stutter fails when it occurs at least three times or
  accumulates to at least three seconds, unless the motion is an intentional
  and reasonable part of the shot;
- subtitles, stickers, masks, logos, or decorative text must not materially
  obscure the subject; obstruction above 30% fails, while obstruction above 5%
  is not eligible for the platform's highest cleanliness grade;
- exposure and color must remain natural enough to identify the product; heavy
  beauty filters or color distortion that changes product appearance fail;
- audio, video, and lip movement remain aligned; three or more sync errors or
  at least three seconds of cumulative mismatch fail.

**P2: subject, scene, and readability**

- the product is orderly and clearly distinguishable from the background;
- the primary presenter is clean, appropriate, natural, confident, and
  emotionally stable;
- the background is tidy, balanced, and harmonious with the person and
  product;
- Mandarin is used where practical; dialect or otherwise difficult speech
  must have corresponding standard-Mandarin subtitles;
- language is understandable to an ordinary viewer and specialist terms are
  explained.

**P3: information value and commerce expression**

- the topic is clear from the opening and the product is visibly presented;
- necessary product basics are not missing (for example material, shade,
  usage, ingredients, audience, or other decision-critical attributes);
- normally highlight two to three core selling points, derived from complete
  basic information rather than replacing it;
- show selling points through a combination of speech, captions, close-ups,
  demonstrations, or other appropriate shot language;
- include concrete use scenarios, applicable audiences, conditions, or
  precautions, and maintain person-product-scene consistency;
- provide professional knowledge, comparison, selection guidance, or a
  meaningful demonstration rather than only displaying the product;
- coordinate what is said with what is shown; the video should help the viewer
  understand and make a decision.

**P4: content value and production quality**

- the video has a clear theme, coherent narrative, and sufficient shot or
  scene variation for a short video;
- it is not a still-image carousel, a low-effort splice of livestream/video
  fragments, or a simple content reuse/re-edit with little original value;
- expressed viewpoints and values are socially responsible and do not use
  vulgar, sensational, or harmful themes merely to attract attention.

For the qualitative items, the baseline requires at least the article's
positive/"优质" behavior. An item described as "低质" is a hard failure; an
"一般" result is a warning and cannot be used to claim platform-quality
baseline attainment unless the policy explicitly marks that item as optional.

The platform policy stores a per-check result, evidence reference, severity,
source rule ID, policy version, and remediation destination. It does not replace
the general quality rubric: `P1` maps to audio/visual execution,
`P2` to platform fit and readability, `P3` to message clarity and business
expression, and `P4` to narrative, strategy, and originality.

### Scored quality dimensions

Each dimension uses a 1-5 anchored rubric and structured issue tags. Scores support comparison and diagnosis but cannot override a hard-gate failure.

| Dimension | Business question | Example issue tags |
|---|---|---|
| Message clarity | Is the intended value understandable? | unclear_promise, unsupported_claim, information_gap |
| Opening strength | Is there a reason to continue in the first seconds? | weak_hook, slow_start, cover_mismatch |
| Narrative and pacing | Does the video sustain attention efficiently? | repetition, density_spike, dead_air, weak_payoff |
| Visual execution | Is the visual language coherent and credible? | identity_drift, artifact, hierarchy_failure, generic_visual |
| Audio execution | Is speech natural and the mix usable? | pronunciation, timing, music_masking, loudness |
| Platform fit | Does the asset suit the destination? | unsafe_text, wrong_duration, mobile_illegibility |
| Business expression | Does the video support the desired action? | weak_offer, late_cta, ambiguous_cta, brand_mismatch |

Every review stores evaluator type (`automated`, `human_reviewer`, or `user`), rubric version, score, issue tags, and evidence. This prevents score changes caused by a new rubric from being mistaken for creative improvement.

## User Acceptance

User behavior is an independent quality signal:

- first-version acceptance rate;
- final acceptance rate;
- average revision rounds;
- time from approved brief to publishable version;
- publication rate;
- abandonment rate;
- structured rejection reasons;
- repeat usage and sustained user success.

Required rejection reasons include requirement misunderstanding, strategy mismatch, script weakness, visual style mismatch, generation defect, voice or audio issue, brand or compliance concern, and excessive revision cost. Free-form comments may supplement but not replace the structured reason.

## Online Feedback Model

### Common funnel

```text
eligible exposure -> start -> early retention -> deep viewing
                  -> interaction or click -> attributed conversion
```

Raw platform metrics are stored unchanged. Derived rates are computed from versioned definitions so that platform API changes do not silently rewrite history.

### Metric definition contract

Every metric used for settlement is registered in an `evaluation_policy` with:

- stable `metric_key` and human-readable name;
- policy version and platform adapter version;
- unit (`count`, `seconds`, `ratio`, `currency`, or `currency_ratio`);
- numerator source and denominator source;
- eligibility filters and deduplication key;
- aggregation (`sum_ratio`, `mean`, `median`, or percentile);
- comparison direction (`higher_is_better` or `lower_is_better`);
- missing-data behavior (`required`, `optional`, or `proxy_allowed`);
- minimum valid sample, observation window, and maximum data-lag allowance.

Platform-specific policies also store the source URL, source retrieval date,
platform rule IDs, baseline check definitions, and policy ownership
(`quality_floor`, `business_metric`, or `guardrail`). A policy cannot be
activated without these provenance fields.

An evaluation policy cannot be activated if any required metric lacks a numeric
minimum sample, a window, a comparator direction, or a missing-data rule. This
makes platform-specific threshold tuning configuration rather than undefined
runtime behavior.

V1 uses the following canonical formulas. Platform-specific counters must map to
these fields with provenance; a platform metric with materially different
semantics receives a different metric key rather than being coerced.

| Metric key | Formula | Unit and validity |
|---|---|---|
| `start_rate` | `qualified_starts / eligible_impressions` | Ratio; impressions and starts must use the same platform eligibility scope. |
| `early_retention_rate` | `views_reaching_3s / qualified_starts` | Ratio; for videos shorter than 3 seconds, use `views_reaching_95pct / qualified_starts` under a separate short-video policy. |
| `normalized_watch_rate` | `total_watch_seconds / (qualified_starts * video_duration_seconds)` | Ratio; capped at 1 for settlement, with uncapped replay contribution stored separately. |
| `completion_rate` | `views_reaching_95pct / qualified_starts` | Ratio; 95% is the canonical completion point in V1. |
| `replay_rate` | `max(total_plays - qualified_starts, 0) / qualified_starts` | Ratio; available only when play and unique-start semantics are compatible. |
| `engagement_rate` | `(likes + comments + saves + shares) / qualified_starts` | Ratio; component counts remain individually available. |
| `follower_conversion_rate` | `attributed_new_followers / qualified_starts` | Ratio; requires platform attribution within the policy window. |
| `cta_reach_rate` | `unique_viewers_reaching_first_cta_timestamp / qualified_starts` | Ratio; may be derived from a retention curve and must record `derived=true`. |
| `cta_click_rate` | `unique_attributed_outbound_clicks / qualified_starts` | Ratio; click deduplication follows the platform adapter contract. |
| `landing_arrival_rate` | `unique_landing_page_arrivals / unique_attributed_outbound_clicks` | Ratio; requires click and arrival identity from the same attribution window. |
| `qualified_conversion_rate` | `qualified_attributed_conversions / qualified_starts` | Ratio; useful when click identity is unavailable but platform conversion attribution is available. |
| `post_click_conversion_rate` | `qualified_attributed_conversions / unique_attributed_outbound_clicks` | Ratio; missing click identity makes this metric unavailable, not zero. |
| `conversion_value_per_cost` | `attributed_conversion_value / total_distribution_and_production_cost` | Currency ratio; currency and attribution window must match. |
| `cost_per_qualified_conversion` | `total_distribution_and_production_cost / qualified_attributed_conversions` | Currency; lower-is-better and unavailable when conversions are zero. |
| `return_on_ad_spend` | `attributed_conversion_value / distribution_cost` | Currency ratio; lower-scope production cost is not included unless policy says so. |
| `negative_feedback_rate` | `(hides + not_interested + reports) / qualified_starts` | Ratio and lower-is-better; components remain separately visible. |

Division by zero yields `unavailable`, never zero. Required unavailable metrics
prevent valid settlement and lead to `settled_insufficient_data` when the window
closes. Aggregated ratios use summed numerators divided by summed denominators;
they are not the unweighted mean of per-video rates.

### Scenario A: social content

The declared primary metric must be one of these canonical keys:

- `normalized_watch_rate`;
- `completion_rate`.

Secondary outcome measures (diagnostic unless selected as the policy primary):

- `replay_rate`;
- `engagement_rate` (the component like/comment/save/share counts remain raw);
- `follower_conversion_rate`.

Guardrails:

- `early_retention_rate` (low value is a failure condition);
- `negative_feedback_rate` (high value is a failure condition).

The default effectiveness decision uses one declared primary measure and at least one retention guardrail. Engagement and follower growth explain business value but do not rescue a severe retention or negative-feedback failure.

### Scenario B: performance marketing

The declared primary metric must be one of these canonical keys, selected in
descending order of verification strength:

1. `conversion_value_per_cost` or `post_click_conversion_rate`;
2. `qualified_conversion_rate`;
3. `cta_click_rate` when downstream attribution is unavailable.

Supporting measures (diagnostic unless selected as the policy primary):

- `cta_reach_rate`;
- `landing_arrival_rate`;
- `cost_per_qualified_conversion`;
- `return_on_ad_spend`;
- a policy-registered negative-conversion metric for refunds, invalid leads, or low-quality conversions.

Using click-through as a proxy must be explicitly recorded. Proxy-based effectiveness and conversion-verified effectiveness are not reported as equivalent confidence levels.

### Observation windows

- **24 hours:** early diagnostic snapshot, never the only final result when sample volume is insufficient.
- **7 days:** default social-content settlement window.
- **30 days:** marketing conversion and long-tail settlement window.

Each platform-objective pair may override these defaults through a versioned evaluation policy.

## Mixed Benchmark

The evaluator selects the best available benchmark in this order:

1. the account's prior 60-day median for comparable settled publications when at least 20 are available; expand once to the prior 90 days when the 60-day sample is smaller than 20;
2. a cohort median matched on platform, objective, industry, account scale, duration, format, audience, and paid/organic status, requiring at least 100 publications from at least 20 accounts;
3. a versioned absolute floor when neither history nor a valid cohort exists.

The comparison record stores the selected benchmark source, value, cohort definition, sample count, and policy version. The system must not silently switch benchmark sources after settlement.

Comparable history always ends immediately before the evaluated publication's
timestamp, so the evaluated result never leaks into its own benchmark. Cohort
matching fields and fallback order are part of the evaluation policy; a missing
match does not permit an ad hoc broader cohort.

The initial decision rule is deliberately interpretable:

- pass the declared primary metric's benchmark, using `observed >= benchmark`
  for higher-is-better metrics and `observed <= benchmark` for lower-is-better
  metrics; equality passes;
- pass all required guardrails under the same direction rule;
- meet minimum sample validity.

A required missing primary metric or guardrail produces insufficient data, not
a pass or fail. Optional guardrails are omitted from the decision with an audit
note. A `proxy_allowed` primary metric may settle an order, but the evaluation
is marked `verification_tier=proxy`; proxy and conversion-verified results are
reported separately and never pooled into one benchmark cohort.

A weighted composite may be shown as a dashboard summary, but it cannot determine effectiveness without the underlying rule results.

## Attribution Rules

Attribution is diagnostic rather than absolute. The initial rule set is:

| Observed pattern | Primary diagnostic destination |
|---|---|
| Low eligible exposure | distribution, timing, audience selection, topic demand |
| Normal exposure and low starts | cover, title, first frame, opening promise |
| Strong start and high early loss | hook-body mismatch, opening pacing, misleading promise |
| Good early retention and mid-video loss | script structure, repetition, scene density |
| Good viewing and weak interaction | emotional value, point of view, interaction design |
| Good completion and low CTA reach | CTA position or script structure |
| High CTA reach and low clicks | offer, message, CTA wording, audience fit |
| High clicks and low conversion | landing page, price, product, lead flow; normally not generation quality |
| User does not publish | brief understanding, editability, creative direction, or final quality |

Every diagnosis includes a confidence level and evidence. Low exposure reduces confidence in content-quality attribution. Paid traffic must be separated from organic traffic because spend and targeting materially affect reach and conversion.

### Stable attribution contract

Diagnostics use stable destination codes that map to existing or external
business stages:

| Destination code | OpenMontage/business stage |
|---|---|
| `external_distribution` | publishing, timing, targeting, or platform delivery |
| `objective_definition` | `idea/research -> brief` |
| `content_strategy` | proposal and creative direction |
| `script_hook` | opening script and first 3-8 seconds |
| `script_structure` | script body, payoff, and CTA placement |
| `scene_plan_pacing` | scene duration and information density |
| `asset_execution` | generated visual, voice, music, and subtitle assets |
| `edit_compose` | edit rhythm, transition, mix, and final composition |
| `cta_expression` | offer, CTA wording, and CTA visual treatment |
| `external_conversion` | landing page, price, product, lead flow, or sales process |

Each attribution rule in the versioned evaluation policy declares its required
metrics, benchmark-relative conditions, confounder exclusions, destination
code, and confidence thresholds. V1 assigns confidence deterministically:

- `high`: every required metric is valid, the diagnostic-side metric differs
  from its benchmark by at least 20% relative, and no declared confounder is present;
- `medium`: every required metric is valid and the relative difference is at
  least 5% but less than 20%, with no declared confounder;
- `low`: the pattern is directionally present but below 5%, relies on a proxy,
  or has a declared confounder.

Relative difference is `abs(observed - benchmark) / abs(benchmark)`. A zero
benchmark uses a policy-defined absolute delta. Low-confidence diagnostics are
shown as hypotheses and cannot initiate a policy experiment without human
review.

## Business-Oriented Generation Lifecycle

### 1. Objective definition

Answer why the video should exist. Capture platform, account, scenario A or B, audience, primary goal, primary metric, offer or message, duration, budget, publication timing, constraints, and unacceptable outcomes.

**Gate:** one primary objective, one primary online metric, a defined audience and platform, and explicit constraints.

**OpenMontage mapping:** `idea/research -> brief`.

### 2. Content strategy

Answer which content hypothesis should achieve the objective. Define topic, audience need, angle, promise, hook, emotional direction, visual direction, evidence, CTA, expected baseline, and risks. Generate a small set of alternatives and approve one.

**Gate:** hook-body consistency, audience relevance, objective-aligned CTA, credible evidence, and a stated reason the strategy should work.

### 3. Script and scene structure

Answer why a viewer should continue from the first second to the final action. Use the business sequence:

`hook -> problem or benefit -> evidence or value -> memorable payoff -> CTA`

Each section records its business purpose, expected duration, message, visual treatment, and expected observation point.

**Gate:** strong opening promise, no unnecessary repetition, platform-appropriate length, factual validity, and correctly timed CTA.

**OpenMontage mapping:** `script -> scene_plan`.

### 4. Creative sample

Validate the highest-risk creative choices before full production. The sample should normally include the cover or first frame, first 3-8 seconds, one representative body scene, narration and subtitle treatment, and CTA treatment.

**Gate:** explicit approval of strategy, character or product representation, visual language, voice, pacing, and CTA treatment.

**Metrics:** first-pass sample approval, sample revision count, time to sample, sample cost, and direction-related cancellation rate.

### 5. Formal production

Generate complete assets, narration, edit, composition, and render only after the creative direction is locked.

**Metrics:** generation success, first-useful-asset rate, automated repair rate, provider and model stability, elapsed time, cost per production order, internal attempts, and human intervention time.

**OpenMontage mapping:** `assets -> edit -> compose`.

### 6. Publication acceptance

Run automated hard gates, including the destination platform baseline, then
capture user acceptance as direct accept, accept after revision, reject, or
abandon. For Douyin e-commerce, the `douyin_ecommerce_quality_v1` result must
be `pass` before the user can mark the version publishable. A rejection requires
a structured reason. If the optional platform pre-review tool is available, its
result is stored as supporting evidence rather than treated as the system's
only quality decision.

**Metrics:** first-version acceptance, final acceptance, revision rounds, time to publishable output, publication rate, and abandonment reasons.

### 7. Online learning

Collect performance snapshots at the applicable windows and join them to the exact published video version, production configuration, quality review, user decision, and benchmark policy.

**Gate:** sufficient observation validity before settlement. One video may create a diagnosis; only aggregate evidence creates a proposed policy change.

**OpenMontage mapping:** extend `publish` with post-publication observations and evaluations while keeping raw platform data separate from derived decisions.

## Feedback-to-Generation Policy

Learning operates at three levels:

1. **Video diagnosis:** identify probable issues for one published version.
2. **Cohort insight:** aggregate comparable videos and find stable patterns after minimum sample and confidence thresholds.
3. **Policy experiment:** test a proposed change against the current policy with a declared objective, holdout, evaluation window, and rollback condition.

No model, provider, prompt template, script rule, or default style is promoted solely because one video performed well. Policy changes are versioned so later orders can be attributed to the policy that produced them.

## Core Data Objects

Every object has an immutable string ID, `created_at`, and schema version. Foreign
keys are explicit; timestamps are UTC. Mutable business state is changed through
audited events, while observations and evaluations are append-only.

| Object | Identity and required references | Cardinality and ownership |
|---|---|---|
| `production_order` | `order_id`; required `project_id`, `user_id`, approved `brief_version_id`, `settlement_policy_id`, primary platform and objective; optional `supersedes_order_id` | One order owns many video versions and user decisions. It is the denominator entity and owns the business state. `settlement_policy_id` defines whether one primary destination, any destination, or all required destinations determine order settlement. |
| `video_version` | `video_version_id`; required `order_id`, exact artifact hashes, script and scene-plan version IDs, generation-policy version | Many versions belong to one order. Version number is unique within the order; rendered media identity is immutable. |
| `quality_evaluation` | `quality_evaluation_id`; required `video_version_id`, rubric or platform-policy version, evaluator identity/type, check results, and evidence | Many append-only evaluations may assess one version; one explicitly selected final hard-gate evaluation governs publication eligibility. Platform baselines and general rubrics remain distinguishable. |
| `user_decision` | `user_decision_id`; required `order_id`, decision type, actor; `video_version_id` required for version-specific acceptance or rejection | Many chronological decisions belong to one order. The latest valid final acceptance selects exactly one accepted version at a time. |
| `publication` | `publication_id`; required `video_version_id`, platform, account ID, platform post ID, published time, paid/organic status, `evaluation_policy_id`, and `is_primary_destination` | One exact version may have many publications. `(platform, account_id, platform_post_id)` is globally unique. A publication never changes to point at another version. Its policy owns metric semantics for that destination. |
| `performance_snapshot` | `snapshot_id`; required `publication_id`, observed-at time, source and adapter version | Many immutable snapshots belong to one publication. `(publication_id, observed_at, source_revision)` is unique. Corrections append a superseding snapshot. |
| `benchmark_record` | `benchmark_record_id`; required `publication_id`, metric key, evaluation-policy ID, source, cohort definition, frozen value | One frozen record exists for each evaluated publication, metric, policy, and settlement run. It owns the benchmark provenance used by the evaluation. |
| `effectiveness_evaluation` | `effectiveness_evaluation_id`; required `order_id`, `settlement_policy_id`, settlement run ID, and evaluation scope (`publication_id` or order-level combination); references included publication IDs, snapshot IDs, and benchmark-record IDs | Many append-only evaluations may belong to an order, but only one is the current official settlement. It owns metric results, validity, verification tier, attribution, and state result. Destination evaluations use each publication's policy; the official order evaluation combines them using the order's settlement policy. |
| `evaluation_policy` | `evaluation_policy_id`; required platform, scenario, policy ownership, source URL/retrieval date, metric definitions, platform baseline checks, validity rules, windows, comparator and attribution rules | Immutable once used. Many publications may reference one versioned destination policy. A successor policy receives a new ID. |
| `settlement_policy` | `settlement_policy_id`; required destination mode (`primary`, `any_destination`, or `all_required_destinations`), primary destination or required destination set, and settlement combination rules | Immutable order-level policy. One order references exactly one policy; it never substitutes for a destination's metric policy. |
| `policy_experiment` | `experiment_id`; required control/treatment generation-policy IDs and evaluation-policy ID | Many eligible orders belong to at most one arm of an experiment for the same hypothesis and period. Assignment is immutable. |

When one accepted version is published to multiple destinations, each
publication is evaluated against its own platform policy. The order-level
`settlement_policy_id` declares whether success means `any_destination`,
`all_required_destinations`, or one named primary destination. V1 requires one
named primary publication; secondary publications may still receive
destination-level evaluations but do not create additional denominator units.

## Business Funnel and Dashboards

The executive funnel is:

`production orders -> generated -> quality passed -> accepted -> published -> data sufficient -> effective`

Each stage displays count, conversion rate, median time, median cost, and top loss reasons. The dashboard keeps three supporting views:

- **Effectiveness:** Effective Video Rate, effective video count, and objective-specific online outcomes.
- **Satisfaction:** acceptance, revisions, publication, rejection reasons, and repeat user success.
- **Efficiency:** success rate, cycle time, cost, attempts, and human intervention.

Breakdowns include platform, scenario, user cohort, content class, duration band, provider/model, generation-policy version, paid/organic status, and time period. Small cohorts are suppressed or marked low confidence.

## MVP Boundary

### V1: measurable closed loop

- Capture structured business objective and declared primary metric.
- Create a unique production order at formal-production authorization.
- Persist hard-gate results and a small anchored quality rubric.
- Activate the `douyin_ecommerce_quality_v1` platform baseline for Douyin
  e-commerce destinations, including its P0-P4 checks and numeric thresholds.
- Capture structured user acceptance and rejection reasons.
- Record publication identity and paid/organic status.
- Support manual or CSV performance import when platform APIs are unavailable.
- Implement 24-hour and 7-day snapshots for social content and a configurable 30-day snapshot for marketing.
- Implement mixed benchmark selection and explicit insufficient-data handling.
- Produce the business funnel and four independent results: intrinsic quality, user acceptance, online outcome, and attribution.

### V2: automated collection and diagnosis

- Platform API connectors and scheduled snapshot collection.
- Cohort benchmark service with confidence reporting.
- Rule-based attribution suggestions.
- Exact generation-policy and provider/model comparisons.
- Alerting for funnel regressions and guardrail breaches.

### V3: incremental optimization

- Controlled policy experiments and holdouts.
- Human-made versus generated incremental-value analysis.
- Cost-aware policy selection by platform and objective.
- Recommended strategy, hook, script, or render-policy changes based on validated cohort evidence.

## Acceptance Criteria

The design is implementable when the following questions have deterministic answers:

1. What exact event creates a denominator unit?
2. Why is each order currently effective, ineffective, pending, or excluded?
3. Which hard gate or scored dimension failed, under which rubric version?
4. Did the user reject, accept, publish, or abandon the output, and why?
5. Which exact video version was published?
6. Are online data sufficient and comparable to the chosen benchmark?
7. Which business objective and primary metric govern settlement?
8. Which generation stage should receive each diagnostic signal, with what confidence?
9. Can every policy-level change be traced to cohort evidence or an experiment?
10. Can the executive funnel reconcile from production-order counts without counting retries as new videos?

## Risks and Controls

- **Metric gaming:** use guardrails and retain raw metrics rather than optimizing one visible rate.
- **Survivorship bias:** keep generation failures, rejections, and unpublished approved orders in the denominator.
- **Small samples:** use explicit insufficient-data states and confidence thresholds.
- **Benchmark drift:** version policies and freeze the benchmark record at settlement.
- **Attribution error:** separate paid and organic delivery, retain confidence, and avoid blaming video quality for downstream product failures.
- **Cross-platform inconsistency:** preserve raw platform definitions and compare normalized metrics only within compatible cohorts.
- **Feedback overreaction:** require cohort evidence and controlled experiments before changing defaults.
- **Missing integrations:** allow governed manual imports in V1 and store provenance for every observation.

## Open Implementation Decisions

These decisions belong in the implementation plan rather than this business design:

- whether post-publication objects extend existing artifact schemas or use a dedicated analytics store;
- which platform connector is implemented first;
- initial policy threshold values for the first selected platform, supplied as versioned configuration before activation;
- the first anchored 1-5 rubric wording and evaluator mix;
- dashboard implementation and storage technology;
- authentication and retention policy for connected publishing accounts.
