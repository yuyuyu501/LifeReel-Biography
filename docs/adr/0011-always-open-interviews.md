# Always-Open Chapter Conversations

## Decision

Chapter conversations remain available indefinitely. Remove interview lifecycle
badges and pause/resume/complete controls from the chapter list and workspace.
The composer is always rendered, including when a legacy record is paused or
completed, or while the previous AI workflow is processing. The current chapter
title remains in the conversation heading.

The old pause/resume/complete HTTP endpoints and frontend client functions are
removed. Persisted `status` and `completed_at` fields remain for historical data
compatibility only; they no longer gate conversation entry or new messages.
No historical messages, scripts, files, or timestamps are deleted or rewritten.

## Continuation and Safety

`POST /interviews/{id}/turns` accepts an optional `round_id`. With an explicit ID,
the existing tenant/session scope and answer-overwrite checks remain. Without an
ID, reuse the latest unanswered question, or append a new user-initiated round
with an empty question. Never fabricate an AI question just to reopen a chat.
The frontend omits empty question bubbles.

Serialize submissions on the interview row. Repeated idempotency keys return the
same workflow; a key from another session cannot expose or reuse its workflow.
While the latest workflow is queued/running/failed, keep the input visible but
require that workflow to finish or be retried before sending another message.
These execution/error states remain necessary and are distinct from the removed
interview lifecycle. They protect messages, chapter updates, and token accounting.

Opening or viewing an old interview does not itself invoke AI or charge tokens.
New submitted messages still use semantic readiness assessment and the existing
token-billing pipeline. Video production remains based on saved chapter scripts,
not on whether an interview has been marked completed.

## Verification

Cover legacy paused/completed records with both unanswered and fully answered
last rounds, duplicate submissions, busy workflows, persistent composer visibility,
material controls, and mobile pane switching. Use synthetic data for browser tests;
do not replay or bill a real user's interview merely to validate this UI change.
