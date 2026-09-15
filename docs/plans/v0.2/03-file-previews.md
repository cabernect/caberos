# v0.2.0 File Previews and Composer Attachments

## Outcome

Users paste and inspect attachments before sending, then preview generated or workspace files from chat, Agent Settings, and Skills Studio through one safe reusable preview module.

## Dependencies

- Artifact Studio for tracked revisions
- Existing attachment persistence and workspace containment

## Supported previews

| Format | Preview |
|---|---|
| Markdown | rendered/source |
| Text/code/JSON/CSV | bounded text/code/table |
| Images/SVG | sanitized image |
| PDF | paginated viewer |
| DOCX | rendered pages/document |
| PPTX | thumbnails + selected slide |
| XLSX | tabs + virtualized grid |
| Audio/video | native controls |
| Unknown binary | metadata + download/open |

## Shared preview panel

```text
Conversation
  → resizable right-side panel; chat narrows without modal/navigation

Agent Settings → Workspace
  → split file-browser/preview inside expanded Settings

Skills Studio
  → Skill-resource preview using the same renderers
```

Chat opens the exact Artifact revision attached to the message. Workspace opens the current file/revision. Newer revisions appear as a banner and never silently replace selected content.

Tracked Artifacts expose History, compare, restore, download, open, reveal, Add to Vault, and Ask agent to revise. Ordinary files expose current preview, metadata, and Track history without fabricated revisions.

Closing Workspace preview preserves path, selection, scroll, and focus. `Escape` closes preview before Settings. Narrow layouts use a full-width preview with Back to Workspace.

## Composer attachment tray

Replace filename-only chips with visual previews:

- clipboard image paste without inserting base64 into text;
- copied screenshots/web images show local thumbnails;
- drag/drop and file picker share the tray;
- PDF/Office use bounded first-page/slide/sheet previews when available;
- URLs use domain/title preview;
- show name, type, size, upload state, remove, and reorder;
- preserve intentional mixed text/image clipboard content;
- detect duplicate bytes by content hash;
- failed send retains the draft and attachments;
- revoke temporary object URLs after removal/send;
- non-vision models receive metadata, never hidden image input.

## Safety and performance

- Sanitize active HTML/SVG.
- Never execute macros/binaries.
- Bound bytes, pages, rows, sheets, thumbnails, and concurrent renders.
- Lazy-load large previews.
- Render untrusted formats out of process where practical.
- Preview failure never deletes or invalidates the source file.

## Tests first

- Paste image, text, URL, and mixed clipboard cases
- Multiple attach/reorder/remove/retry
- Composer/streamed/persisted preview parity
- Exact chat revision versus current Workspace revision
- Settings split-panel state/focus preservation
- Tracked versus ordinary-file actions
- Live file/revision update banner
- Responsive full-width preview
- Keyboard accessibility
- Very large fixture remains bounded
- Deleted/unavailable revision state

## Done when

Every target format opens through the same preview module from chat, Workspace, and Skill resources, and clipboard images persist correctly through a complete message round trip.
