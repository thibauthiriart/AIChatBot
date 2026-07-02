from __future__ import annotations

from server.app.config import get_settings
from server.app.db import db
from server.app.ingest import _to_vector
from server.app.openai_client import embed_texts


async def retrieve_context(site_id: str, question: str) -> list[dict]:
    settings = get_settings()
    query_embedding = (await embed_texts([question]))[0]
    async with db.acquire() as connection:
        rows = await connection.fetch(
            """
            SELECT
              chunks.content,
              documents.url,
              documents.title,
              1 - (chunks.embedding <=> $2::vector) AS score
            FROM chunks
            JOIN documents ON documents.id = chunks.document_id
            WHERE chunks.site_id = $1::uuid
            ORDER BY chunks.embedding <=> $2::vector
            LIMIT $3
            """,
            site_id,
            _to_vector(query_embedding),
            settings.chat_max_context_chunks,
        )
    return [dict(row) for row in rows if float(row["score"]) >= settings.chat_min_relevance]
