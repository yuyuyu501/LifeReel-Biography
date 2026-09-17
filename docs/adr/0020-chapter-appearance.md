# Chapter Appearance and Video Preparation

The script's appearance section owns the photo, video-screenshot image, and audio
references for its chapter. The studio has one generation action and no separate
reference replacement form. Images without a matching chapter are not silently
borrowed from another chapter. An empty selection stays empty.

`script_scenes.reference_asset_ids` is nullable: null resolves the chapter's primary
eligible photo and previously measured short audio; an explicit list is authoritative.
Updates validate tenant, subject, consent, types and limits, require the current
script version, and increment it. Script regeneration preserves the chapter's
selection. Production freezes IDs and source hashes before reserving funds.

With `VIDEO_REFERENCE_STYLE=color_redraw`, chapter images are prepared using
SiliconFlow `Qwen/Qwen-Image-Edit-2509` and the `ai-label-v2` prompt. This prompt
preserves the original photo and asks only for the user's text in the bottom-right
corner. `color_redraw` remains the configuration name for compatibility; the
versioned prompt determines the operation. New runs do not impose the previous
hand-drawn video style. Historical tasks and media are preserved.
The pipeline shares durable redraw jobs, including cached results and uncertain-call
protection. It passes the traced prepared images to Seedance as `reference_image`.
A user's explicit generation retry can retry a transient redraw failure, bounded
to that failed attempt and the existing redraw retry limit. Queue deliveries do
not automatically repeat failed redraw requests; concurrent preparations wait
for the existing job's execution lock. Completed redraws remain cached.
A redraw failure never falls back to the original. Neither a successful redraw nor
granted source consent is represented as approval by the video platform. Normal
moderation still applies, and a rejection does not trigger automatic substitutions
or repeated provider calls. Subsequent segments retain the original continuation
path and completed segment billing.

MP3/WAV references are passed as `reference_audio`. Seedance 2.0 requires an image
or video alongside audio, each audio must be 2-15 seconds, and combined audio must
not exceed 15 seconds. Validate these constraints before a production reserve.
Support at most nine images and three audio files. Uploaded video screenshots are
ordinary JPEG, PNG, or WebP images; full video extraction is not part of this UI.

The style and prepared-image prompt version participate in production idempotency.
A failed run from a previous pipeline or prompt version starts a new run under
the current configuration. Settings expose the prompt version so the studio can
detect both changes without resuming frozen old inputs. Prepared image records
and asset metadata must match the run's prompt version.

Release requires migration `20260917_0028`, a configured photo redraw provider,
and `VIDEO_REFERENCE_STYLE=color_redraw` in the server environment. The migration
only adds a nullable column, so previous runtime images can still read the schema.
Routine verification uses isolated databases and mocked AI providers.

Provider references checked on 2026-09-17:

- https://docs.volcengine.com/docs/82379/2298881?lang=zh
- https://ark.volcengine.com/region:cn-beijing/docs/82379/1520757?lang=zh
