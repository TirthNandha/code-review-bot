# diff_chunker.py
# Parses a raw git diff string into structured DiffChunk dataclasses.
# Each chunk captures the filename, hunk header, changed lines, and the starting
# line number so comments can later be anchored to the correct position in the PR.
# Also provides chunk_by_token_limit() to split oversized hunks before sending to the LLM.
