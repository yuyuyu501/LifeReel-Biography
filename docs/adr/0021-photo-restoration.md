# Standalone Photo Restoration

The `/photo-restoration` workspace has a separate sidebar entry. Users can upload
a JPEG, PNG, or WebP up to 10 MiB without creating a person, interview, or script.
Uploading does not call an AI provider. Explicit start creates a durable
`photo.restoration` job; the database video lane executes it.

SiliconFlow `Qwen/Qwen-Image-Edit-2509` uses the independent
`photo-restoration-v1` prompt. Conservative restoration removes scratches,
creases, stains, and noise while prioritizing identity, age, expression, original
composition, and photographic texture. Black-and-white stays black-and-white
unless the user checks colorization. AI restoration can invent missing details;
the prompt is a constraint, not a guarantee of historical accuracy or likeness.
Portrait redraw and chapter-video prompts are unchanged.

Originals are tenant-scoped in `restoration_photos`, deduplicated by content
hash, and kept in private storage. Results are stored separately. All media,
history, task, and export endpoints enforce tenant ownership. Job identity
includes source, model, provider, prompt text and version, and colorization.
Duplicate starts return the existing task. Inputs are frozen on creation.
Requests are checkpointed before provider invocation; interrupted calls fail as
uncertain and are never automatically submitted again. Explicit retries are
bounded to three attempts and clear the old worker lease under the execution
lock. Provider rejection and invalid source require a new suitable upload.

The page supports history, a before/after comparison slider, zoom, and download.
Only an explicit save copies a result to a selected person's assets. It records
the original photo ID, hash, task ID and prompt version, and marks the asset as
synthetic restoration. Existing originals are never overwritten. Restored images
cannot be analyzed as factual evidence and are excluded from automatic chapter
reference selection. Users may explicitly choose them in chapter appearance.
No restoration action starts video generation.

Configuration reuses `PHOTO_REDRAW_PROVIDER=siliconflow`, `SILICONFLOW_API_KEY`,
and `JOB_QUEUE_BACKEND=database`. The key remains server-side. Like standalone
redraw, image-edit provider costs are borne by the operator; this feature does
not add wallet charges or a new pricing policy. Development may use the mock
provider. Routine verification uses isolated databases and mocked provider calls.

Release requires migration `20260918_0029`, then the updated API and web runtime
and a running database worker. This migration adds one independent table and is
compatible with rolling back to the previous runtime images. Back up the
database and environment and retain those images before deployment.
