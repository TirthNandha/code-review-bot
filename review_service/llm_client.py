# llm_client.py
# Async client for the OpenAI Chat Completions API (called directly via httpx, no SDK).
# review_chunk() sends a single DiffChunk to GPT-4o with JSON response_format enforced
# and returns a parsed ReviewResponse (or None on any API / parse error).
