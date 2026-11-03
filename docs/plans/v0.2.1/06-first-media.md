# First Media Capability

Status: proposed. Choice not finalized: TTS recommended; image generation is the
alternative if supported-provider feasibility makes TTS unsuitable. Whichever
ships first becomes the first live `model`-shape binding under the W5 registry
(`media.tts` / `media.image`); `media.stt` and `media.video` stay roadmap until
a real backend exists — see [Tool bindings](05-tool-bindings.md#binding-key-roadmap).

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
