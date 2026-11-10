# First Media Capability

Status: decided — **image generation** (`media.image`) is the first modality;
`media.tts`, `media.stt`, `media.video` stay roadmap until a real backend
exists — see [Tool bindings](05-tool-bindings.md#binding-key-roadmap).

## Decision Gate — Recorded

| Question | Evidence |
|---|---|
| Modality | **Image** — the plan's fallback activates. The bundled `models.dev` snapshot carries no TTS models at all (`openai` has zero `tts`/`audio` entries), and LiteLLM `aspeech` returns `HttpxBinaryResponseContent` with **no usage object** — so TTS would have neither pricing authority nor reported usage, violating "unknown ≠ zero" accounting less usefully than image. |
| Provider | `openai` provider type (already first-class, encrypted key, existing readiness checks). |
| Models | Bundled catalog carries `gpt-image-1`, `gpt-image-2`, `gpt-image-1-mini`, `gpt-image-1.5`, `chatgpt-image-latest` with `output: ['image']` modality; `gpt-image-2` has token pricing (in 5 / out 30 per Mtok) → real cost provenance via `capture_call_rates`. |
| Transport | LiteLLM 1.106.6 `aimage_generation` → `ImageResponse`; `data[].b64_json` gives bytes directly (no URL fetch — satisfies "prefer bytes"); `usage.input_tokens/output_tokens` normalizes under the `chat` family. |
| Output contract | `n=1` fixed (no multi-output billing), `size`/`quality`/`format` allowlists via binding options, `b64_json` response format, magic-byte + MIME validation, 16 MiB cap. |
| Cancellation | Single `asyncio.wait_for` timeout; no automatic retry after ambiguous billable dispatch — timeout/error records the attempt honestly. |
| Cancellation of TTS decision | TTS requires a catalog entry + reported-usage path that doesn't exist yet; adding hand-rolled pricing contradicts "bundled models.dev is pricing authority". |

## Goal

Ship one complete mediated workflow: configured Model Offering -> approved
request -> bounded provider output -> tracked artifact -> inspectable accounting.
Do not implement several modalities or add placeholder handlers.

## Decision Gate

Before implementation, record the chosen modality, one supported provider,
transport behavior, formats, cancellation semantics, and pricing evidence.
Inspect the provider abstraction and actual supported API documentation before
selecting methods; no provider compatibility has been verified by this plan.

For TTS, use explicit input text, bounded length, allowlisted voice/format options,
and one output. No voice cloning, speaker uploads, or arbitrary callback URLs.
If image generation is chosen, replace audio-specific acceptance scenarios
explicitly rather than claiming both modalities.

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
Success yields playable/downloadable tracked output. Correlation is exact.
Oversize/invalid data, unavailable providers, timeouts, cancellation, publication
failure, and unknown cost are covered without silent fallbacks or paid retries.
