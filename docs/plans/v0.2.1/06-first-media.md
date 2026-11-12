# First Media Capability

Status: image generation/editing (`media.image`) is implemented as the first
agent-callable media slice. The original speech deferral is superseded by
[W10: Speech Input And Output](10-speech-input-output.md), now in v0.2.1 scope
as operator UI actions, not agent tools. Video remains deferred.

## Decision Gate — Historical W6 Selection

The evidence below records why image shipped first, not a current restriction
against speech. Missing pricing/usage must remain unknown; it is not a reason
to fabricate rates or require a catalog entry before enabling a verified API.

| Question | Evidence |
|---|---|
| Modality | **Image** — the plan's fallback activates. The bundled `models.dev` snapshot carries no TTS models at all (`openai` has zero `tts`/`audio` entries), and LiteLLM `aspeech` returns `HttpxBinaryResponseContent` with **no usage object** — so TTS would have neither pricing authority nor reported usage, violating "unknown ≠ zero" accounting less usefully than image. |
| Provider | `openai` provider type (already first-class, encrypted key, existing readiness checks). |
| Models | Bundled catalog carries `gpt-image-1`, `gpt-image-2`, `gpt-image-1-mini`, `gpt-image-1.5`, `chatgpt-image-latest` with `output: ['image']` modality; `gpt-image-2` has token pricing (in 5 / out 30 per Mtok) → real cost provenance via `capture_call_rates`. |
| Transport | LiteLLM 1.106.6 `aimage_generation` → `ImageResponse`; `data[].b64_json` gives bytes directly (no URL fetch — satisfies "prefer bytes"); `usage.input_tokens/output_tokens` normalizes under the `chat` family. |
| Output contract | `n=1` fixed (no multi-output billing), `size`/`quality`/`format` allowlists via binding options, `b64_json` response format, magic-byte + MIME validation, 16 MiB cap. |
| Cancellation | Single `asyncio.wait_for` timeout; no automatic retry after ambiguous billable dispatch — timeout/error records the attempt honestly. |
| Original TTS deferral (superseded) | Catalog/usage gaps favored image first. W10 permits honest unknown audio pricing/usage and adds separate speech adapters and accounting. |

## Goal

Ship one complete mediated workflow: configured Model Offering -> approved
request -> bounded provider output -> tracked artifact -> inspectable accounting.
This workstream covers images only; W10 separately covers speech. Do not claim
other modalities work or add placeholder handlers.

## Decision Gate

Before implementation, record the chosen modality, one supported provider,
transport behavior, formats, cancellation semantics, and pricing evidence.
Inspect the provider abstraction and actual supported API documentation before
selecting methods; no provider compatibility has been verified by this plan.

Audio-specific UI, authority, retention, and acceptance are now defined in W10.
The remaining contracts in this document govern the mediated image tool path.

## Existing File Targets

`providers/interface.py`, `providers/registry.py`, `providers/litellm_transport.py`,
`capabilities/builtin.py`, `syscall/mediator.py`, `models/model_call.py`,
`artifacts/service.py`, `models/artifact.py`, `previews.py`, and observability
projections. Audit rate snapshots and cost classification before extending them.
Proposed: a focused media execution module plus a capability handler.

## Execution Contract

1. Resolve supported binding and pin its effective provider/model/options.
2. Validate text/options and output budget before dispatch.
3. Cross syscall mediation with accurate egress/effect flags and the normal
   approval gate; missing grants/configuration deny before any provider call.
4. Dispatch one bounded request. Enforce connect/read/total timeouts and byte
   limits; do not automatically retry a potentially billable ambiguous request.
5. Validate actual returned bytes/MIME. A provider-returned URL is not permission
   for unrestricted fetching: prefer bytes or apply explicit safe-fetch policy.
6. Stage output under the pinned workspace's `artifacts/` and publish tracked
   identity/revision bytes through a deliberate binary-artifact interface.
7. Return artifact identity, safe preview/download references, and exact call
   correlation, not a base64 blob in conversation history.

## Artifact Contract

Current structured Office artifact creation is not an implicit audio contract.
Add a bounded trusted binary ingestion path internal to the media module;
do not let arbitrary agent-supplied bytes bypass validation.

Define filename/path containment, allowed formats, revision publication, cleanup
on DB/file failure, and preview/download authentication. Audio playback is inert,
bounded, and user-controlled, without autoplay or unexpected remote fetching.
Retain provenance and revision evidence across workspace default changes.

## Ledger And Cost

One `model_calls` record per actual provider attempt, with modality, Model
Offering, status, latency, run/session/tool-call correlation, and typed usage
units. Use `detail` or additive typed fields after deciding a stable contract;
never overload tokens with audio seconds or image counts.

Store reported usage and estimated usage distinctly with price provenance.
Unavailable price or usage remains unknown, not zero/free. A timeout after
dispatch may have incurred cost; denied requests create no fabricated model call.
Provider success followed by artifact failure still preserves the real model
attempt and reports the output failure honestly.

## Implementation Steps

1. Finalize provider, usage, output, and pricing contracts with scripted fixtures.
2. Add binary-artifact and preview support with validation/rollback tests.
3. Add bounded provider execution and ledger recording across success/failure.
4. Register the mediated capability and readiness wiring; verify approval denial,
   cancellation, binding drift, and no-grant behavior.
5. Complete Tools configuration and artifact UX, then run deterministic browser QA.
6. With explicit consent, do one bounded real-provider smoke test and record actual
   output, ledger evidence, and any unknown price/usage.

## Acceptance

No provider call before required approval; no extra permissions from a binding.
Success yields previewable/downloadable tracked image output. Correlation is exact.
Oversize/invalid data, unavailable providers, timeouts, cancellation, publication
failure, and unknown cost are covered without silent fallbacks or paid retries.
