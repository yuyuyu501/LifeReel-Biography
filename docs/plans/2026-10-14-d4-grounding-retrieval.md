# D4 Grounding And Retrieval Experiment

Frozen before provider calls, 2026-10-14. Baseline: `2b0a5ed`, tag
`d4-baseline-20261014`. The existing acceptance standard remains unchanged.

## Factors

| Group | D4 complete Sol review | Concise evidence support checks | Person-scoped retrieval |
| --- | --- | --- | --- |
| baseline | yes | no | no |
| reasoning | yes | yes | no |
| retrieval | yes | no | yes |
| combined | yes | yes | yes |

The reasoning factor changes the review prompt and output contract together.
It is application-level structured verification, not proof of hidden reasoning
or an experiment on a provider reasoning-effort parameter. Lite thinking remains
disabled for the main comparison. No scratch chain of thought is requested.

Retrieval uses SQL person/tenant filters, current entries, exact lexical matches
and adjacent original answers. No embedding API, local embedding model, vector
index or extra infrastructure is introduced in this first comparison. This tests
structured retrieval augmentation; it cannot establish vector RAG quality.

Retrieved originals are past statements, not authoritative current values.
Current entries retain corrections, confidence, privacy and version metadata.
Only current answer versions are queried. Evidence windows retain source offsets.
Retrieval augments, rather than replaces, D4's existing recent context and review.
Bounds and truncation are reported; unmatched history can still be missed.

## Evaluation

Freeze synthetic disclosures, target atoms and necessary evidence before calling
providers. Never send gold or hidden persona to the tested interview models.
Compare all four groups with identical models, timeouts and source material.
Record every request, failure, elapsed time, usage and program fallback. Do not
automatically retry uncertain calls. Semantic matches and evidence sufficiency
require review; keyword matches and the support model's verdict are not scores.

Use a fixed-disclosure recording track and a separate unseen-person interviewing
track. Inspect every saved atom and every question. Program replacement replies
do not count as successful interviewing. A small experiment does not certify all
67 fields, completion rate or production concurrency. Add local persistence
checks for corrections, privacy, resume and person isolation.

## Release Boundary

`INTERVIEW_D4_ENHANCEMENT=baseline` is the default. Experiments run locally with
synthetic people and isolated databases. Do not change the production default
or deploy an experimental treatment before local comparison and acceptance.
Preserve the baseline tag and previous receipts. A negative result is recorded,
not silently converted into a successful release.

## Hardware Observation

Read-only SSH observation on 2026-10-14: 8 vCPU, 14.96 GiB RAM,
about 12.95 GiB available, about 62.02 GiB free disk, no compute GPU found,
16 healthy containers. PostgreSQL 16.15 has pgvector 0.8.6 extension files,
but vector is not enabled in the application database. These observations are
not a concurrent-load benchmark; service memory limits still apply.

## Execution Appendix

The two frozen provider runs and the reviewed fixed-track scores are reported in
`docs/reports/2026-10-14-d4-grounding-retrieval.md`. V2 completed all 32 recording
cases. Baseline and combined completed 14 interview turns each; reasoning and
retrieval stopped after 4 and 2 turns under the predeclared failure rule. No full
interview acceptance or vector RAG validation is claimed.

After the provider runs ended, `d4-profile-20261014-v2` corrected empty control
replies and inactive pending questions. Five cached responses passed an offline
protocol replay without live calls; the original scores remain unchanged.
This patched runtime has narrow persistence regression coverage but has not
completed a new live four-group comparison. Experimental production defaults
remain disabled. Continue with field routing, refinement-versus-conflict,
deduplication and a better answering protocol before choosing a release.
