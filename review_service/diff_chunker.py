"""diff_chunker.py

Parses a raw unified-diff string into structured DiffChunk objects.
Provides chunk_by_token_limit() to split oversized hunks so each one
stays within the LLM context budget.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

import tiktoken
from dotenv import load_dotenv

load_dotenv()

CHUNK_TOKEN_LIMIT: int = int(os.getenv("CHUNK_TOKEN_LIMIT", "3000"))

_HUNK_HEADER_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
_FILE_HEADER_RE = re.compile(r"^diff --git a/.+ b/(.+)$")

_encoder: tiktoken.Encoding | None = None


def _get_encoder() -> tiktoken.Encoding:
    """Lazy-load the tokenizer (avoids import-time network call)."""
    global _encoder
    if _encoder is None:
        _encoder = tiktoken.encoding_for_model("gpt-4o")
    return _encoder


def _count_tokens(text: str) -> int:
    """Return the token count for *text* using the GPT-4o tokenizer."""
    return len(_get_encoder().encode(text))


@dataclass
class DiffChunk:
    """One reviewable unit of a diff — a single hunk (or part of one)."""

    filename: str
    hunk_header: str
    lines: list[str] = field(default_factory=list)
    start_line: int = 1

    @property
    def body(self) -> str:
        """The hunk header + all diff lines joined as a single string."""
        return self.hunk_header + "\n" + "\n".join(self.lines)


def parse_diff(raw_diff: str) -> list[DiffChunk]:
    """Parse a raw unified diff into a list of DiffChunks.

    Args:
        raw_diff: The full output of `git diff` (may contain multiple files).

    Returns:
        A list of DiffChunk objects, one per hunk.
    """
    chunks: list[DiffChunk] = []
    current_file: str = ""
    current_chunk: DiffChunk | None = None

    for line in raw_diff.splitlines():
        file_match = _FILE_HEADER_RE.match(line)
        if file_match:
            if current_chunk and current_chunk.lines:
                chunks.append(current_chunk)
                current_chunk = None
            current_file = file_match.group(1)
            continue

        hunk_match = _HUNK_HEADER_RE.match(line)
        if hunk_match:
            if current_chunk and current_chunk.lines:
                chunks.append(current_chunk)
            current_chunk = DiffChunk(
                filename=current_file,
                hunk_header=line,
                start_line=int(hunk_match.group(1)),
            )
            continue

        if current_chunk is not None:
            current_chunk.lines.append(line)

    if current_chunk and current_chunk.lines:
        chunks.append(current_chunk)

    return chunks


def chunk_by_token_limit(
    chunks: list[DiffChunk],
    max_tokens: int = CHUNK_TOKEN_LIMIT,
) -> list[DiffChunk]:
    """Split any DiffChunks whose body exceeds *max_tokens*.

    Oversized hunks are split into consecutive sub-chunks, each staying
    under the token budget.  The hunk_header is repeated in every sub-chunk
    so the LLM always has context.  start_line is adjusted for each split.

    Args:
        chunks:     Output of parse_diff().
        max_tokens: Maximum tokens per chunk body.

    Returns:
        A new list where every chunk is ≤ max_tokens.
    """
    result: list[DiffChunk] = []

    for chunk in chunks:
        if _count_tokens(chunk.body) <= max_tokens:
            result.append(chunk)
            continue

        sub_lines: list[str] = []
        sub_start: int = chunk.start_line
        current_new_line: int = chunk.start_line

        for line in chunk.lines:
            candidate = chunk.hunk_header + "\n" + "\n".join(sub_lines + [line])
            if sub_lines and _count_tokens(candidate) > max_tokens:
                result.append(DiffChunk(
                    filename=chunk.filename,
                    hunk_header=chunk.hunk_header,
                    lines=list(sub_lines),
                    start_line=sub_start,
                ))
                sub_lines = [line]
                sub_start = current_new_line
            else:
                sub_lines.append(line)

            if not line.startswith("-"):
                current_new_line += 1

        if sub_lines:
            result.append(DiffChunk(
                filename=chunk.filename,
                hunk_header=chunk.hunk_header,
                lines=sub_lines,
                start_line=sub_start,
            ))

    return result
