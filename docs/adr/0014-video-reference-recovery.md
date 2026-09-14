# Video Reference Rejection Recovery

The September 14 production failure was an input-image moderation rejection,
not a connection failure. The first 15-second clip completed and was billed;
the platform rejected the previous clip's last frame as the next reference.

## Changes

- Map input-image moderation to `VIDEO_REFERENCE_REJECTED`, other content
  moderation to `VIDEO_CONTENT_REJECTED`. Keep Chinese copy in the frontend.
- Project legacy failures from their saved provider code without rewriting
  historical jobs, usage receipts, balances or finished segments.
- Block unchanged moderation retries in both the job retry and execute paths,
  before taking a new wallet hold. Never automatically remove the reference,
  switch providers or repeatedly submit rejected content.
- Offer an inline, explicit replacement from the same person's image assets.
  Only ready JPEG/PNG/WebP files up to 10 MiB are eligible. Validate tenant,
  person, type, size, prior rejection IDs and file hashes on the server.
  Replacement images still undergo the provider's normal moderation.
- Keep replacement history and failed-reference hashes in the manifest. Use the
  production execution lock for validation, reference update and retry transition.
  A failed balance check rolls back the replacement too.
- Continue only unfinished segments using the frozen script/plan; do not recreate
  completed clips or rebill their receipts. No automatic paid production retry
  is part of this release.
- Allow private preview of completed segments even while the full chapter is
  incomplete. Check tenant ownership and the exact per-run storage key. Partial
  output is not a published chapter and cannot use the publish action.
- Refresh wallet and ledger queries on terminal production updates, including
  failures, instead of leaving controls disabled until the next 10-second poll.

## Verification

Provider tests cover submission and terminal moderation mapping. Pipeline tests
cover legacy projection, no-reserve rejection, tenant/person isolation, invalid
or repeated reference files, atomic insufficient-balance handling, partial
preview, checkpoint preservation, continued generation and exactly-once billing.
UI tests cover inline replacement, image preview, no blind retry or confirmation
dialog, empty asset lists and immediate terminal-state wallet refresh.

No schema migration is required. Deploy the same Git revision for API and web;
do not reset the existing failed production run or its already-settled charge.
