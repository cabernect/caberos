# W3 Test Plan — executable by an agent

Validates the merged W3 scope (PR #51 on `feat/v0.2.0`): file previews,
attachments, workspace file management. Written for an autonomous agent —
every case has an exact command and a programmatic assertion. Run sections in
order; each is self-contained.

## 0. Environment

```bash
# Terminal 1 — backend on :8081 (auto-reloads)
cd backend && AGENTOS_RELOAD=true uv run python -m agentos.gateway_entry

# Terminal 2 — frontend on :5173
cd frontend && npm run dev
```

Auth — every API call needs a session token:

```bash
TOKEN=$(curl -s -X POST http://localhost:8081/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"<operator>","password":"<password>"}' \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["session_token"])')
export H="Authorization: Bearer $TOKEN"
```

Pick a test agent id (list: `curl -s -H "$H" localhost:8081/api/agents`).
Below, `AG=<agent_id>` and `WS=backend/data/workspaces/<agent_id>`.

## 1. Fixtures

```bash
mkdir -p "$WS/fixtures/dir-with-files"
echo "# Hello" > "$WS/fixtures/notes.md"
python3 -c 'print("a,b\n"*600)' > "$WS/fixtures/big.csv"          # >500 rows
python3 -c 'print("x"*250000)' > "$WS/fixtures/long.txt"          # >200k chars
head -c 200 /dev/urandom > "$WS/fixtures/blob.bin"                # unknown kind
printf 'PNG' > "$WS/fixtures/bad.png"                             # corrupt image
echo data > "$WS/fixtures/dir-with-files/inner.txt"
ln -s /etc/hostname "$WS/escape-link"                             # symlink escape
```

Plus one tracked artifact (create via `artifact_create` or the UI) and one
untracked file under `artifacts/` (e.g. `artifacts/untracked.txt`).

## 2. Backend API suite

Run with `curl -s -o /tmp/body -w '%{http_code}'` — assert status, then
`python3 -c` assertions on `/tmp/body`.


| #   | Command (append to `localhost:8081/api/agents/$AG`)                    | Expect                                                                  |
| --- | ---------------------------------------------------------------------- | ----------------------------------------------------------------------- |
| A1  | `GET /workspace/preview?path=fixtures/notes.md`                        | 200, `.kind=="markdown"`                                                |
| A2  | `GET /workspace/preview?path=fixtures/big.csv`                         | 200, `.truncated==true`, `.total>500`                                   |
| A3  | `GET /workspace/preview?path=fixtures/long.txt`                        | 200, `.truncated==true`                                                 |
| A4  | `GET /workspace/preview?path=fixtures/blob.bin`                        | 200, `.kind=="unknown"`                                                 |
| A5  | `GET /workspace/preview?path=fixtures/bad.png`                         | 200, image kind with honest error — no 500                              |
| A6  | `GET /workspace/preview?path=../../etc/passwd`                         | **403**                                                                 |
| A7  | `GET /workspace/preview?path=/etc/passwd`                              | **403**                                                                 |
| A8  | `GET /workspace/preview?path=escape-link`                              | **403** — symlink escape blocked                                        |
| A9  | `GET /workspace/preview?path=missing.txt`                              | **404**                                                                 |
| A10 | `GET /workspace/preview?artifact_id=<id>` (tracked file)               | 200, artifact meta embedded                                             |
| A11 | `GET /workspace/preview?artifact_id=<id>&revision_id=<old>`            | 200, serves revision bytes, flags newer revision                        |
| A12 | `GET /workspace/raw?path=fixtures/notes.md`                            | 200, raw bytes, text content-type                                       |
| A13 | `GET /workspace/pdf-page?path=<pdf>&page=1`                            | 200, `Content-Type: image/png`                                          |
| A14 | `GET /workspace/pdf-page?path=fixtures/notes.md&page=1`                | 4xx — non-PDF refused                                                   |
| A15 | `DELETE /workspace?path=fixtures/dir-with-files`                       | 200, dir + children gone on disk                                        |
| A16 | `DELETE /workspace?path=<tracked-artifact-path>`                       | **409**, detail mentions "tracked"/"untrack"                            |
| A17 | `DELETE /workspace?path=artifacts` (contains tracked file)             | **409**                                                                 |
| A18 | `DELETE /workspace?path=artifacts/untracked.txt`                       | 200 — untracked sibling fine                                            |
| A19 | `DELETE /workspace?path=` and `?path=/`                                | **400**                                                                 |
| A20 | `DELETE /workspace?path=escape-link`                                   | 200 — symlink removed, `/etc/hostname` intact (`test -f /etc/hostname`) |
| A21 | `DELETE /workspace?path=../outside`                                    | **403**                                                                 |
| A22 | `POST /artifacts/adopt` `{path: "fixtures/notes.md"}` → then A16 on it | adopt 200 → delete now 409                                              |


Disk assertions after deletes: `test ! -e "$WS/<path>"`.

## 3. Composer + send suite (UI)

Navigate `http://localhost:5173` → open a conversation → use
`browser_evaluate` + a `DataTransfer` on `#file-input` to stage files.


| #   | Steps                                                  | Assert via `browser_evaluate`                                                                                          |
| --- | ------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------- |
| U1  | Stage a `.txt` via file input                          | tray shows `AttachmentCard` with `FileTypeTile` + `name · size`                                                        |
| U2  | Stage a real PNG (inline base64 → `File`)              | `img[src^="blob:"]` with `naturalWidth > 0`                                                                            |
| U3  | Stage the same file twice                              | exactly one chip — SHA-256 dedupe                                                                                      |
| U4  | Reorder two chips, remove one                          | order changed, `blob:` URL revoked                                                                                     |
| U5  | Send message with PNG staged                           | **thumb continuity**: poll `img.naturalWidth` at 200ms intervals for 4s — never 0; `src` transitions `data:` → `blob:` |
| U6  | Immediately after U5, click "new chat", reopen session | sent card still shows attachments (reload-preservation regression)                                                     |
| U7  | Click sent card                                        | `PreviewPanel` opens on the stored `attachments/` path                                                                 |
| U8  | Send a `https://` URL attachment                       | card shows domain/title; clicking opens preview with the URL                                                           |
| U9  | Attach, then force `onSend` false (offline backend)    | draft + attachments retained                                                                                           |


## 4. PreviewPanel + delete suite (UI)

Settings → Workspace tab. `useConfirm` modals — accept via the dialog button.


| #   | Steps                                                     | Assert                                                           |
| --- | --------------------------------------------------------- | ---------------------------------------------------------------- |
| P1  | Open `fixtures/notes.md`                                  | rendered markdown, not raw source                                |
| P2  | Open `big.csv`                                            | table capped (500 rows) + "showing N of M" honesty               |
| P3  | Open the same file from Conversation + Workspace + Skills | identical payload rendering                                      |
| P4  | Open a tracked artifact's old revision                    | banner "Viewing revision N — M is current"; content doesn't swap |
| P5  | Hover a file row → trash → confirm                        | row gone; `GET /workspace/list` no longer contains it            |
| P6  | Trash a tracked artifact → confirm                        | 409 surfaces "tracked … untrack first" — not raw JSON            |
| P7  | Trash a dir → confirm copy mentions recursive             | dir + children gone                                              |
| P8  | Delete the file currently open in preview                 | panel closes, listing refreshes                                  |
| P9  | Skills Studio preview                                     | delete/track-history buttons absent (no `onDeleted`)             |
| P10 | Click card for a file already deleted on disk             | "File not found" state — not raw `404: {...}`                    |


## 5. Regression guards (the two fixed bugs — highest value)

- **U5/U6** cover the optimistic-send thumb flash and reload-attachment-loss
fixes. They have no automated guard — if any step fails, it's a regression.
- After any `Conversation.tsx` change: `cd frontend && npm run build` must
pass (`tsc -b` catches type drift `tsc --noEmit` misses — the merged fix
`e409c72` was exactly this).

## 6. Gate commands (run all, all must pass)

```bash
cd backend  && uv run ruff check src/ tests/ \
            && uv run ruff format --check src/ tests/ \
            && uv run pytest -v --tb=short
cd frontend && npm run lint && npm run build && npx vitest run
```

## 7. Report format

Emit a table: `case | PASS|FAIL | actual`. For FAIL include the response
body or `browser_evaluate` result. Sev-1 (containment breach, data loss,
artifact revision orphaned) blocks; sev-2 (wrong render, missing honesty
flag) gets filed to W11.

## Known-ok (don't flag)

- Office previews render structure, not layout — W12 adds the LibreOffice
rendered tier.
- PDF/image attachments can't be edited — inspect-only by design.
- `naturalWidth` probe needs a *real* PNG — a `.png` fetched through the
Vite dev server can return SPA HTML (dotdirs aren't served). Inline base64.

