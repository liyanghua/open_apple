# d034 — local mask-interior boundary refinement

User feedback on 2026-09-28: “旧字母去除比较干净，继续”. This accepts the
caption-removal result and continues the proposed local refinement, not a new
model call, batch, s06 generation or approval of the whole film.

## Diagnosis and minimal correction

v2 hard-composites a generated patch into original RGB. At source frame 19 the
one-pixel exterior ring differs from the generated candidate by mean absolute
5.338 RGB levels (maximum 53); the resulting boundary is visible. Some mismatch
may also be geometric; color correction cannot prove or fix geometry alignment.

Use the existing d032 candidate and exact unchanged glyph mask. Solve a harmonic
color correction D inside M, with exterior boundary D = source − candidate,
then output candidate + D inside M and original source outside M. This is the
discrete gradient-domain/Poisson boundary-matching formulation; preserve the
candidate's interior Laplacian, never blend source glyph pixels back in.

No blur, dilation, opacity band, resizing, motion change, or cross-frame averaging.
No pixel outside M may change. Source RGB inside M must not influence the solve.
Use NumPy matrix-free conjugate gradients with bounded iterations and residual
checks; no new dependency or service. Reject nonconvergence, invalid geometry or
unsupported masks. Keep old hard compositing the default for compatibility;
opt-in `blend_mode=boundary_match` requires a version-2 input contract.

## Verification and delivery

Test constant color-offset recovery, candidate detail retention, independence
from source glyph pixels, identical repeated output, no input mutation, invalid
masks and nonconvergence. Re-run existing caption/cost tests. Run through registry
`masked_caption_composite` in the hybrid assets stage in the existing isolated
branch. Keep all historical artifacts, no active asset replacement.

Output a v3 38-frame diagnostic, original/candidate/v3 comparison, and v2/v3
comparison. Verify lossless exterior RGB, inspect all 38 repaired regions, and
record remaining alignment/temporal limits. A solver pass is not a visual pass.

Concept reference: [Pérez et al., Poisson Image Editing](https://www.cs.jhu.edu/~misha/Fall07/Papers/Perez03.pdf).
