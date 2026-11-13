# W0 Preview Capability And Limitation Contract

Status: operator direction accepted; implementation and browser checks pending.
This supersedes earlier requirements to select a full Office layout engine.
LibreOffice is excluded: no integration, optional install, or W0 blocker.

## Scope

Preview eligibility depends on supported format/features, not who created the
file. Uploaded PPTX/DOCX/XLSX may use existing best-effort previews with visible
limitations. Do not disable them because no faithful Office renderer exists.
Keep existing PDF/image/text/Markdown/code/CSV/media previews.

Native editable Office creation/editing and HTML deck playback remain included.
Neither implies perfect Office layout reproduction in CaberOS. No new preview
dependency is required just to continue W0/W1.

## Preview Modes

| Source | Baseline preview | Required qualification |
|---|---|---|
| PPTX, uploaded or generated | Existing slide-grouped extracted text, images, tables and chart data | Limited preview; not original slide composition, fonts or effect playback |
| DOCX, uploaded or generated | Existing document content view | Limited preview; pagination, fonts, positioning, fields and advanced content may differ/be omitted |
| XLSX, uploaded or generated | Bounded worksheet grid and formula expressions; extend styles where supported | Not Excel print layout/full-feature view; formula results have independent provenance |
| PDF | Existing PDF pages | Existing limits/errors; no new Office conversion step |
| Images/SVG | Existing safe image view | Preserve existing decoding bounds and SVG image-loading policy |
| Text/Markdown/code/CSV/media | Existing format-specific views | Existing truncation/format limits remain explicit |
| HTML deck | Planned W2H isolated live playback and stable captures | No Office engine; motion tests separate from screenshots |
| Ordinary raw HTML | Existing code/source view | Do not silently execute uploaded HTML as an admitted deck |

An optional richer preview from a CaberOS-authored spec must identify itself as
a design/spec representation and pin the spec/assets to that exact revision.
It is not proof of how exported Office bytes render. Such a companion is not a
prerequisite for displaying existing Office previews.

## User-Facing Limitation Alerts

Show persistent, non-blocking notice inside the shared preview for approximate
Office modes. It applies to generated and uploaded files alike, follows revision/
source changes, and is distinct from file corruption, errors, and truncation.
The notice must not require dismissal before inspecting supported content.

Proposed English copy; official English/Vietnamese docs must explain equivalent
limitations using existing localization conventions:

| Format | Notice |
|---|---|
| PPTX | Limited preview. Layout, fonts, animations, and some elements may differ from PowerPoint or be omitted. |
| DOCX | Limited preview. Page layout, fonts, fields, and some content may differ from Word or be omitted. |
| XLSX | Limited preview. Some formatting and workbook features are not shown. Formulas are not calculated here. |

Adapt XLSX
wording if a separately approved calculation engine ever exists; do not imply one.

## Proposed Interface Semantics

Extend the existing preview payload rather than create parallel preview plumbing.
Exact field names remain to be settled against frontend/backend types in W1:

- Source: exact artifact/revision/hash, or proven live snapshot identity.
- Mode: content/approximate, native-supported view (e.g. PDF), HTML live, or
  authored-design representation. Unknown fidelity never defaults to native.
- Limitations: stable codes for layout/fonts/effects/omitted features/formula
  evaluation; a baseline Office warning does not require exhaustive detection.
- Additional findings: positively detected features such as a transition or
  conditional formatting can add detail. "Not detected" does not mean absent.
- Outcome: ready/partial/unsupported/failed plus explicit truncation. Preview
  readiness is not structural validity, native editability or model approval.

The same limitation semantics must reach the operator and agent. Agents reviewing
a content preview cannot claim exported PowerPoint/Word layout was verified.
Previewing never modifies source bytes, executes macros or calculates formulas.

## Implementation Responsibilities

- W0: record this contract and fixture coverage; keep remaining authoring/identity/
  asset decisions separate. No Office engine bake-off is a mandatory exit.
- W1: exact-source plumbing, mode/limitation metadata, bounded safe reads/captures,
  auth/cache/race behavior. Reuse existing Office previews.
- W4: implement persistent alerts across chat/Workspace/Skills, source/revision
  transitions and responsive/accessibility states; add frontend/browser tests.
- W5: retain mode/coverage in review evidence; unsupported layout checks are
  unavailable, not passed. HTML captures and supported image views remain useful.
- W6: verify supported content and truthful alerts; native Office edits/effects/
  recalculation remain separate checks on exported files, not preview-engine gates.

## Acceptance

- [ ] Uploaded and generated Office fixtures remain inspectable without LibreOffice.
- [ ] Shared preview shows the correct format-specific notice and mode.
- [ ] Existing non-Office preview types remain unchanged.
- [ ] Unsupported/omitted content and truncation never masquerade as complete output.
- [ ] Agent review distinguishes content/design/HTML views from native Office layout.
- [ ] Parser failure gives an error; a limitation notice does not conceal corruption.
- [ ] EN/VI docs explain the same scope; no UI feature is claimed from this plan.

Automated W0 fixture tests verify the existing extraction paths only. They do
not prove a visible alert exists; that requires W1/W4 implementation and browser
evidence. Native Office editability gates are unchanged.
