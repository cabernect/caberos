# v0.2 Dependency Readiness (W11 Track B, Former W12)

This is a detailed track of [W11 Runtime Readiness](11-bug-fixes.md), not a
separate workstream. The operator approved app-managed installation as the
default, with fixed subprocess recipes and guided system installation as
fallbacks. No binaries have been downloaded or verified by this specification.

## Outcome

Optional dependencies are operator-managed from an **Optional Tools & Runtimes**
section in global Settings -> General: detected, installed, and re-checked on
demand. Features that
need a missing dep degrade honestly — they say what they need and offer an
install path — instead of failing silently or pretending.

## Dependencies

- W3 previews (renderers that can use local tools)
- W4 managed browser (Chromium install is a dep of this shape)

## Principle

CaberOS stays installable and useful with zero optional deps. Every dep is
opt-in: the user clicks Install, or declines and accepts the documented
limitation. No auto-installs, no surprise network fetches.

## End-User Scope

The packaged desktop app includes its Python gateway, application libraries, SQLite, and compiled frontend. Node, Python, uv, Rust, Homebrew, and a database server are not general prerequisites for using it. Development/build prerequisites are not dependency-manager requirements.

Local MCP servers may require their own Node/npm or uv/Python environment and additional tools. Determine requirements from the selected server; a missing local runtime must not block remote HTTP MCP servers or unrelated capabilities. Do not infer the runtime required by arbitrary custom servers without explicit configuration.

A local model server such as Ollama is conditional on provider choice, not a baseline installation. Show its connection/configuration health with the provider; do not silently install a model server or download model weights.

Desktop sandbox readiness remains in Health: macOS uses built-in Seatbelt; supported Windows installations bundle experimental MXC with explicit first-use setup. Linux/Docker deployment requirements are separate from packaged-desktop optional installations. Host MCP runtime availability does not imply accessibility inside the Windows shell sandbox; never widen sandbox permissions just to expose a managed runtime.

FFmpeg/transcoding and Tesseract/OCR are deferred: neither feature currently consumes those binaries. Do not show actionable install prompts or claim installing them enables these features. Revisit recipes only when the corresponding capability is implemented.

## Known optional deps

> **Scope note (2026-10-13):** Office→PDF export and the LibreOffice dependency were removed by operator decision. The table below lists the four active dependencies; native Office generation/previews and direct PDF creation/viewing are unaffected.

| Dep | Unlocks | Without it |
|---|---|---|
| Chromium (managed profile) | W4 browser automation | Browser automation features are unavailable until a configured or private install exists |
| Node.js/npm/npx | Selected JavaScript stdio MCP servers | Only those MCP servers can't launch; resolver already handles PATH |
| uv/uvx | Selected Python stdio MCP servers | Only those MCP servers unavailable; a separate MCP Python environment may need to exist or be provisioned — the bundled gateway is not their interpreter |
| Git | Git MCP servers and Git-based agent/workspace workflows | Git-dependent integrations/workflows are unavailable; unrelated app features still work |

## Optional Tools & Runtimes (Global Settings -> General)

```text
Settings → General → Optional Tools & Runtimes
  ┌─────────────────────────────────────────────┐
  │ Chromium           not installed      [Install] │
  │ Node.js            detected · v22     [✓]   │
  │ uv/uvx             not installed      [Set up] │
  │ Git                declined           [Install] │
  └─────────────────────────────────────────────┘
```

Install starts an approved managed recipe; Set up opens guided instructions when no verified managed recipe is available.

Per dep: status (`installed` + version / `not installed` / `declined` /
`installing` + progress), what it unlocks, Install / Re-check / Dismiss.
Declined is remembered — the feature stays available but shows the limitation
instead of re-prompting forever.

## Detection

A registry maps dep → detection strategy: `shutil.which` names + well-known
paths (platform package locations) +
version probe (`node --version`, `git --version`).

## Installation Policy

| Dependency | Initial strategy |
|---|---|
| Chromium | Reuse the existing private managed Chrome runtime |
| Node.js/npm/npx | Detect compatible system installation; offer private managed runtime on verified platforms through General settings or approved JavaScript MCP setup; never auto-install on startup |
| uv/uvx | Detection plus guided installation only when a chosen Python MCP server requires it; managed recipes are a future verified extension |
| Git | Detect compatible Git; CaberOS-managed setup on verified platforms, available directly in General or as a prerequisite of an approved Git MCP setup; not a manual-install requirement for nontechnical users |

Detection order: explicit configured override, compatible system installation,
then a compatible app-managed installation. Never download simply because a
preferred source is absent. Report detected-but-incompatible separately from ready.

### Guided Integration Setup

Optional does not mean the operator must install tools manually. ~~A Git MCP setup should present one CaberOS-owned preparation plan~~ — **combined Git MCP preparation is excluded from W11 by operator decision (2026-10-13)**; proactive General-settings runtime installs remain supported, and any future prep plan must still follow explicit approval, fixed recipes, reuse of compatible tools, and no expansion of repository-write or agent authority.

Global General settings lists supported optional tools even when no integration currently needs them, so an operator can proactively install Git. An agent/workflow may request preparation, but downloads begin only after operator approval of the same trusted installation plan. No LLM-generated shell commands, arbitrary package/URL guesses, or implicit package downloads during probing.

When a platform lacks a verified recipe, show that setup is unsupported/unavailable with an optional expert workaround; do not label manual Git installation as the standard user journey. App-managed host Git availability is separate from availability inside the Windows shell sandbox, whose current restrictions remain unchanged.

### Managed Installer Contract

- Recipes are fixed, versioned, dependency/platform-specific inputs. The request
  selects a dependency/recipe; it cannot supply arbitrary commands, URLs, or paths.
- Before consent, show version, publisher/source, approximate size where known,
  private destination, verification method, and what functionality it unlocks.
- Store managed versions under app-controlled data, outside agent workspaces.
  Stage into a new directory, verify, smoke-test, then atomically activate.
- Retain the previous working version on failure/cancellation. Serialize competing
  installs for a dependency and make retried requests idempotent.
- Expose queued/downloading/extracting/verifying/activating/completed/failed/
  cancelled/interrupted job states, byte progress where available, and bounded logs.
  Persist enough job identity/state to mark unfinished jobs interrupted on restart.
- Enforce timeouts, download/extraction size limits, archive path containment,
  redirect/source restrictions, and platform/architecture checks.
- Use trusted publisher signatures or published checksums where available.
  A locally computed SHA-256 is only a fingerprint. Expose the actual verification
  level; do not claim authenticated publisher verification from a local hash.
- Fixed subprocess recipes use argument arrays, not shell interpolation; cancel
  and timeout terminate the associated process tree. They are operator-controlled
  installer jobs, not the agent's arbitrary terminal capability.
- No `sudo`, package-manager bootstrapping, global PATH edits, or overwriting system
  binaries automatically. System-changing fallbacks need separate explicit consent;
  if elevated privileges are required, provide instructions for the operator.
- Startup performs no automatic installation. An agent/workflow request creates
  no implicit consent; its preparation plan waits for explicit operator approval.
- Decline persists. Failures are actionable and never reported as ready.
- Repair/update uses the same verified installation lifecycle. Removing managed
  versions affects only CaberOS-owned files, requires explicit confirmation, and
  must not remove a version still in use.

### Executable Resolution And Feature Gating

One dependency module owns detection and resolved executable paths. MCP subprocess
environments receive the selected Node/npm paths locally; do not modify global PATH.
Browser/artifact/preview callers use the same resolution interface and re-check
after an installation or explicit configuration change.

Feature checks cover installed software and implemented capability separately:
detecting a supporting tool does not imply the consuming feature was implemented.
Supporting resources such as language data or companion libraries are part of
readiness where a verified recipe requires them.

Docker uses explicit build-time provisioned dependencies; runtime self-installation
and new desktop platform support are not implied by this workstream.

## Feature gating

Features query the dep registry, not bespoke `which()` calls:

- Image-only PDFs retain the current no-extractable-text limitation; do not offer Tesseract as a working remedy until an OCR implementation exists.
- First-hit prompt: when a feature hits a missing dep, surface it once
  (notification or inline affordance); decline persists.

## Tests first

- Registry detection: fake `which`/paths → correct status per dep
- Status transitions: not installed → installing → installed/declined
- Decline persistence: no re-prompt; feature shows limitation state
- Install path: mocked installer → status flips, version recorded

## Done when

- Every optional dep has one detection source of truth and one UI surface.
- No feature silently fails for a missing dep — each states what it needs.
- A user who declines everything gets a fully honest, still-working CaberOS.
