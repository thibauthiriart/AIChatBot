from __future__ import annotations

import hashlib
import re
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from server.app.db import db

MAX_CHUNK_CHARS = 1200
CHUNK_OVERLAP_CHARS = 180


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _same_domain(base_url: str, url: str) -> bool:
    return urlparse(base_url).netloc == urlparse(url).netloc


def _chunk_text(text: str) -> list[str]:
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + MAX_CHUNK_CHARS, len(text))
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end == len(text):
            break
        start = max(end - CHUNK_OVERLAP_CHARS, start + 1)
    return chunks


async def fetch_page(url: str) -> tuple[str, str]:
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        response = await client.get(url, headers={"User-Agent": "AgentIAConversationIndexer/1.0"})
        response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "nav", "footer"]):
        tag.decompose()
    title = _clean_text(soup.title.string if soup.title and soup.title.string else "")
    main = soup.find("main") or soup.body or soup
    text = _clean_text(main.get_text(" "))
    return title, text


async def ingest_urls(site_id: str, urls: list[str]) -> tuple[int, int]:
    async with db.acquire() as connection:
        site = await connection.fetchrow("SELECT id, base_url FROM sites WHERE id = $1::uuid", site_id)
    if not site:
        raise ValueError("Unknown site_id")

    indexed_documents = 0
    indexed_chunks = 0
    for url in urls:
        if not _same_domain(site["base_url"], url):
            raise ValueError(f"URL outside site domain: {url}")

        title, text = await fetch_page(url)
        if len(text) < 80:
            continue

        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        chunks = _chunk_text(text)

        async with db.acquire() as connection:
            async with connection.transaction():
                has_embedding_column = await _chunks_table_has_embedding(connection)
                document_id = await connection.fetchval(
                    """
                    INSERT INTO documents(site_id, url, title, content_hash, updated_at)
                    VALUES($1::uuid, $2, $3, $4, now())
                    ON CONFLICT(site_id, url)
                    DO UPDATE SET title = EXCLUDED.title, content_hash = EXCLUDED.content_hash, updated_at = now()
                    RETURNING id
                    """,
                    site_id,
                    url,
                    title,
                    content_hash,
                )
                await connection.execute("DELETE FROM chunks WHERE document_id = $1::uuid", document_id)
                for index, chunk in enumerate(chunks):
                    if has_embedding_column:
                        await connection.execute(
                            """
                            INSERT INTO chunks(document_id, site_id, chunk_index, content, embedding)
                            VALUES($1::uuid, $2::uuid, $3, $4, $5::vector)
                            """,
                            document_id,
                            site_id,
                            index,
                            chunk,
                            _zero_vector(),
                        )
                    else:
                        await connection.execute(
                            """
                            INSERT INTO chunks(document_id, site_id, chunk_index, content)
                            VALUES($1::uuid, $2::uuid, $3, $4)
                            """,
                            document_id,
                            site_id,
                            index,
                            chunk,
                        )
        indexed_documents += 1
        indexed_chunks += len(chunks)
    return indexed_documents, indexed_chunks


async def _chunks_table_has_embedding(connection) -> bool:
    return bool(
        await connection.fetchval(
            """
            SELECT EXISTS (
              SELECT 1
              FROM information_schema.columns
              WHERE table_name = 'chunks' AND column_name = 'embedding'
            )
            """
        )
    )


def _zero_vector() -> str:
    return "[" + ",".join("0" for _ in range(1536)) + "]"
