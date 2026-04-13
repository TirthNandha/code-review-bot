"""llm_client.py

Async client that sends a single DiffChunk to an OpenRouter-hosted LLM
(via httpx, no SDK) and returns a validated ReviewResponse or None on failure.
"""

from __future__ import annotations

import json
import logging
import os
import re

import httpx
from dotenv import load_dotenv

from review_service.diff_chunker import DiffChunk
from review_service.models import ReviewResponse
from review_service.prompts import SYSTEM_PROMPT, build_user_prompt

load_dotenv()

logger = logging.getLogger(__name__)

OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL: str = os.getenv("OPENROUTER_MODEL", "qwen/qwen3-coder:free")
OPENROUTER_MAX_TOKENS: int = int(os.getenv("OPENROUTER_MAX_TOKENS", "2048"))
OPENROUTER_TEMPERATURE: float = float(os.getenv("OPENROUTER_TEMPERATURE", "0"))

API_URL: str = "https://openrouter.ai/api/v1/chat/completions"
REQUEST_TIMEOUT: float = 240.0

_FENCE_RE = re.compile(r"```(?:json)?\s*\n?(.*?)\n?\s*```", re.DOTALL)


def _extract_json(text: str) -> str:
    """Strip markdown code fences if the model wrapped its JSON in them.

    Args:
        text: Raw content string from the LLM response.

    Returns:
        The inner JSON string, or the original text if no fences found.
    """
    match = _FENCE_RE.search(text)
    return match.group(1).strip() if match else text.strip()


async def review_chunk(chunk: DiffChunk) -> ReviewResponse | None:
    """Send one diff chunk to the LLM and return the parsed review.

    Args:
        chunk: A single DiffChunk produced by the diff chunker.

    Returns:
        A validated ReviewResponse, or None if the API call fails or
        the response cannot be parsed.
    """
    payload: dict = {
        "model": OPENROUTER_MODEL,
        "temperature": OPENROUTER_TEMPERATURE,
        "max_tokens": OPENROUTER_MAX_TOKENS,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(chunk.filename, chunk.body)},
        ],
    }

    headers: dict = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            response = await client.post(API_URL, json=payload, headers=headers)
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        logger.error(
            "OpenRouter API HTTP %s for %s: %s",
            exc.response.status_code, chunk.filename, exc.response.text[:300],
        )
        return None
    except httpx.RequestError as exc:
        logger.error("OpenRouter request failed for %s: %s", chunk.filename, exc)
        return None

    try:
        body = response.json()
        content = body["choices"][0]["message"]["content"]
        if content is None:
            logger.warning("LLM returned null content for %s — skipping", chunk.filename)
            return None
        cleaned = _extract_json(content)
        parsed = json.loads(cleaned)
    except (KeyError, IndexError, json.JSONDecodeError, TypeError) as exc:
        logger.error(
            "Failed to extract/parse LLM JSON for %s: %s — raw: %s",
            chunk.filename, exc, response.text[:500],
        )
        return None

    try:
        return ReviewResponse.model_validate(parsed)
    except Exception as exc:
        logger.error(
            "Pydantic validation failed for %s: %s — data: %s",
            chunk.filename, exc, parsed,
        )
        return None
