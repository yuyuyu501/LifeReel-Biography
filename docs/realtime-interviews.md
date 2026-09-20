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

Final user transcripts are saved immediately as interview answers. AI replies
are stored separately as questions and never inserted as user answers.
Only final transcripts enter memory extraction; incomplete transcription is
not treated as verified speech. Microphone audio is streamed to the realtime
provider without creating a local recording or a saved media asset. Committed
final transcripts survive process crashes. Existing recordings from earlier
versions remain accessible; new calls leave `source_asset_id` empty.

On hang-up/disconnection, one durable existing interview workflow processes
the saved answers and updates the chapter when enough evidence is present.
Memory/graph compilation and script updates currently run after the call,
not after each spoken turn. They use the application workflow and do not
require model function calling.
It follows the existing script billing policy. Stale calls are recovered after
a 60-second lease, checked every 15 seconds. No reconnect or audio replay occurs
automatically. One simultaneous call is allowed per tenant; calls are bounded
by the configured duration and input rate.

Realtime speech is currently operator-funded. Provider usage receipts are kept
on the call record; they are not charged using unrelated text-token prices.
Set an appropriate quota in the Speech console before enabling public access.

## Release Verification

Use isolated databases and the mock transport for routine tests. Verify origin,
cookie/role/tenant checks, duplicate joins, transcript deduplication, interruption,
mute, disconnect recovery, final-utterance flushing, no audio persistence and
one workflow per call.
Check pending jobs and active `interview_voice_calls` before releasing. Preserve
the database, environment and old runtime images. Apply migration
`20260918_0030`, update API/web runtimes, and verify the TLS WebSocket path.
Actual provider latency, microphone echo behavior and Chinese recognition quality
require a separately authorized live call with configured Speech credentials.
