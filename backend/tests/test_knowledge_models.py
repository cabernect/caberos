from agentos.models import Document, DocumentChunk


def test_document_and_chunk_models_define_knowledge_metadata():
    document_columns = set(Document.__table__.c.keys())
    chunk_columns = set(DocumentChunk.__table__.c.keys())

    assert {"source_path", "storage_path", "display_name", "content_hash", "status"} <= set(
        document_columns
    )
    assert {"document_id", "seq", "text", "heading_path", "page_number", "token_count"} <= set(
        chunk_columns
    )
