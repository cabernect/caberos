# Copilot instructions for CaberOS

Standing instructions for GitHub Copilot when reviewing pull requests or suggesting
code in this repository.

## What CaberOS is

A local-first AI Agent Operating System. Python 3.12 + FastAPI backend, React 19 +
Vite dashboard, Tauri 2 desktop shell. The defining property is that **every
capability an agent invokes crosses one mediated boundary** — `syscall/mediator.py`
— which resolves identity, checks the grant, applies the approval gate, injects
credentials, executes, and writes an audit record. Changes that let a capability
reach the outside world without crossing that boundary are architectural
regressions, not style issues.

Read `AGENTS.md` for the module layout and the numbered design decisions (D1-D40),
and `docs/platform-support.md` for the platform tier contract.

## Code review format

Structure every review this way. Consistency matters more than length.

### 1. Summary

What the PR does in two or three sentences, then one explicit verdict:
**approve** / **changes recommended** / **blocked**. Say which, do not imply it.

### 2. Per-file findings

Group by file. For each finding give all five of these:

- **What happens** — the observable defect. Not a restatement of the diff.
- **Root cause** — why the code produces it.
- **Impact** — who hits it, on which platform, OS locale, Node/Python version or
  input, and how badly. "Could break" is not impact; name the condition.
- **Proposed fix** — concrete, ideally a diff or exact replacement line.
- **Confidence** — high / medium / low. Say plainly when you are inferring rather
  than certain.

### 3. Cross-cutting concerns

Anything that spans files: public contracts, DB schema and migrations, CI and
release wiring, the syscall boundary, credential handling, platform assumptions.

### 4. What you did not check

State the blind spots explicitly — files skipped, paths you could not reason
about, behaviour that needs a runtime to verify. Silence reads as coverage and is
worse than an admission.

## Review depth

Prefer a thorough pass over a fast one. Reviewing a subset of changed files and
reporting a verdict as if the whole diff were covered is the failure mode to
avoid — if files were skipped, say so under section 4.

Report a real defect even when the PR is otherwise strong. Equally, write "no
issues found" rather than inventing minor nits to appear thorough; a review padded
with cosmetic comments buries the finding that mattered.

## What this codebase gets wrong repeatedly

Weight these higher than generic style feedback. Every one has actually shipped
here at least once:

- **Platform-conditional file reads.** Python's `open()` and `Path.read_text()`
  default to the *locale* encoding — cp1252 on Windows. Bundled text carrying
  em-dashes silently corrupts. Always require explicit `encoding="utf-8"`.
- **Capability name vs implementation name.** The registered capability is
  `terminal`; the function is `shell_run`. Granting or invoking the function name
  silently denies the call.
- **Relative imports in packaged entry points.** PyInstaller runs the entry script
  as `__main__` with no parent package, so `from .x import y` raises at startup.
- **`--add-data` separator.** `:` on POSIX, `;` on Windows. The wrong one does not
  error — it silently omits the data.
- **Unconditional sandbox binds.** `--ro-bind` on a path that may not exist (e.g.
  `/lib64` on arm64/musl) makes bwrap fail to start, which the probe then reports
  as "no sandbox available".
- **The updater manifest.** `latest.json` lives at one fixed URL and holds every
  platform key. Anything that writes it per-platform silently strands the other
  platform's users on their current version, with no error anywhere.
- **Escape sequences in generated text.** Content written through non-raw strings
  turns `\t`, `\v`, `\r`, `\b` into control bytes. Flag stray control characters
  in committed files.

## Conventions

- Python: ruff for lint and format; type hints on new code; tests under
  `backend/tests/`
- TypeScript: `tsc --noEmit` must pass; oxlint for lint
- Commits: conventional format. **No AI attribution, co-author trailers, or
  session links** in commit messages, PR bodies, or code comments.
- Never suggest committing secrets, `.env` files, tokens, or credentials.
