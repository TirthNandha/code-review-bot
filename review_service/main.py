"""main.py

FastAPI application entry point.
POST /review  — accepts a diff + PR metadata, orchestrates chunker → LLM → comment poster.
GET  /health  — lightweight probe for Docker health checks and uptime monitoring.
"""

from __future__ import annotations

import asyncio
import logging
import os

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import JSONResponse

from review_service.comment_poster import post_review_comments
from review_service.diff_chunker import DiffChunk, chunk_by_token_limit, parse_diff
from review_service.llm_client import review_chunk
from review_service.models import ReviewIssue, ReviewResponse

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger(__name__)

MAX_CONCURRENT_LLM_CALLS: int = int(os.getenv("MAX_CONCURRENT_LLM_CALLS", "3"))

app = FastAPI(
    title="LLM Code Review Bot",
    version="0.1.0",
)


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe. Returns 200 with a simple status payload."""
    return {"status": "ok"}


@app.post("/review")
async def review(
    diff_file: UploadFile = File(..., description="Raw unified diff text file"),
    pr_number: int = Form(..., description="Pull request number"),
    repo: str = Form(..., description="Owner/repo, e.g. 'octocat/hello-world'"),
    github_token: str = Form(..., description="GitHub PAT with repo scope"),
) -> JSONResponse:
    """Run the full review pipeline for a pull request.

    1. Parse the uploaded diff into chunks.
    2. Send each chunk to the LLM (with a concurrency cap).
    3. Collect all issues and post them as inline PR review comments.

    Args:
        diff_file:    Uploaded text file containing the raw `git diff` output.
        pr_number:    The PR number to comment on.
        repo:         GitHub repository in "owner/repo" format.
        github_token: PAT used to post review comments.

    Returns:
        JSON summary of how many issues were found and posted.
    """
    raw_diff: str = (await diff_file.read()).decode()
    logger.info("Received diff for %s PR #%s (%d chars)", repo, pr_number, len(raw_diff))

    chunks: list[DiffChunk] = chunk_by_token_limit(parse_diff(raw_diff))
    logger.info("Parsed %d chunk(s)", len(chunks))

    if not chunks:
        return JSONResponse({"issues_found": 0, "comments_posted": 0, "detail": "Empty diff"})

    semaphore = asyncio.Semaphore(MAX_CONCURRENT_LLM_CALLS)

    async def _limited_review(chunk: DiffChunk) -> ReviewResponse | None:
        async with semaphore:
            return await review_chunk(chunk)

    results: list[ReviewResponse | None] = await asyncio.gather(
        *[_limited_review(c) for c in chunks]
    )

    all_issues: list[ReviewIssue] = []
    for resp in results:
        if resp is not None:
            all_issues.extend(resp.issues)

    logger.info("LLM returned %d issue(s) across %d chunk(s)", len(all_issues), len(chunks))

    comments_posted: int = 0
    if all_issues:
        comments_posted = await post_review_comments(
            issues=all_issues,
            repo=repo,
            pr_number=pr_number,
            github_token=github_token,
        )

    return JSONResponse({
        "issues_found": len(all_issues),
        "comments_posted": comments_posted,
    })
