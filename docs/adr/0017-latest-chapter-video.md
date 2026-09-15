# Latest chapter video retention

The studio has no generation-history selector. It follows the newest task for
the selected chapter, ordered by creation time, including pending/failed tasks.
An older successful video is not presented as the result of a new failed task.

After a new render and billing settlement commit, a durable production.cleanup
job runs in the existing database-backed video lane. For each chapter it keeps
the most recently created successful render and retires older terminal runs.
Newer failed/running attempts do not trigger deletion of the last successful
video. Chapter IDs in snapshots survive regenerated scene IDs. Ambiguous legacy
whole-book renders are excluded rather than assigned to a guessed chapter.

Retirement first records a pending file list and withdraws old publications.
Then it deletes the old final assets, segment videos and saved provider tails
from that run's exact LifeReel-Biography/generated/{tenant}/{run}/ directory.
Source uploads, other chapters, billing events, jobs and script snapshots remain.
Old assets and retries are blocked after retirement. Deleted files cannot be
restored by reverting application code or restoring database metadata.

Storage errors leave the cleanup pending and retry with bounded backoff, without
changing the successful render or billing again. Deferred maintenance must not
reserve the video lane during its wait. Internal cleanup jobs are not shown in
the user's task list. Existing runs can be reconciled by scheduling the same
idempotent cleanup jobs after reviewing their file inventory.
