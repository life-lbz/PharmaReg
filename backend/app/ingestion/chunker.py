import re
from typing import Any

MAX_CHUNK_TOKENS = 512
APPROX_CHARS_PER_TOKEN = 1.5


def chunk_clause(clause_id: int, content: str, clause_no: str) -> list[dict[str, Any]]:
    max_chars = int(MAX_CHUNK_TOKENS * APPROX_CHARS_PER_TOKEN)
    if len(content) <= max_chars:
        return [{
            "clause_id": clause_id,
            "clause_no": clause_no,
            "chunk_index": 0,
            "text": content,
        }]

    sentences = re.split(r"(?<=[。；！？\n])", content)
    chunks: list[dict[str, Any]] = []
    current_chunk = ""
    chunk_index = 0

    for sentence in sentences:
        if not sentence.strip():
            continue
        if len(current_chunk) + len(sentence) > max_chars and current_chunk:
            chunks.append({
                "clause_id": clause_id,
                "clause_no": clause_no,
                "chunk_index": chunk_index,
                "text": current_chunk.strip(),
            })
            chunk_index += 1
            current_chunk = sentence
        else:
            current_chunk += sentence

    if current_chunk.strip():
        chunks.append({
            "clause_id": clause_id,
            "clause_no": clause_no,
            "chunk_index": chunk_index,
            "text": current_chunk.strip(),
        })

    return chunks
