# Chapter Readiness and Token Billing

## Decision (2026-09-11)

The user approved retail text pricing at the published provider rate times 1.5.
This replaces the per-successful-chapter fee when `BILLING_TEXT_MODE=tokens`.
Video pricing and local CPU Whisper remain unchanged. Historical charges are not
recalculated. Provider cost is calculated from measured token receipts at the
published standard online tariff, not account discounts or prepaid bundles.

## Chapter Workflow

Memory extraction -> semantic chapter assessment -> conditional script update ->
next interview question. Assessment returns `missing_topics`, `ready_for_script`
and `reason`. Readiness is not inferred from claim count or answer length. A name
alone does not justify inventing a visual story; a concrete memory may suffice
even if other chapter topics remain uncovered.

When not ready, complete the turn normally, retain earlier script content, and
pass the assessment to the interview AI for its next question. Provider outages
and malformed responses remain technical errors; never relabel them as missing
information. Script evidence references remain mandatory.

## Published Tariff

Source checked 2026-09-11:
https://docs.volcengine.com/docs/82379/1544106?lang=zh

Explicit supported model: `doubao-seed-character-260628` at
`https://ark.cn-beijing.volces.com/api/v3`.

| Input length | Input CNY / million | Output CNY / million | Cached input CNY / million |
| --- | --- | --- | --- |
| 0-32,000 | 0.80 | 2.00 | 0.16 |
| 32,001-128,000 | 1.20 | 6.00 | 0.16 |

The tier applies to the whole request, not progressive bands. Retail rates are
1.20/3.00/0.24 and 1.80/9.00/0.24 respectively. 1.5x cost is a 50% markup and
33.3% gross margin before infrastructure, support and unrecovered error costs.

Cost = ((prompt_tokens - cached_tokens) * input_rate + cached_tokens * cache_rate
+ completion_tokens * output_rate) / 1,000,000. Reasoning tokens are already in
completion_tokens and must not be added again. Explicit cache storage and audio
token pricing are not supported by this tariff. Local ASR has no provider token
receipt and must not be assigned fabricated tokens.

## Accounting

- Each application-owned chat/vision call reserves CNY 0.40 before network I/O.
  Output is capped at 8,192 tokens. This covers the highest supported tariff's
  128,000 input tokens plus that output cap (CNY 0.304128 retail).
- Persist original usage, request ID, model, operation and root workflow reference
  independently of business transactions. A model call can succeed even when the
  resulting script fails validation. Such real consumption remains billable.
- Release the budget and settle verified receipts atomically, using a serialized
  wallet lock. Repeated receipts do not charge again. A genuine new provider call
  has separate usage even when it retries the same workflow.
- Use integer nano-CNY (1e-9 CNY). Carry sub-cent remainder across calls. Debit whole
  cents only; do not round every small call up to one cent. Snapshot rates per receipt.
- Missing/invalid receipts remain `pending` with the budget held for reconciliation;
  do not estimate zero or bill guessed tokens. HTTP rejection (400/401/403/404/413/
  422/429) without usage releases the budget; ambiguous server errors and timeouts
  do not. A valid usage receipt on any HTTP response is still settled.
- Settlement runs in a savepoint so accounting errors retain the original receipt.
  Persistence failures retain the hold and emit an error in server logs. A crash
  after reservation may leave a hold without a receipt. Pending holds, or unresolved
  holds older than five minutes, block new calls for that wallet before network I/O.
- Operator reconciliation is available via `token_admin` below. No automatic
  provider-bill import is implemented. It requires verified provider evidence,
  records operator/reference/time, and cannot modify already resolved charges.
  Never release a hold merely because it is old or invent usage to settle it.
- Zero-price script charges remain internal idempotency markers and produce no
  wallet ledger noise. Retrying a released legacy script charge in token mode does
  not also collect the old chapter fee. Settled legacy results are preserved.

## Deployment and Verification

Run migration `20260911_0022` before the new API starts. Enable token mode only when
all text model configuration points to the supported Ark endpoint/model. Unknown
models are rejected before billable requests. Deploy the matching Web build so
the old "failed scripts are free" notice is replaced before accepting new calls.

Do not migrate billing by editing balance values or deleting old ledger entries.
Restore the prior billing mode for rollback without dropping usage/remainder data.
Tests must cover insufficient information, retained old scripts, exact tier/cache
arithmetic, sub-cent carry, duplicate receipts, missing usage, insufficient funds,
and provider success followed by business validation failure. No live generation
of a user's biography is required for these regressions.

## Operator Reconciliation

Run inside the API container using `docker compose -f compose.production.yaml exec api`:

```bash
python -m lifereel_api.modules.billing.token_admin list
python -m lifereel_api.modules.billing.token_admin settle --hold-id UUID --operator NAME --reference PROVIDER_TICKET --receipt /tmp/verified-receipt.json
python -m lifereel_api.modules.billing.token_admin release --hold-id UUID --operator NAME --reference PROVIDER_TICKET --confirmed-no-charge
```

The verified receipt contains `id` (provider request ID) and the provider's original
`usage` object. This is an administrative command, not a public HTTP endpoint.
`release` refuses receipts with nonempty usage; use verified settlement instead.
Short-lived in-flight holds cannot be reconciled, avoiding a race with live requests.
Monitor the oldest unresolved hold and server reconciliation errors. A wallet remains
paused until its uncertain receipts are reconciled, so failures cannot silently
generate unlimited unbilled model calls. Sub-cent carry is not a pending error.
