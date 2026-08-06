"""Memory module — three-layer memory architecture (D34).

Layers:
1. Working memory (session context) — handled by the harness
2. MEMORY.md — agent-curated notebook (file in agent home dir)
3. Knowledge graph — structured facts (memory_triples table)
4. Semantic recall — FTS5 (default) or embeddings (configurable)
"""
