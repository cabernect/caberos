# Vault Document Inspection

Status: proposed. Dependencies: existing document/chunk models.

## Goal

Expose what the Vault actually stores, with bounded paging and source provenance,
without invoking extraction, rebuilding, or embeddings when opening inspection.

## Existing File Targets

- `backend/src/agentos/api/knowledge.py`
- `backend/src/agentos/models/document.py` and `models/knowledge_index.py`
- `backend/src/agentos/knowledge/retrieval.py`
- `frontend/src/pages/KnowledgeVault.tsx` and `frontend/src/lib/knowledge.ts`
- Existing knowledge API, model, ingest, and RAG tests.

## Data Honesty

`DocumentChunk` is canonical corpus state, not a generation-versioned snapshot.
`IndexGeneration` and `ChunkEmbedding` describe derived embedding state. Show
those separately; never label today's chunk text as historical generation text.

Inspection exposes persisted `kind`, parent id, sequence, heading path,
source location, page number, token count, and bounded text preview. Missing
locations remain missing. Token counts use the stored estimate, not invented
provider usage. Lexical-only chunks need no embedding to be inspectable.

## Proposed Interface

Add authenticated `GET /api/knowledge/documents/{id}/chunks` with bounded `limit`
and a deterministic sequence/id cursor. Reuse existing global/agent-scope access
rules; a caller cannot change scope to retrieve another document.

Return document id/content hash, corpus inspection version, items, next cursor,
and explicit preview truncation. If showing embedding membership, return the
requested generation identity separately and join on exact chunk ids.

Pin paging to a corpus version or reject stale cursors after re-ingest. A content
hash alone may not identify a different chunking of identical bytes; select a
version marker that reflects corpus mutation. Do not snapshot the entire corpus
merely to display a tree.

Allow bounded parent/child filtering or lazy branch loading. Parent nodes may be
absent from a page; include sufficient ancestry metadata or load them explicitly
instead of presenting children as roots.

## UI Behavior

- Open inspection from a document row; show status, content identity, and counts.
- Expand parents lazily; render text as inert text, not executable HTML.
- Show page/sheet/source coordinates only when persisted.
- Handle empty, indexing, failed, stale-page, and missing-document states.
- Selection changes cancel/ignore stale fetch results; load more never appends
  chunks from another document or corpus version.
- Support keyboard navigation and narrow layouts using existing design tokens.

## Implementation Steps

1. Define response/cursor/version contracts and add scope/paging API tests.
2. Implement bounded queries without N+1 chunk counts or accidental provider calls.
3. Add the inspection view, lazy branches, loading/error/empty states, and tests.
4. Verify active/rebuilding/failed embedding generations do not mislabel corpus
   content; add tabular inspection extensions with the row workstream.

## Acceptance

Every displayed chunk can be matched to an actual row. Paging remains coherent
across re-ingest, previews are bounded, hidden scope cannot leak, and opening the
view makes zero provider calls. Rebuild status is not a fake historical snapshot.
