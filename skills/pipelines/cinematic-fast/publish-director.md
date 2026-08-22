# Publish Director - Cinematic Fastline

Read the complete `skills/pipelines/cinematic/publish-director.md` and
`skills/meta/fastline.md` before acting. Package the verified local render,
metadata and QA evidence under the project workspace. This stage never uploads
to Douyin, WeChat Channels, Xiaohongshu or another external platform without a
separate explicit authorization.

## L1a hard gate (publish precondition)

Publish requires the final-scope `evaluation_report` produced by compose. Read
`evaluation_report.hard_gate.pass` and `evaluation_report.status`:
`status == "fail"` (any fatal L1a failure: SKU/price/params/sensitive words)
means the deliverable must NOT be published — surface the failing checks to the
user and stop. `status == "revise"` means fixable L1a failures remain; record
them in the publish decision and proceed only with the user's explicit
acknowledgement. `creative_advisory` is informational and never a publish
blocker in the first phase.

