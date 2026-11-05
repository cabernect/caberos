# Speech Input And Output

Status: included in v0.2.1 scope; implementation pending. Supersedes the earlier
W6 speech deferral, not the implemented image tool contract.

## Product Decisions

Two independent user actions, not agent-callable tools:

- **Dictation (STT):** microphone button in the composer -> record -> stop ->
  transcribe -> review/edit the draft -> normal Submit.
- **Read Aloud (TTS):** speaker icon beneath a completed agent message, next to
  Copy and before the usage text -> generate/play speech -> stop.

Typing/submitting text works without either configured service. A spoken input
does not require spoken output, and a typed input can receive read-aloud output.
No automatic sending, always-listening microphone, or unsolicited playback.

Future **Voice Mode** is realtime two-way spoken interaction, including spoken
instructions, normal agent tool execution, questions, and interruption. It is
explicitly out of v0.2.1 scope. Native speech-to-speech versus a streaming
STT -> agent -> TTS pipeline remains a future architecture decision.

## Configuration And Provider Coverage

Settings -> Tools has separate Speech to Text and Text to Speech cards. Each
owns its backend/connection, masked API-key entry, supported model identifier
when required, options, Save, explicit Test, and readiness. Reuse the encrypted
Provider storage/encryption seam from [W9](09-search-services.md), with inline
Tools configuration rather than a separate connection store; do not require
dedicated speech services to masquerade as chat-model providers.

- Provider scope includes ElevenLabs, Deepgram, and Gradium, alongside compatible
  existing LLM providers. Maintain a per-operation support matrix; do not assume
  a service supports both STT and TTS, every model, or every audio format.
- Before adapter work, verify official endpoints, auth, request/response shapes,
  languages, voices, formats, limits, and usage evidence. Select one verified
  STT and one verified TTS adapter for the first vertical slices, then complete
  supported operations for the named speech services before claiming coverage.
- No requirement to route all audio through LiteLLM. Use provider-specific
  transports where necessary; keep them behind small operation-specific adapters.
- Existing LLM-provider credentials may be explicitly referenced where compatible;
  do not copy secrets into plain options or silently change the chat provider.
- Keep TTS voice/model/format and STT model/language settings independent.
  Fetching voice/model lists and connection tests require explicit actions;
  settings load/save must not initiate provider requests.
- Missing catalog prices or reported usage do not block speech support. Missing
  transport support does. Never invent catalog rates or claim unknown cost is zero.
- No cloning, speaker enrollment, uploaded reference voices, arbitrary endpoints,
  automatic dependency/model downloads, or local-engine installs in this slice.

## Dictation Interaction

1. Request microphone access only after the user presses Record. Explain the
   configured remote transcription destination before upload; browser microphone
   permission alone is not remote-processing consent.
2. Show recording state, elapsed time, Stop, and Cancel. Stop microphone tracks
   on stop, cancel, unmount, navigation, or session/agent switch.
3. Initially support bounded record-then-upload, not realtime transcription.
   Detect supported browser/WebView recording MIME formats and adapter input
   formats; reject incompatibility clearly rather than installing a transcoder.
4. Stop triggers transcription only after remote-processing consent. Cancel
   before upload makes zero provider calls. In-flight cancellation stops waiting
   where possible, but does not promise the provider avoided processing/billing.
5. Insert the transcript into an editable draft; never submit it automatically.
   Empty/silent or failed recordings preserve the existing draft.
6. Bind the result to the originating agent/session and draft revision. Late
   responses must not overwrite intervening typing, another session, or a
   submitted message. Offer explicit insertion/recovery when the draft changed.
7. Retain no raw recording by default: release client blobs and server temporary
   files on success/failure/cancel. The submitted transcript becomes ordinary
   user text only after Submit. Retaining source audio is separate future scope.

Proposed initial ceilings: 60 seconds and 15 MiB per recording, one active
transcription per composer, and a bounded transcript length. Enforce byte/time
limits server-side as well as in UI; finalize transcript and request-time limits
against verified provider contracts before enabling adapters.

## Read Aloud Interaction And Speech Rendering

- Render a speaker action only for supported, configured speech output on
  completed assistant messages with speakable text. Keep Copy independent.
  Explain unavailable configuration without a dead, apparently working button.
- Read from the persisted, authorized message ID, not arbitrary client-supplied
  transcript HTML. Loading old messages or scrolling must not generate audio.
- Render the speakable text deterministically: strip Markdown syntax; speak link
  labels rather than URLs; preserve prose, list order, questions, and warnings.
  Omit code blocks, raw HTML, tool payloads, and tables with an honest indication
  that omitted material remains in chat. Do not narrate raw Markdown or JSON.
- Preserve inline code used in prose where sensible. Never execute/fetch linked
  content or use image bytes/URLs as speech input. A message with no speakable
  prose offers no read-aloud request.
- This slice adds no hidden summarization/paraphrasing model call. Show that
  formatted/nonprose content can be omitted; retain the original message intact.
- Button states: idle, generating, playing, stopped, failed. First explicit click
  requests speech and starts playback when ready; if browser autoplay protection
  blocks delayed playback, show a Play action. Stop releases playback promptly.
- One playback at a time. Switching messages stops previous audio; navigation
  stops playback and revokes object URLs. Stopping speech never cancels agent work.
- Reuse authenticated blob playback and audio preview infrastructure, not a raw
  bearer-protected API URL in `<audio src>`. Do not expose provider media URLs.
- Reuse validated generated audio for repeat playback using message/content hash,
  speech-renderer version, and frozen connection/model/voice/options revision.
  Do not share cached speech across unauthorized sessions or agents.

Proposed initial ceilings: 10,000 speakable characters and 20 MiB output, with
bounded total request/playback duration. Reject oversized requests before paid
dispatch, without silently truncating the answer. Finalize durations/formats
against adapter evidence.

## Backend, Authority, And Persistence

Add authenticated operator speech endpoints that delegate to one shared speech
service for access checks, readiness, frozen configuration, consent, bounds,
cancellation, and accounting. Do not register `media_speak`, `audio_transcribe`,
or other loadable agent tools for these UI actions.

This is a deliberate operator-action boundary, not a bypass for agent execution:
browser cookie/bearer auth, applicable CSRF protection, scoped message/session
authorization, rate limits, explicit egress consent, and redacted audit records
are mandatory. If agent-callable speech is added later, it must cross syscall
mediation and its grants/approval gates separately.

- Freeze operation/provider/options at request admission. Secret rotation,
  removal, or binding edits must never redirect an admitted operation silently.
- For TTS, publish validated audio via the existing trusted binary artifact path
  into the source session's pinned workspace, with source message and request
  provenance. No fabricated run/tool-call ID; run ownership can be null.
  Preserve original workspace pins and enforce artifact access on every read.
- Audio reuse must verify retained artifact bytes/revision, not only a cache key.
  No automatic regeneration on missing bytes or changed options.
- Validate actual audio format, MIME, and byte limits; never trust filename alone.
  Clean only newly owned staging bytes on failure; preserve real provider receipts
  when artifact publication fails.
- STT temporary inputs are not workspace attachments by default. Request metadata
  may be retained for audit; do not store raw audio or transcript bodies in logs.

## Accounting And Failure Semantics

One `model_calls` record per actual STT/TTS provider attempt, with operation,
request ID, provider/model, connection revision, latency, outcome, and available
agent/session/message correlation. Pre-submission dictation may have no session
or run; do not manufacture either. Replaying retained audio makes no model call.

Use typed units (audio seconds, text characters, provider-reported tokens/credits)
without overloading token columns. Distinguish locally measured, provider-reported,
and estimated values. Unknown price or usage remains unknown. Extend spend/trace
projections and redaction for non-run speech calls; do not double-count run totals.
No automatic retries or provider fallback after potentially billable dispatch.

## Implementation Units

1. Record adapter support matrix and fixtures; settle encrypted connection,
   supported MIME formats, request limits, and consent/retention contracts.
2. Add authenticated shared operation service, request IDs, cancellation,
   accounting, additive DB changes where required, and access/security tests.
3. Implement first STT adapter plus composer recording/draft state machine.
4. Implement deterministic speech renderer with Markdown/code/table/link fixtures.
5. Implement first TTS adapter, validated message-linked artifact publication,
   speaker/play/stop controls, and reuse without repeat billing.
6. Complete verified operations for ElevenLabs, Deepgram, Gradium, and selected
   compatible LLM providers; add inline Tools configuration and explicit tests.
7. Run scripted browser QA on desktop/mobile and actual Tauri microphone/playback
   checks; record unsupported platform/format limitations before release.

Existing targets: backend `api/settings.py`, `models/model_call.py`,
`artifacts/service.py`, `previews.py`, encryption and accounting/redaction services;
frontend `pages/ProvidersSettings.tsx`, `pages/Conversation.tsx`,
`components/ChatInputBar.tsx`, `components/MessageActions.tsx`,
`components/previews/useObjectUrl.ts`, `lib/api.ts`, and `lib/types.ts`.
Proposed: focused speech adapters, service, endpoints, and renderer modules.

## Acceptance

Text-only chat remains usable. Dictation never sends automatically or overwrites
another draft. Permission denial, silence, unsupported formats, provider failures,
cancel, navigation, and bounds all have honest visible states and cleanup.
TTS never reads raw markup, automatically speaks history, fabricates cost, or
executes tools. Replays use retained authorized audio, and independent voice
configuration does not change the agent's reasoning model or permissions.
