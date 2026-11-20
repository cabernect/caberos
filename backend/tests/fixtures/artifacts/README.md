# W0 Artifact Fixture Corpus

Synthetic test inputs, not evidence of native editability, visual quality or
safe live playback. `manifest.json` pins bytes, source specs, package versions,
expected results and per-file execution policy. See the W0 plan/evidence under
`docs/plans/v0.2.2/`.

## Generate And Verify

From `backend/` using the existing environment (no downloads):

```sh
.venv/bin/python tests/fixtures/artifacts/generate.py
.venv/bin/python -m pytest tests/test_artifact_fixtures.py tests/test_artifacts.py -q
```

Use `--output-dir /existing/parent/new-fixtures` for a separate corpus; the
generator creates that directory and does not clean up unrelated existing files.
Regenerating in place overwrites named generated outputs, not source files.

Byte reproducibility is tested within the pinned dependency environment.
The generator normalizes Office ZIP ordering/timestamps, core created/modified
metadata, and embedded Office ZIPs. This normalization is test-only and must
never be applied to tracked production revisions. A dependency/font change can
legitimately change output; the manifest records package versions.

## Corpus Coverage

| File(s) | Purpose / expected observation |
|---|---|
| `analysis-deck.pptx` | Eight slides, two native charts, one table, one image, notes |
| `analysis-deck-longtitle.pptx` | Deliberate wrapping/overflow pressure |
| `deck-vietnamese.pptx`, `report-vietnamese.docx` | Diacritics and glyph coverage |
| `deck-missing-font.pptx`, `report-missing-font.docx` | Deliberately unusual font name; measure actual substitution |
| `analysis-deck-external-edit.pptx` | Visible first-title change plus valid editor metadata; external conflict input |
| `deck-transition.pptx` | Synthetic fade-transition XML probe; no native playback verification yet |
| `report.docx` | Tables/figure/explicit breaks; four-to-six pages is an unverified target |
| `workbook.xlsx` | Styles/merges/filter/freeze and eight real formulas including SUM/IF/AVERAGE/cross-sheet |
| `uploaded-features.xlsx` | Table/chart/validation/conditional format/protection outside current structured create surface |
| `deck.html` | Four identified slides, navigation, motion/reduced-motion and fixture-only stable capture hook |
| `hostile-isolation.html` | Attempts parent/storage/API/network/socket/IPC/popup access; DO NOT OPEN normally |
| `hostile-loop.html` | Deliberate infinite loop; DO NOT OPEN normally |

The uploaded workbook is synthesized with openpyxl, not an actual Excel export.
It is not a macro/pivot/external-link preservation fixture. The transition probe
is assembled with XML only to test a foreign input; it is not a model-authored
XML interface, production effect implementation, or complete animation fixture.

## Safety

Tests parse/hash hostile HTML as text only. Neither generation nor tests run
scripts, contact external services, open Office applications or calculate formulas.
The `.invalid` URL is a reserved test name, but attempted requests still need
runtime blocking. Isolation probes require a future opt-in, bounded isolated
runtime; do not open them in the dashboard origin or an ordinary browser tab.
Infinite-loop tests must not run until the watchdog/process containment exists.

## Assets And Expected Values

All figures/data/text are synthetic repository-authored content governed by the
repository `LICENSE`; no downloaded image/font asset is bundled. `figure.png`
uses Pillow's bundled default font rasterized into an image, not an embedded
font file. Review the installed Pillow distribution's font notices when packaging.
The requested missing-font family is intentionally fictional, not an install.

Formula expectations in the manifest are hand-derived test oracles, not calculated
cache values. Formula caches remain absent/unverified until a named native engine
recalculates them. Float results need a stated tolerance in native checks.
