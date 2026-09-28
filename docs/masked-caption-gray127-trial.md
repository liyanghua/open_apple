# s01 gray-conditioned input correction (d032)

2026-09-28. One-variable diagnostic after the rejected d030 trial. User explicitly
approved: “批准单次试验，预留 $0.50”. This is not batch or production acceptance.

## Evidence and hypothesis

The [official VACE guide](https://github.com/ali-vilab/VACE/blob/main/UserGuide.md#31-vace-recognizable-inputs)
defines missing source pixels as gray RGB 127 and white mask pixels as generated.
The [official inpainting annotator](https://github.com/ali-vilab/VACE/blob/main/vace/annotators/inpainting.py)
also replaces masked source pixels with a configured gray before inference.
The previous input preserved text-bearing source pixels while fal preprocessing
was disabled. This differs from the upstream input contract. It is a concrete
adapter gap, not yet proof of the sole cause of the failed visual result. fal's
public `preprocess` description does not establish its internal implementation.

## Single change

Construct control frames as `C = S.copy(); C[M] = 127` before lossless upload.
Use the exact existing source, 12,869-pixel mask, 38→81→38 frame mapping, prompt,
seed and model settings. `preprocess=false` remains fixed: preprocessing is local
and verified rather than delegated to undocumented provider behavior. No mask
dilation, crop, new references, full-frame recolor, or new narration.

The output remains `O = S.copy(); O[M] = G[M]`. Gray is model conditioning, never
a final cover plate. Reject gray holes, old text, seams, edge drift or flicker.

## Contract and implementation

- Historical version-1 contracts remain readable and tied to d030. Do not rewrite
  the prior files, claim, request, cost entry or rejection.
- Version 2 explicitly records `input_preprocessing=vace_gray127`; validate all
  81 decoded frames: masked pixels exactly 127, all unmasked pixels exactly source.
- `prepare` accepts this explicit mode. The provider binds d032 to version 2 and
  rejects a raw version-1 input before upload or inference.
- d032 has a separate permanent claim and operation
  `s01_wan_vace14b_gray127_once`. At most one new inference POST; all recovery uses
  the owned request. Keep safety, lifecycle and unknown-billing behavior unchanged.
- Test conditioning, tampered inputs, exact approval, old/new claim isolation,
  legacy-contract rejection, duplicate blocking and async resume before the call.

## Approval, cost and acceptance

Provider fal; endpoint `fal-ai/wan-vace-14b/inpainting`, Wan2.1 VACE 14B. The only
upload is the silent preconditioned pilot and exact glyph mask. Public price
checked 2026-09-28: 81/16 × $0.08 = $0.405; reserve $0.50 inside the $8.50 project
budget. Reservation is not a provider-enforced price cap or final invoice.

Deliver 38-frame source / candidate / composite comparison and standalone review
clip. Check all 38 frames, geometry, outside-mask exact RGB and residual text;
record temporal viewing limits honestly. No automatic retry. Neither a passing
test nor successful API completion makes the clip production-ready. Stop at the
single-shot user review; s06 and the full 13.2-second film remain out of scope.
