# Realtime Interview Calls

The interview page supports continuous microphone input, spoken replies,
server-detected interruption, mute and hang-up. Existing text and recording
interviews remain available. A call locks competing interview submissions.

## Provider Setup

Enable Doubao Speech's full-duplex realtime service, then configure the API
service environment (never commit the real key):

```dotenv
REALTIME_VOICE_PROVIDER=doubao
DOUBAO_REALTIME_API_KEY=<Doubao Speech API key>
DOUBAO_REALTIME_VOICE=zh_female_xiaohe_jupiter_bigtts
REALTIME_VOICE_MAX_SECONDS=900
```

The Speech credential is independent of `VOLCENGINE_API_KEY` used for Seedance.
Restart/recreate the API container after changing its environment.
Without this configuration the call button is unavailable. `mock` is supported
only in development/test, never production.

This integration uses model `1.2.6.1`, JSON WebSocket events at
`wss://openspeech.bytedance.com/api/v3/duplex/realtime/dialogue`, 16 kHz mono
PCM16 input (640 bytes / 20 ms), and explicit 24 kHz `pcm_s16le` output.

Official protocol: <https://www.volcengine.com/docs/6561/2549778>

## Networking

Browser access requires HTTPS (localhost also works) and microphone permission.
`API_CORS_ORIGINS` must contain the exact browser origin, including the scheme
and any non-default port. WebSocket requests validate origin, session cookie,
current account membership, write permission and call ownership. Credentials
are sent upstream only by the API. Browser query strings contain no tokens.

Every reverse proxy must forward WebSocket Upgrade and Connection headers using
HTTP/1.1. The repository web nginx template and Vite proxy support this.
Check the host/TLS proxy too. Allow API egress to `openspeech.bytedance.com:443`.

## Persistence And Costs

Each completed user utterance immediately enters a bounded, connection-local
memory queue. A serial background consumer extracts derived knowledge, invokes
the existing graph/biography compiler, and updates the chapter when enough
evidence is present. Speech input and replies continue independently. Duplicate
ASR event IDs are ignored; AI replies are never compiled as user facts. The most
recent question provides transient context for brief answers. Rewrite requests
use existing knowledge without becoming biographical claims. No model function
calling is required. WebSocket progress events refresh the workspace, graph and
script during the call.

Neither microphone recordings nor transcripts are saved as files or database
conversation history. New calls do not create interview rounds, deferred jobs,
or turn workflows. Their `messages` stays empty, and `source_asset_id`,
`last_round_id` and `workflow_id` stay null. Derived claims retain their person,
chapter and interview-session association, but have no raw `source_quote` or
fabricated source-round/asset link. Existing history from earlier versions is
not deleted by this change. Browser captions hold at most two recent turns,
are never written to browser storage, and are cleared on disconnect.

On hang-up/disconnection the consumer finishes utterances already received;
it does not defer initial processing until hang-up. A heartbeat keeps the call
in `closing` until pending updates finish. Failed updates report a sanitized
error without automatic paid resubmission; later utterances can still proceed.
An API process crash loses pending in-memory utterances; only completed derived
knowledge and scripts survive. Stale recovery closes call metadata without
reconstructing transcripts or scheduling replay. It follows the existing
memory/token and successful-script-update billing policy. Stale calls expire after
a 60-second lease, checked every 15 seconds. No reconnect or audio replay occurs
automatically. One simultaneous call is allowed per tenant; calls are bounded
by the configured duration and input rate.

Realtime speech is currently operator-funded. Provider usage receipts are kept
on the call record; they are not charged using unrelated text-token prices.
Set an appropriate quota in the Speech console before enabling public access.

## Release Verification

Use isolated databases and the mock transport for routine tests. Verify origin,
cookie/role/tenant checks, duplicate joins, transcript deduplication, interruption,
mute, disconnect recovery, final-utterance flushing, updates before hang-up,
responsive audio during slow updates, ordered processing, failure handling,
and absence of persisted audio/transcripts/workflows.
Check pending jobs and active `interview_voice_calls` before releasing. Preserve
the database, environment and old runtime images. Apply migration
`20260918_0030`, update API/web runtimes, and verify the TLS WebSocket path.
Actual provider latency, microphone echo behavior and Chinese recognition quality
require a separately authorized live call with configured Speech credentials.
