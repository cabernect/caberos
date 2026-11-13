# W2H - HTML Presentation Authoring And Isolated Playback

Status: prioritized first per operator decision 2026-11-13 — HTML decks are
the primary authoring path for presented deliverables (live preview beats
approximate Office extraction); Office files remain available via the
existing spec paths and uploaded Office keeps best-effort previews with
limitation alerts. HTML→PPTX export is NOT promised by this plan. Existing
HTML fixture is a sample, not a shipped artifact format.

Progress 2026-11-13: slices 1+2+3 landed — `formats/html.py` deck handler
(spec v1 → self-contained .html, whitelist fragment sanitizer, deck-rt1
nav runtime + postMessage bridge, slide-id revise addressing), `html`
registered in handlers/`_FORMATS`/tool schema. Slice 2 (revisioned
packaging): image blocks + `<img>` in fragments take workspace-relative
raster srcs (png/jpg/gif/webp by magic bytes, ≤4MB each, ≤25MB/20 assets
per deck), resolved via `resolve_within` (traversal/symlink-safe), embedded
as data URIs; asset manifest (path/mime/bytes/sha256) rides in the spec
JSON so inspect reports inventory and revise re-resolves against current
workspace bytes. Isolated player: admitted
decks (marker + valid spec + platform-scripts-only audit) serve via
`/workspace/deck` with hash-pinned script CSP + `sandbox allow-scripts`
directive; the panel renders `sandbox="allow-scripts"` (no
allow-same-origin) iframe + platform chrome. Browser-verified: nav bridge
1/3→2/3, opaque origin confirmed, zero console errors.

Progress 2026-11-13 (cont.): slices 5+7 partially landed — deck-rt2 runtime
with stepwise `reveal:true` blocks (platform + in-frame keyboard), `layout:
"title"` cover slides, `theme.font` (sans/serif/mono), presenter notes (N
toggle + state flag), progress bar, per-slide footer, directional slide
transition, polished block/table/image styling. Bridge gained `step`
(reveal-aware) + `goto` (exact index/reveal — the deterministic state hook
slice 6 capture needs); state reports index/count/revealed/pending/
canPrev/canNext/notes. Title-only slides legal; inspect reports
`reveal_blocks` + asset manifest. Skill docs: office-documents specs.md has
the full deck spec; SKILL.md teaches html-deck-by-default vs pptx-for-
editability. Browser-verified on QA stack: reveal consumes Next presses
(1/4→1/4→2/4 sequence), goto determinism, iframe keyboard, notes overlay,
zero console errors. Remaining: portable-download offline check (7),
capture (6), Tauri-shell auth path.

Progress 2026-11-13 (cont. 2): deck-rt3 — slides are a true 16:9 canvas
letterboxed in the player (container-query units scale type to slide
width, not viewport shape); runtime shrink-to-fit (`--dfs`) scales type,
padding and images so dense slides fit instead of scrolling (55% floor,
styled scrollbar fallback); sparse slides center vertically. Multi-runtime
admission: every known platform runtime (rt1/rt2/rt3) is byte-exact
matched and CSP-hash-pinned, so decks built before a runtime upgrade keep
playing — inspect reports the file's actual runtime. Frontend sends
`nav` to rt1, `step`/`goto` to rt2/rt3. Caveat: old files keep their
embedded CSS/JS — the fixes apply to decks built or revised after rt3.
Browser-verified: rt1 deck plays + navigates, rt3 dense slide fits at
dfs≈0.62, sparse slide centers at dfs=1, extreme overflow scrolls
honestly, zero console errors.

Bounded execution is satisfied by the constrained scripting model, not a
watchdog: admitted decks contain ONLY the platform runtime (hash-pinned
in CSP) — deck-authored JS is never admitted, so no arbitrary code can
loop or freeze the main thread. Arbitrary-script .html files get the
static source view, never playback. Tauri-shell playback still needs its
own auth/path verification (iframe can't send Bearer; cookie is
SameSite=Lax same-site only).
Dependencies: [W0](00-contracts-fixtures.md) HTML identity/package/isolation decisions.
No LibreOffice or native Office renderer dependency.

## Purpose And Operator Workflow

Create an attractive presentation that plays in a browser: slide navigation,
supported transitions, stepwise reveals, and bounded interactions. Operator opens
the exact revision in CaberOS, plays it, asks to simplify a named slide, and
downloads a portable deck that works offline.

This is the HTML feature, not an alternative name for Office preview. It does
not promise lossless HTML-to-PPTX export, a Canva editor, arbitrary web apps, or
safe execution of every uploaded `.html` file.

## Contracts Before Coding

- Decide structured deck schema/runtime versus admitted raw fragments. Define
  stable slide/block IDs, themes/layouts, notes, interactions and effect vocabulary.
- Choose single HTML file or bundle; measure asset-size/portability trade-offs
  before fixing limits. Pin scripts/styles/images/fonts per immutable revision.
- Separate trusted platform controls from untrusted deck content. Define browser
  and Tauri isolation, execution bounds, capture protocol, and failure recovery.
- Define reduced motion and explicit stable capture states, independent of
  elapsed time. Captures identify revision, slide, viewport, and reveal state.

## Implementation Slices

1. **Minimal artifact path.** Extend existing dispatch/create/inspect/revise for
   the chosen deck format. One slide, local asset, metadata/IDs and validation;
   retain base revision checks, provenance, history and restore-as-new.
2. **Revisioned packaging.** Resolve assets within admitted workspace roots,
   validate MIME/decoded sizes and licenses, embed or bundle pinned bytes.
   Reject traversal/symlinks escaping roots and implicit CDNs/remote fonts.
   Inspect reports asset inventory and supported-runtime version.
3. **Isolated player.** Use an untrusted surface with no app-origin credentials,
   Tauri IPC, filesystem or CaberOS API authority. Restrict navigation, popups,
   downloads, form submission and network. Enforce policy at serving/playback,
   not only a removable CSP meta tag in generated source.
4. **Bound execution.** An iframe sandbox alone does not guarantee CPU/process
   isolation. Prove looping scripts cannot freeze the app on browser and Tauri;
   use a bounded isolated runtime or constrained scripting model as required.
   Add watchdog, kill/close/reload and cleanup behavior.
5. **Player features.** Previous/next, position, keyboard/focus handling,
   presentation/fullscreen where supported, notes policy, reduced motion and
   a small tested transition/reveal/interaction set. Closing stops media/work.
6. **Capture and revise.** Reuse W1 source/result conventions for bounded stable
   slide images. Validate a narrow message bridge against the active player
   instance/source and strict schema; opaque origin messages alone are not proof
   of trust. Targeted revisions preserve unaffected slides and revision assets.
7. **Portable download and guidance.** Verify the file/bundle opens offline
   without CaberOS services. Document supported browsers, keyboard behavior,
   script limitations and safe asset choices; update authoring skill resources.
8. **Deck export (design-first → deliverable).** Per the authoring contract's
   two-mode pptx model: export a deck revision to PDF via the managed
   browser's `printToPDF` (printBackground + preferCSSPageSize, fixed
   1280×720 slide pages), and/or to a lossy native `.pptx` for simple
   layouts (title/bullets/table) with complex slides rendered as images —
   never a broken half-mapped pptx. Export is a new revision of a *separate*
   artifact or an explicit download action; it must not mutate the deck.
   Lossy-ness is declared in the result metadata.

## Import And Security Behavior

Ordinary HTML source preview stays available. Do not automatically execute any
`.html` selected in Workspace or Skills; define explicit admission/player policy.
Static validation is not a complete network/script security boundary.

Test fetch/XHR/WebSocket, CSS URLs, images/fonts/media, frames, navigation and
popups, parent DOM/storage/cookies, forged messages, file URLs and Tauri commands.
Source bytes remain downloadable even when playback is refused. Opening a
download outside CaberOS has a different trust boundary and must be documented.

## Verification And Done When

Acceptance: A31-A33, plus A10-A12, A16-A18, A20, A22 and applicable A24-A25.
Test live motion/interaction separately from stable screenshots.

- [ ] Create, inspect, targeted revise, history, restore and portable download work.
- [ ] Local assets remain identical when selecting an older revision.
- [ ] Offline playback, reduced motion and stable captures pass.
- [ ] Hostile and infinite-loop decks cannot gain authority or freeze the main app.
- [ ] Browser and packaged Tauri behavior verified independently.

Targets: artifact dispatch/service/capabilities, preview APIs, isolated frontend
playback, managed capture runtime if required, skill resources and fixture tests.
