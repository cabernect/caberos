# W2H - HTML Presentation Authoring And Isolated Playback

Status: planned. Existing HTML fixture is a sample, not a shipped artifact format.
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
