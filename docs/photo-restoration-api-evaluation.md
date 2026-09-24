# Photo restoration API evaluation

Reviewed: 2026-09-18. This is a shortlist based on public provider documentation,
not a measured quality ranking. No paid inference or private-photo upload was
performed. Application configuration and production runtime are unchanged.

## Current implementation

`providers/siliconflow.py` fixes the model to `Qwen/Qwen-Image-Edit-2509` and
uses 20 inference steps. `modules/restoration/service.py` calls the same image
editing adapter as portrait redraw, with a separate restoration prompt.
Restoration inherits `PHOTO_REDRAW_PROVIDER`; it has no independent backend.

The prompt requests preservation of identity, composition and black-and-white
appearance unless colorization is selected. These are instructions to a
generative model, not enforced fidelity guarantees. The code alone does not
establish why a particular photograph produced an unsatisfactory result.

## Candidates

| API | Best initial evaluation use | Public price observed | Limits |
| --- | --- | --- | --- |
| Topaz via fal, `fal-ai/topaz/upscale/image` | Blur, noise, compression and low-resolution portraits | USD 0.08 per image up to 24 MP output; larger outputs cost more | Enhancement is not a guarantee of scratch removal or identity preservation. Compare precision models before generative models. |
| SeedVR2 via fal, `fal-ai/seedvr/upscale/image` | Low-resolution photographs and whole-image detail enhancement | USD 0.001 per megapixel | Verify metering and output size when budgeting. It is an upscaler, not a dedicated scratch-removal or colorization interface. |
| fal Photo Restoration, `fal-ai/image-editing/photo-restoration` | Damaged or faded photographs and restoration with color | USD 0.04 per image | Description includes colorization; the documented input schema has no colorization-disable switch or custom prompt. It cannot yet be assumed compatible with conservative black-and-white restoration. |

Prices are from the public pages on the review date, not contractual quotes.
All three pages display a commercial-use label. Provider latency, service
availability from the deployment server and actual output quality remain untested.

### Topaz evaluation settings

Start with `Standard V2` and `Low Resolution V2`, output PNG, and a 2x upscale.
Compare face enhancement disabled against a conservative setting with
`face_enhancement_creativity=0` and reduced `face_enhancement_strength`.
These are proposed evaluation settings, not measured optimal settings.
The API also exposes `denoise`, `sharpen` and `fix_compression` independently.

The shared schema mentions `Recover 3`, `Dust-Scratch V2` and `Faces` in
`ImageRestoreRequest`. However, the corresponding public restore model page
returned HTTP 404 during this review. Treat that separate route's availability
and price as unconfirmed; do not implement against it solely from the shared
schema.

### Older alternatives

- Microsoft Bringing Old Photos Back to Life on Replicate exposes `HR` and
  `with_scratch`. The published version inspected was created in 2022 and does
  not expose colorization. Keep it as an optional scratch-removal baseline,
  not an assumed upgrade over current models.
- CodeFormer exposes a quality/fidelity tradeoff for face restoration. Its
  upstream S-Lab license permits non-commercial use and requires contacting
  contributors for commercial use. A hosted API listing alone does not resolve
  that licensing question for this product.

## Recommended evaluation

Use the current Qwen output as the baseline. Compare Topaz and SeedVR2 for
low-resolution or noisy images; compare fal Photo Restoration for damaged images
where colorization is acceptable. Evaluate independent outputs before composing
multiple paid stages.

Use a fixed set of 12 authorized sample photos: three low-resolution portraits,
three scratched or creased prints, three faded photos, and three group photos.
Include both black-and-white and color sources. Samples must be explicitly
approved for upload to the chosen provider; do not automatically draw from the
private evidence library.

Inspect at matched display sizes and at 100% crops. Prioritize identity,
age/expression, preservation of people and text, damage removal, natural skin
texture, and color-mode compliance. Reject results that change identity or
invent/remove subjects even when they look sharper. Record latency, failure
rate, delivered dimensions and cost separately from quality scores. Obtain
the photo owner's judgment of likeness when possible.

## Integration after model selection

- Give restoration an independent provider configuration while retaining the
  existing portrait redraw behavior.
- Freeze backend, model/version and effective settings in each job and its
  idempotency key. Preserve old job provenance when configuration changes.
- Persist asynchronous provider request IDs and resume polling without
  automatically resubmitting an uncertain paid request.
- Keep originals and results separate. Validate downloads, never forward API
  credentials to output hosts, and keep the API key server-side.
- Preserve the explicit colorization choice; reject unsupported modes rather
  than silently ignoring them or adding an undisclosed second model call.
- Verify with isolated databases and mocked HTTP calls. Sample-quality
  evaluation is a separate activity from routine release verification.

No provider has been selected for deployment. No migration or release was
performed as part of this research.

## Sources

- [Topaz API and parameter schema](https://fal.ai/models/fal-ai/topaz/upscale/image/api)
- [Topaz public pricing](https://fal.ai/models/fal-ai/topaz/upscale/image)
- [SeedVR2 API](https://fal.ai/models/fal-ai/seedvr/upscale/image/api)
- [SeedVR2 public pricing](https://fal.ai/models/fal-ai/seedvr/upscale/image)
- [Photo Restoration API](https://fal.ai/models/fal-ai/image-editing/photo-restoration/api)
- [Photo Restoration public pricing](https://fal.ai/models/fal-ai/image-editing/photo-restoration)
- [Microsoft restoration API](https://replicate.com/microsoft/bringing-old-photos-back-to-life/api)
- [CodeFormer API](https://replicate.com/sczhou/codeformer/api)
- [CodeFormer upstream license](https://github.com/sczhou/CodeFormer/blob/master/LICENSE)
