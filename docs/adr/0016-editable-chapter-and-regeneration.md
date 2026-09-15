# Editable chapters and interview regeneration

## Decision

The interview, script book and studio share one four-part chapter reader/editor:
plot, shots, dialogue (including narration), and setting. The book's left directory
is its only chapter selector. The interview gives chat and script independent
scroll containers; mobile switches between the panes.

Manual edits use PATCH /v1/scripts/{project_id}/scenes/{scene_id}. They update the
existing chapter without calling AI or charging the wallet. Tenant ownership,
the subject execution lock and expected project version prevent cross-family
access and stale overwrites. A queued/running interview blocks manual edits.
Shot durations must sum to the chapter duration. Narration is derived from the
ordered dialogue lines. Production snapshots remain immutable and appear in a
separate production section, never as the editable current chapter.

An explicit regenerate button submits an idempotent queued interview turn.
For ordinary messages the interview model classifies semantic intent before
memory extraction. Pure rewriting commands are retained in chat but excluded
from biographical claims. Mixed messages can contain both facts and instructions.
Intent is checkpointed for workflow recovery and billed through existing actual
usage tracking. Provider failures do not fall back to hardcoded production logic.

Readiness and generation receive the current chapter and the user's revision
instructions. Follow-up acknowledges a successful rewrite, or asks for genuinely
missing information when the evidence is insufficient. All four parts are in
the generation contract introduced in ADR 0015; legacy plots are not fabricated
or retroactively generated without a user request.

## Verification

Backend tests cover version conflicts, tenant isolation, duration validation,
unchanged historical snapshots, free manual edits, regeneration idempotency and
exclusion of rewriting instructions from memories. Frontend tests cover saving,
cancelling, errors and ordering. Intercepted browser fixtures verify all three
pages at 1440, 390 and 320 pixels without paid AI calls or production mutations.
