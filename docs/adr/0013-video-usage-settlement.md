# Video Usage Settlement and Chapter Duration

## Decision

New real video jobs reserve a fixed CNY 24, not a per-second final price.
The current supported tariff is doubao-seedance-2-0-mini-260615, 720p, with
text/still-image input and no reference-video input: CNY 23 per million output
tokens, multiplied by 1.5 for retail (CNY 34.50). The basis is the standard
non-promotional price recorded in ADR 0009:
https://docs.volcengine.com/docs/82379/1544106?lang=zh

Text AI used for video shot planning shares that reservation. Its actual usage
is settled at the existing text tariff, also official cost multiplied by 1.5.
It must not take an extra text hold from a balance made negative by video credit.
Every billable attempt retains its provider receipt. Polling/re-reading the same
task does not charge again. Unknown models/configurations cannot silently use
this tariff; mock/legacy fixed-price jobs retain their existing behavior.

The studio starts directly, without a browser confirmation or the old quote
paragraph. The wallet shows the tariff, reservation, settled debt and ledger.
New generation is disabled when available balance is zero or negative.

## Credit and Accounting

- A new video is allowed when available balance is strictly positive, even if
  the fixed reservation exceeds it. Wallet row locks serialize this check and
  reservation, preventing multiple requests spending the same available funds.
- Keep bonus funds nonnegative. A signed cash balance carries settled debt;
  reserved cash can exceed cash on hand. Other held bonus funds remain covered.
- An already-authorized job may finish with negative availability. At settlement,
  release its hold, debit actual usage once, and retain sub-cent precision in the
  existing nano-CNY carry. Higher actual costs may create additional debt.
- Confirmed recharge credits cash as before, reducing debt before restoring credit.
- A provider-successful segment remains billable even if download, assembly or
  another segment fails. Retrying charges only new provider receipts.
- Officially failed video tasks with no usage are zero-cost. Missing/invalid usage
  on successful tasks, in-flight tasks, and uncertain submissions retain the hold.
  Never infer usage from seconds or silently refund an unknown cloud expense.
- A later complete receipt may replace an incomplete unbilled receipt. Operators
  can reconcile a terminal job with a verified receipt using video_admin; the
  event must belong to that run/tenant and cannot already have been charged.

Examples excluding shot-planning text: 649,800 output tokens cost CNY 22.4181.
A CNY 20 wallet becomes CNY 2.41 debt plus 0.0081 carried for later settlement.
100,000 tokens cost CNY 3.45, returning the unused CNY 20.55 reservation.
1,000,000 tokens cost CNY 34.50, exceeding the reservation by CNY 10.50.

Allowing any positive balance to open a CNY 24 reservation is intentional credit
risk requested by the owner. It is not a payment guarantee or an anti-abuse policy.
The new tariff limits each budget to one chapter of 15-30 seconds. Registration
and payment verification policies remain unchanged.

## Script Duration

The script AI estimates an integer duration from final narration length, pauses,
visual pacing and a natural Mandarin speaking rate, within 15-30 seconds. It
condenses the chapter when necessary instead of forcing long text into 30 seconds.
The backend validates the AI value; it does not substitute a fixed duration for
missing/out-of-range output. Shot durations sum to the chapter duration. Video
planning splits that duration into supported segments while preserving narration.
Existing scripts, videos, quotes and receipts are not rewritten or rebilled.

## Operations and Verification

Apply migration 20260911_0023 before serving the new API. It only relaxes the cash
balance/coverage constraints and does not change balances. Downgrade refuses if
debt/credit holds violate the previous constraints; never erase them to roll back.

Verified provider receipts may be applied by an operator (not a customer API):

```sh
python -m lifereel_api.modules.billing.video_admin \
  --run-id RUN_UUID --event-id EVENT_UUID --receipt verified-receipt.json \
  --operator OPERATOR --reference PROVIDER_RECONCILIATION_REFERENCE
```

Cover fixed holds, one-cent admission, zero/negative rejection, lower/higher cost,
sub-cent carry, failed partial generation, replay/retry, missing and late receipts,
planner usage, actual segmented execution, and migration/concurrency on disposable
PostgreSQL. UI tests verify no confirmation, no old quote text, disabled generation
without funds, and visible settled debt. Do not create a paid production job merely
to check frontend controls.
