# ADR 0009: Standard-Rate AI Pricing

Date: 2026-09-09

## Decision

- Script: CNY 0.40 per chapter per successful generation/update, including automatic
  interview updates. The price bundles interview follow-up, gap analysis, memory
  extraction, relationships/timeline/knowledge graph, biography and asset understanding.
- Video: CNY 0.80 per requested second; 30 seconds = CNY 24.
- Price version: `standard-2026-09-luna20`.
- Existing receipts and retries retain their original quotes. No historical
  charges, balances or welcome grants are rewritten. Viewing saved data is free.
- The CNY 20 welcome grant remains unchanged. It funds ten script updates, but
  does not cover a 30-second video at the new price. Recharge remains unavailable;
  do not add artificial funding or claim payment is available to bypass this.

## Rate Basis

The user supplied GPT-5.6-Luna input USD 1.00 / million tokens and output USD
6.00 / million tokens, then specified that the post-July price is 20% of that
baseline. This is the authoritative planning rate for this version. It is
user-supplied, not a claim of independent verification of OpenAI pricing.
Use no cache, reseller or promotional discount. Use CNY 7.50 / USD as a planning
exchange rate, not a live exchange quote. Therefore effective input costs CNY 1.50 /
million tokens and output costs CNY 9.00 / million tokens. Reasoning tokens, when billed
as output, must be included in the output budget, not treated as free.

Seedance 2.0 mini, 720p, no reference-video input: standard CNY 23 / million
completion tokens. Source: https://docs.volcengine.com/docs/82379/1544106?lang=zh
Text and optional still-image input do not qualify as video input. Ignore the
temporary 40% promotional price. Native audio is part of this video model flow;
there is no separate active cloud TTS generation call in the current pipeline.

## Text-Workflow Budget

These are engineering planning assumptions, NOT measured averages or enforced
limits. Context lengths differ by family, source length and chapter. Normal text
turns invoke six model operations; files and recovery can increase that count.

| Operation | Input tokens | Output tokens | CNY |
| --- | ---: | ---: | ---: |
| Extract new memory facts | 2,000 | 600 | 0.0084 |
| Entities, relationships, timeline and conflicts | 12,000 | 2,500 | 0.0405 |
| Biography/profile update | 7,000 | 1,000 | 0.0195 |
| Missing-information analysis | 12,000 | 300 | 0.0207 |
| Chapter screenplay and shots | 14,000 | 3,500 | 0.0525 |
| Interview follow-up | 6,000 | 300 | 0.0117 |
| Typical-turn subtotal | 53,000 | 8,200 | 0.1533 |
| Average allocation for asset understanding / extra facts | 4,000 | 1,000 | 0.0150 |
| Total model allowance | 57,000 | 9,200 | 0.1683 |

Why these estimates: graph/gap/script contexts currently carry up to 40 memories,
biography up to 20, gap analysis up to 12 rounds, and follow-up up to six answered
rounds. Memory inputs include source quotes. This repeats context across operations.
The 2,500/3,500 output budgets account for structured graph data and shot lists,
not just the short narration visible in the UI.

Asset allowance covers image/selected video-frame understanding and additional
fact extraction from source material. It is an amortized allowance, not a limit
or a claim that arbitrary file batches cost 0.075. Audio transcription currently
uses local faster-whisper small; document parsing and video-frame extraction are
local as well. Their compute and storage costs belong to the non-model allowance.

Add 25% of model cost for retry/recovery, opening questions, standalone legacy
memory/follow-up actions and non-converting/no-script turns; add CNY 0.08 for local
ASR/parsing/compute/storage allocation. Both are assumptions, not measured fees.

| Scenario | Aggregate input/output tokens | Model CNY | Budget incl. 25% + 0.08 | Margin at 0.40 |
| --- | --- | ---: | ---: | ---: |
| Short context | 10,000 / 2,500 | 0.0375 | 0.126875 | 68.3% |
| Typical context plus asset allocation | 57,000 / 9,200 | 0.1683 | 0.290375 | 27.4% |
| Long context / more material | 100,000 / 16,000 | 0.2940 | 0.447500 | -11.9% |

Formula: `(input_tokens * 1 + output_tokens * 6) / 1_000_000 * 7.50 * 0.2`.
The typical scenario is the planning mean, not a statistically estimated mean.
Do not present these values as supplier receipts. CNY 0.40 is the chosen flat rate
for normal use and has a calculated allowance margin; long contexts or large
material batches can still exceed it and need limits or a future tiered price.

## Video Budget

Two previously completed 15-second tasks returned 324,900 completion tokens each.
Using their existing receipts, with no new paid test:

- Standard model cost: `649800 / 1000000 * 23 = CNY 14.9454` for 30 seconds.
- Retail: CNY 24, leaving CNY 9.0546, or 37.7%, before other costs.
- Example planning allowance: 20% extra model expense for successful segments
  needing replacement / failed delivery, plus CNY 0.50 per 30 seconds for LLM
  shot planning, transcoding, storage and delivery. Budget: CNY 18.43448, leaving
  CNY 5.56552 (23.2%). These allowances are not measured service costs.
- Officially failed generation tasks are not charged by the video provider;
  successfully generated segments may still incur cost if the overall job fails.
- Planning currently allows up to three LLM attempts. Video planning is allocated
  to the video price, not charged again as a chapter script update.

The sample is specific to the current model, resolution, aspect ratio and input
mode. Reprice if these change. A cheap video-input token rate does not imply a
cheaper total task, because reference-video duration also contributes tokens.

## Accounting And Limits

An interview workflow now pre-reserves the same chapter-update charge before all
AI preprocessing. Script generation reuses and settles this reservation. A failed
preprocessing step releases it; retry uses the original quote. No-script turns
release it. A successful saved script followed by a failed question remains billed,
and retry does not regenerate or charge that script again.

No fixed price guarantees every possible request is profitable. Current prompts
have item-count limits but no aggregate token-cost cap, and user retries / legacy
standalone AI endpoints are not fully metered as separate customer products.
Very long source quotes, batches, repeated free failures and local ASR can exceed
the budget. This change adds no silent truncation, hidden surcharge, new supplier
calls, or a false guarantee of unlimited profitable usage. Strict per-task cost
ceilings, retry/rate limits and durable billing recovery remain launch prerequisites.

Welcome credit is marketing spend, not revenue. Its use creates real supplier
expense. Cash payment fees, taxes, fixed operating costs, abuse and promotional
subsidies are not netted out of the margins above. Registration/recharge remain
closed; this tariff update is not a production payment launch.

## Verification

Use offline/mocked regressions, not paid generations, to verify the new price
catalogue, manual/automatic updates, multi-chapter charging, reservations before
AI, failure release, replay and old-price retry behavior. Check the live wallet
response and the existing frontend without altering user balances or data.

Completed verification:

- Isolated container/tmpfs backend regression: 84 passed, including seven new
  standard-tariff tests. Existing lifecycle tests explicitly retain the original
  tariff as compatibility fixtures; new tests verify production defaults.
- Frontend: 34 passed; TypeScript and Vite production build passed.
- Ruff passed for changed Python modules/tests; diff whitespace check passed.
- API/web containers rebuilt and restarted after confirming zero active jobs.
- Live wallet HTTP 200 and browser both show CNY 0.40/update and CNY 0.80/second.
  Existing balance remains CNY 20, frozen balance zero, ledger one welcome entry.
- No paid generations, recharge, historical rebilling or user data deletion.
