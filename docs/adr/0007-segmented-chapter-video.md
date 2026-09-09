# ADR 0007: Segmented Chapter Video

Date: 2026-09-09

## Decision

Seedance 2.x production renders the selected chapter in 4-15 second segments,
then assembles one private MP4. The current deployment uses
`doubao-seedance-2-0-mini-260615`, native audio, 720p and 16:9.
Legacy providers retain their existing single-clip behavior.

## Pipeline

1. Freeze the selected script, person context and generation settings on the run.
2. Allocate segment durations from the chapter duration, not the legacy
   `VOLCENGINE_VIDEO_DURATION` value. A 30-second chapter becomes two 15-second clips.
3. Ask the configured script LLM for narration boundaries, visual continuity and
   narrator direction. Validate that narration is preserved verbatim and in order,
   chapters do not mix, and durations match the allocation. Invalid plans retry
   up to three times; there is no deterministic content fallback.
4. Submit one segment per queue delivery. Persist its provider task ID before
   polling. Use the preceding clip's last frame as the next clip's first-frame
   reference and reuse the shared identity and voice description.
5. Probe each clip for duration and required audio; store completed clips privately.
6. Normalize dimensions, frame rate and codecs with FFmpeg, concatenate in order,
   and verify the final file. Do not synthesize silence, accelerate speech or truncate
   output to conceal a failed generation.
7. Store one final asset and show planning, segment progress and assembly in Studio.
   Publishing remains a separate action.

## Retry And Safety

- Configuration participates in the idempotency key. Changing models does not reuse
  an old silent render. Repeated starts with the same version/settings return the
  existing run.
- A PostgreSQL advisory lock prevents concurrent execution of one run, including
  across checkpoint commits.
- Completed clips are reused. Polling failures keep their task IDs, so a retry
  queries the existing provider task instead of submitting another paid request.
- Explicit terminal provider failure permits a new task on user retry.
- Ambiguous submission (request sent but no reliable task ID received) stops with
  `VIDEO_SUBMISSION_UNCERTAIN`. Check the provider console before reconciliation;
  the application does not blindly resubmit.
- Provider output that fails media validation stays failed. A retry can re-fetch
  the original result; it does not silently charge for a replacement generation.

## Limits And Follow-Ups

- Each input chapter must be 4-300 seconds; at most 24 segments per run.
- Native generators may round durations by frames. Validation allows up to one
  second difference per clip. The player displays the actual duration.
- Exact narration allocation in prompts does not prove exact speech in output.
  Native pronunciation, omitted words, voice consistency and visual identity need
  content-level acceptance checks. First-frame reference alone cannot guarantee them.
- The existing Redis queue has no durable acknowledgement. Checkpoints prevent
  duplicate known submissions, but do not guarantee automatic recovery from every
  worker crash between database commit and enqueue. Durable queue delivery and
  explicit uncertain-submission reconciliation are follow-up work.

## Regression Coverage

`test_segmented_production.py` covers duration bounds, narration preservation,
checkpoint continuation after a second-segment timeout, uncertain submission,
real FFmpeg audio/video concatenation order and missing-audio rejection.
`test_providers.py` verifies the model, audio, resolution, ratio and reference frame
request contract. `ScriptsAndStudio.test.tsx` checks chapter duration and progress.

## Live Acceptance Run (2026-09-09)

- Existing test person's first chapter, target 30 seconds; no publication action.
- Run `8646949e-a25e-4c3c-af04-f9bcca6c57ee` completed through the normal worker queue.
- Two cloud tasks succeeded, each 15.104 seconds with native AAC audio and 1280x720
  frames. The second task accepted the previous-frame reference.
- Final asset `af8cdc93-d83a-44f3-a7cd-1dc1f35cce1e`: 30.229333 seconds,
  1280x720, AAC audio. Full FFmpeg decode succeeded; mean volume -13.8 dBFS,
  peak 0 dBFS (non-silent; loudness/peak mastering is not implemented).
- Local Whisper transcription spans both segments through the final sentence.
  It contains minor wording/recognition differences, so exact spoken-text fidelity
  is not certified. Visual samples retain an older male subject, similar clothing,
  calligraphy and the same room; continuous audiovisual identity is not guaranteed.
- Backend focused regression: 27 passed (four dependency deprecation warnings).
  Frontend: 31 passed; production build and scoped Ruff checks passed.
- Browser session expired. Full in-page playback and responsive screenshots of the
  new result remain unverified pending restoration of the user's login session.
