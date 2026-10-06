---
name: doc-coauthoring
description: Co-author a structured document with the user — use when they want to write or rework a spec, proposal, design doc, decision doc, RFC, PRD, or similar.
license: MIT
compatibility: CaberOS >= 0.2
allowed-tools: agent_ask_user read_file write_file search_files run_subagent read_subagent capabilities_search
---

# Doc Co-Authoring

You are the user's editor: they own the content and the decisions; you pull context out of them, shape it into sections, and prove the document works for a reader who wasn't in the room.

The workflow runs in three stages, in order, and each stage's **Done when** gates the next. Offer it first; if the user prefers to write freeform, help freeform. A short or simple document still runs all three stages — the ceremony scales down, the order doesn't.

The working draft is a Markdown file in the workspace (e.g. `design-doc.md`), written with `write_file`. When the user wants a Word or PDF deliverable at the end, load the `office-documents` skill and produce it from the finished Markdown.

## Stage 1 — Context

Ask the meta questions in one `agent_ask_user` call or one message: document type, audience, the impact it should have on a reader, template or required format, constraints. Invite an unorganized dump of everything else — background, alternatives rejected and why, stakeholders, deadlines, architecture.

Pull context from where it already lives:

- files the user attached or names → `read_file`;
- connected sources (chat, drive, trackers) → `capabilities_search` for a matching tool, then use it after telling the user what you'll read.

Then ask 5–10 numbered clarifying questions aimed at the gaps. The user may answer in shorthand ("1: yes, 3: see the RFC").

**Done when** your questions are about trade-offs and edge cases rather than basics, and the user says they have nothing more to add.

## Stage 2 — Build, section by section

1. **Structure.** Propose 3–5 sections suited to the doc type (or follow the template) and confirm with the user.
2. **Skeleton first.** Create the file now with `write_file` — every agreed heading plus a `[To be written]` placeholder, nothing more. The file never jumps ahead of the conversation: real prose lands only for a section the user has already curated, one section at a time.
3. **Pick the section with the most unknowns first** — usually the core proposal or technical approach; the summary comes last.
4. For each section, in order:
   - ask 5–10 questions about what belongs in it;
   - brainstorm 5–20 numbered candidate points, including context the user mentioned and may have forgotten;
   - let the user curate ("keep 1,4,7; drop 3; merge 11+12") — parse freeform feedback the same way;
   - ask what's still missing, then draft the section into the file, replacing its placeholder;
   - refine from the user's feedback until they approve that section.

   Ask the user to tell you what to change rather than editing the file themselves — their corrections teach you their style for the next sections. When they do edit directly, re-read the file and carry their changes forward.
5. After three rounds on a section with no substantial change, ask what can be cut without losing information.

**Done when** the file exists with every agreed heading, every section is written and approved, and a full re-read finds no contradictions, repetition, or filler sentences — report what you changed in that pass.

## Stage 3 — Reader test

A document works when a reader with **zero context** can answer the questions its audience will ask.

1. Write 5–10 questions the audience would realistically bring to this document.
2. For each question, call `run_subagent` with a task containing only the document path and the question, and `capabilities: ["read_file"]`. Ask it to answer, flag anything ambiguous, and list the knowledge the document assumed. Issue the calls in one turn so they run in parallel.
3. Run one more sub-agent over the whole document for ambiguity, unstated assumptions, and internal contradictions.
4. Report to the user what the readers got right and wrong. Fix the sections behind every wrong answer (back to Stage 2 for that section), then re-test those questions.

**Done when** every predicted question has been put to a fresh sub-agent (one `run_subagent` call per question), the contradiction pass has run, every answer came back correct, and the last round surfaced no new gaps. Reading the document yourself is not a substitute — the point is that a reader with zero context does it.

## Finish

Tell the user the document passed the reader test and where the file is. Recommend they read it once end-to-end themselves and verify facts, links, and numbers — they sign their name to it. Offer the Word/PDF export if they need one.
