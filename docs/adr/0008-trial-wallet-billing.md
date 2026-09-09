# ADR 0008: Trial Wallet And Billing

Date: 2026-09-09

## Scope

Wallet ownership follows the existing family tenant. One welcome grant of CNY 20
is initialized per family; existing test families get the same one-time grant.
Historical completed jobs are not charged retroactively. Paid balance and bonus
credit are separate; bonus is consumed first and cannot be withdrawn.

Current prices are configuration, not client input. Cost assumptions and the
standard-rate decision are documented in [ADR 0009](0009-standard-ai-pricing.md).

- Video: 80 cents per requested second (30 seconds = CNY 24). Model frame rounding
  does not increase the quote. Legacy single-clip mode uses its clip duration.
- Script: 199 cents per chapter per successful generation/update, including automatic
  interview updates. A new update of the same chapter is another charge. Multiple
  chapters are billed separately; a two-chapter update is 398 cents. This supersedes
  the initial first-success-only interpretation, corrected by the user on this date.
- Registration is disabled by default. When enabled for controlled tests, account,
  family, default chapters, wallet and welcome grant are created atomically.
- Actual recharge is disabled, both in the UI and API. No QR code, mock crediting,
  payment callback or client-confirmed settlement exists yet.

## Accounting

All wallet amounts are integer CNY cents. Wallet rows are serialized through a
tenant row lock; database constraints forbid negative or uncovered balances.
Charge uniqueness is `(tenant_id, business_key)`. Ledger entries are append-only
through the service and uniquely identify a charge attempt and transition.

`reserve -> settled` deducts the original split from bonus/paid balances.
`reserve -> released` restores availability without claiming a cash refund.
Retries re-reserve the original price; duplicate requests/settlements do not charge
again. Debiting and publishing a successful result commit in the same transaction.
Failed work releases the reservation. Worker failure reporting cannot release a
video reservation while its execution lock is still held.

Scripts use `script-update:{request_uuid}:{chapter_uuid_or_free}` business keys,
not transient scene IDs. The person's book is execution-locked, and the tenant is
locked before checking update receipts. Request payload fingerprints reject reuse
of an ID for a different request. Settled receipts return the current saved book
without another AI invocation; they are not historical script snapshots.

The frontend keeps an update UUID across in-place retries and allocates a new one
after success or a changed request. API callers should supply `idempotency_key`;
omitting it treats each request as a new update. A page reload discards an unfinished
manual form request ID, so check saved results before submitting anew. Interview
updates use the persisted workflow UUID, including across worker retries/restarts.
A generated script remains chargeable if a subsequent follow-up fails: the script
itself succeeded. Retrying that workflow reuses the script, with no extra charge.
Retries retain their original chapter set and prices; if the set changed after a
failed multi-chapter update, the old request is rejected rather than silently rebilled.
Old first-success charges remain in the ledger; no historical updates are backbilled.

Interview processing now reserves the same script-update charge before asset
analysis, memory extraction, graph, biography and gap analysis. Insufficient funds
stop the workflow before any of these AI calls. Preprocessing failure or a turn
without a generated script releases the reservation. Script settlement retains
the existing behavior when a later follow-up fails. This is not a token cost cap.

## Cost Measurement

LLM/vision and remote ASR responses record model, provider usage, operation, request
ID, elapsed time and success/failure. No prompt, response content, credential or
uploaded document is stored in this usage log. Seedance submissions and terminal
success/failure receipts retain task IDs for reconciliation. Successful receipts
record returned usage, duration and parameters; duplicate task receipt reads are
deduplicated. Submission parameters are not measured usage. A failed HTTP request
without usage remains unknown, not zero cost; a submission with no terminal receipt
must be checked against the cloud task and invoice, not assumed free.

Customer charges and supplier costs are separate. Provider invoices remain the
source of truth; token counts are not a monetary bill. Local Whisper compute,
storage/bandwidth, unreturned usage, cloud task failures and missing receipts must
be reconciled before pricing is made public. The wallet UI exposes model use for
controlled testing, without pretending it is an exact supplier expense total.

## Configuration

- `REGISTRATION_ENABLED=false`
- `BILLING_PRICE_VERSION=standard-2026-09-luna20`
- `BILLING_WELCOME_BONUS_CENTS=2000`
- `BILLING_VIDEO_CENTS_PER_SECOND=80`
- `BILLING_SCRIPT_CHAPTER_CENTS=40`

Changes apply to new charges only; retries keep saved quotes. Updating the welcome
amount does not replenish already-created wallets. Recharge is intentionally not
enabled by an environment switch.

## Before Public Launch

1. Reconcile real token/video invoices against usage and failure/retry rates; set
   sustainable chapter limits and final prices.
2. Add verified registration, invitation/rate/concurrency controls, abuse detection,
   promotional-credit limits and auditable recovery workflows.
3. Integrate a WeChat merchant order API and verified, idempotent payment notifications.
   A static collection QR and a user pressing "paid" are insufficient for automatic
   wallet credit. Check merchant, app, amount, currency and order before crediting.
4. Add payment reconciliation, refunds, applicable terms and operational alerts.
5. Replace the existing non-acknowledged Redis queue with durable task delivery and
   reservation reconciliation. A process crash can currently leave credit frozen;
   do not expire it blindly while a paid cloud task might still finish.

This iteration is suitable for controlled testing, not an open payment launch.

## Supplier Price Observation

The user's Seedance 2.0 mini 260615 screenshot lists CNY 5.6 per million tokens
with video input, and CNY 9.2 without video input. The current pipeline submits
text and optionally a still image, not reference video, so the latter rate applies
subject to the provider's billing terms. Two existing 15-second tasks returned
324,900 tokens each on a read-only cloud status query (649,800 total). At 9.2 per
million, their combined video generation estimate is CNY 5.97816. At a CNY 6 retail
price, only CNY 0.02184 remains before planning, retries, hosting, storage, fees and
taxes. This is not a confirmed net profit or invoice. Do not use the cheaper video
input rate simply because the output is video or a reference image was supplied.

This historical discount observation does not set current prices. ADR 0009 uses
the standard, undiscounted rate instead. The rates are not automatically enabled
supplier billing or reconciliation logic.

## Verification (2026-09-09)

- Backend full regression after per-update correction: 77 passed (isolated SQLite
  on tmpfs; all AI/media mocked). Covers distinct updates, same-ID replays, original
  retry price, insufficient balance, per-chapter bulk charges and follow-up failure.
- Frontend: 34 passed; TypeScript and Vite production build passed. Includes stable
  update IDs on in-place retry and a new ID for the next successful generation.
- Ruff passed for API source/tests and migration 0019. Older migration 0012 still
  has three pre-existing line-length warnings when linting all migration history.
- Disposable PostgreSQL: migrations through 0019, concurrent first wallet access,
  duplicate reservations, overspend prevention and duplicate settlement passed.
  The disposable database and superseded slow test container were removed; no
  application data was deleted.
- Failure coverage includes generation/provider failure, result-save rollback,
  retry enqueue failure, active-run locks and cancellation of the browser quote.
- Live additive migration is at 0019. Authenticated HTTP smoke passed: CNY 20
  available, zero frozen, one welcome entry, rejected fake recharge, registration
  disabled, existing completed video preserved without retrospective charge.
- Desktop browser confirmed wallet balance, one welcome entry, price notice,
  disabled recharge, ledger filter and usage empty state. At mobile width, review
  identified the hidden wallet link; a top-bar wallet shortcut and two-column
  small-screen recharge selector were added and frontend regression rerun.
- Final browser reload on localhost encountered a host IPv6 loopback timeout:
  curl -4 succeeds, curl -6 times out. IPv4 HTTP smoke is green. Use
  http://127.0.0.1:5173/wallet temporarily (requires a separate login cookie).
  Final mobile visual recheck of the shortcut awaits that login; no system DNS,
  hosts or firewall configuration was changed.
- No new paid model or video calls were made for wallet verification. Live usage
  is empty until new generation calls occur; later supplier invoice comparison
  is still required before asserting profitability or enabling real payments.
