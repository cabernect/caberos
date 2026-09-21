# v0.2 Optional Dependencies (W12)

## Outcome

Optional system dependencies are user-managed from a **Dependencies** tab in
global settings: detected, installed, and re-checked on demand. Features that
need a missing dep degrade honestly — they say what they need and offer an
install path — instead of failing silently or pretending.

## Dependencies

- W3 previews (renderers that can use local tools)
- W2 artifact export (`artifact_export_pdf` renderer chain)
- W4 managed browser (Chromium install is a dep of this shape)

## Principle

CaberOS stays installable and useful with zero optional deps. Every dep is
opt-in: the user clicks Install, or declines and accepts the documented
limitation. No auto-installs, no surprise network fetches.

## Known optional deps

| Dep | Unlocks | Without it |
|---|---|---|
| LibreOffice (`soffice`) | Layout-faithful DOCX/PPTX/XLSX→PDF export; rendered Office previews | reportlab fallback for docx/xlsx; `renderer_unavailable` for pptx; element-based previews |
| Chromium (managed profile) | W4 browser automation; positioned-HTML slide render (W4 path) | Browser features off; pptx→pdf stays unavailable |
| Node.js / npx | MCP stdio servers (`npx`-based) | stdio MCP servers can't launch; resolver already handles PATH |
| ffmpeg | Media thumbnails, transcoding for audio/video previews | Media previews limited to native playback/metadata |
| tesseract | OCR for image-based PDFs in `read_file`/previews | image PDFs honestly report "no extractable text" |

## Dependencies tab (global settings)

```text
Settings → Dependencies
  ┌─────────────────────────────────────────────┐
  │ LibreOffice        installed · 25.2   [✓]   │
  │ Chromium           not installed      [Install] │
  │ Node.js            detected · v22     [✓]   │
  │ ffmpeg             not installed      [Install] │
  │ tesseract          declined           [Install] │
  └─────────────────────────────────────────────┘
```

Per dep: status (`installed` + version / `not installed` / `declined` /
`installing` + progress), what it unlocks, Install / Re-check / Dismiss.
Declined is remembered — the feature stays available but shows the limitation
instead of re-prompting forever.

## Detection

A registry maps dep → detection strategy: `shutil.which` names + well-known
paths (e.g. `/Applications/LibreOffice.app`, platform package locations) +
version probe (`soffice --version`, `node --version`). `_find_soffice` in
`artifacts/service.py` generalizes into this registry — one source of truth.

## Install

Per-dep installer strategy per platform: macOS `brew --cask`, Linux package
manager hints, or a direct download link when no package manager applies.
Install runs through the sandbox/terminal machinery with user-visible progress;
approval applies. Docker image installs are build-time, not runtime (W10).

## Feature gating

Features query the dep registry, not bespoke `which()` calls:

- `artifact_export_pdf` on pptx → `renderer_unavailable` + `missing_dep:
  libreoffice` + hint pointing at the Dependencies tab.
- Image-PDF `read_file` → existing honest note gains "install tesseract to
  OCR" when absent.
- First-hit prompt: when a feature hits a missing dep, surface it once
  (notification or inline affordance); decline persists.

## Tests first

- Registry detection: fake `which`/paths → correct status per dep
- Status transitions: not installed → installing → installed/declined
- Feature gating: pptx export reports `missing_dep` + hint when absent
- Decline persistence: no re-prompt; feature shows limitation state
- Install path: mocked installer → status flips, version recorded

## Done when

- Every optional dep has one detection source of truth and one UI surface.
- No feature silently fails for a missing dep — each states what it needs.
- A user who declines everything gets a fully honest, still-working CaberOS.
