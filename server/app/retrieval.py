from __future__ import annotations

import re
import unicodedata

from server.app.config import get_settings
from server.app.db import db

_STOPWORDS = {
    "a",
    "ai",
    "ai-je",
    "au",
    "aux",
    "avec",
    "bonjour",
    "bonsoir",
    "ce",
    "ces",
    "cette",
    "combien",
    "comment",
    "dans",
    "de",
    "des",
    "du",
    "elle",
    "est",
    "et",
    "il",
    "je",
    "la",
    "le",
    "les",
    "leur",
    "leurs",
    "ma",
    "me",
    "mes",
    "mon",
    "ne",
    "nos",
    "notre",
    "nous",
    "on",
    "ou",
    "par",
    "pas",
    "plus",
    "pour",
    "pouvez",
    "puis",
    "que",
    "quel",
    "quelle",
    "quelles",
    "quels",
    "qui",
    "savoir",
    "se",
    "ses",
    "si",
    "site",
    "son",
    "sur",
    "ta",
    "te",
    "tes",
    "ton",
    "tu",
    "un",
    "une",
    "vos",
    "votre",
    "voudrais",
    "aimerai",
    "aimerais",
    "durer",
}


async def retrieve_context(site_id: str, question: str) -> list[dict]:
    settings = get_settings()
    async with db.acquire() as connection:
        rows = await connection.fetch(
            """
            SELECT
              chunks.content,
              documents.url,
              documents.title,
              chunks.chunk_index
            FROM chunks
            JOIN documents ON documents.id = chunks.document_id
            WHERE chunks.site_id = $1::uuid
            ORDER BY documents.updated_at DESC, chunks.chunk_index ASC
            """,
            site_id,
        )

    scored_rows = []
    question_tokens = _extract_keywords(question)
    normalized_question = _normalize(question)

    for row in rows:
        item = dict(row)
        score = _score_chunk(normalized_question, question_tokens, item["content"], item["title"])
        if score <= 0:
            continue
        item["score"] = score
        scored_rows.append(item)

    scored_rows.sort(key=lambda item: (-float(item["score"]), int(item["chunk_index"])))
    return scored_rows[: settings.chat_max_context_chunks]


def _score_chunk(question: str, question_tokens: list[str], content: str, title: str) -> float:
    haystack = _normalize(f"{title} {content}")
    if not haystack:
        return 0.0

    score = 0.0
    for token in question_tokens:
        if token in haystack:
            score += 2.0

    for bigram in _bigrams(question_tokens):
        if " ".join(bigram) in haystack:
            score += 3.0

    if question and question in haystack:
        score += 6.0

    return score


def _extract_keywords(text: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9]+", _normalize(text))
    keywords: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        if len(token) < 3 or token in _STOPWORDS:
            continue
        if token not in seen:
            keywords.append(token)
            seen.add(token)
    return keywords


def _bigrams(tokens: list[str]) -> list[tuple[str, str]]:
    return [(tokens[index], tokens[index + 1]) for index in range(len(tokens) - 1)]


def _normalize(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", ascii_text.lower()).strip()
