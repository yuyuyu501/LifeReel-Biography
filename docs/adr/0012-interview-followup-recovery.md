# Interview Follow-Up Recovery

## Context

The first-chapter production test completed memory and script processing but
failed at the final interview reply with INTERVIEW_LLM_RESPONSE_INVALID. The
provider returned successful HTTP responses and reported one output token on
the failing requests. Raw content was not retained, so the exact response is
unknown. Re-running the workflow unnecessarily repeated memory enrichment and
chapter assessment.

## Decision

- Keep the reply scoped to the selected chapter. When information is complete
  or the user wishes to stop, allow an AI-written acknowledgement instead of
  forcing a further question. This never closes or locks the conversation.
- Require a nonempty next_question string and one supported intent. Reject
  empty, malformed, non-string, overlong, or exactly repeated replies.
- Allow one corrective retry for invalid JSON or reply structure. If it still
  fails, return the existing error code. Do not fabricate a scripted reply.
  Transport, configuration, and billing errors retain their existing behavior.
- Classify non-text JSON message content as a JSON decoding failure, including
  null content. Keep the provider receipt and actual usage for every attempt.
- Commit the completed memory, assessment, and script references to script_brief
  with followup_ready before requesting the reply. Retries from this checkpoint
  only request the missing reply. This also applies when information is not yet
  sufficient for a script. Legacy workflows without a checkpoint follow the
  existing pipeline once and preserve script idempotency.
- Save the reply round and workflow completion in the same database transaction.
  Completed workflow replays do not append another reply. Older workflows cannot
  be retried after a newer turn has been submitted.

## Verification

Regression coverage includes natural closing replies, malformed and empty JSON,
null message content, invalid intents, a bounded retry, honest provider errors,
actual token settlement for both attempts, and checkpoint recovery both with
and without a generated script. Recovery must preserve memory claims, script
content, and settled charges. Repeated completion must not create extra rounds.

Deploy the tested local Git commit by fast-forwarding the server repository.
Validate the latest failed synthetic Lin interview through its existing retry
control. Do not delete test history or rewrite wallet records to hide failures.
