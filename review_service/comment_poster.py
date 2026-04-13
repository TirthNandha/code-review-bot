"""comment_poster.py

Posts inline review comments to a GitHub PR via the GitHub REST API.
Uses the "Create a pull request review" endpoint so all comments appear
as a single review (not individual comment spam).
"""

from __future__ import annotations

import logging

import httpx

from review_service.models import ReviewIssue, Severity

logger = logging.getLogger(__name__)

GITHUB_API: str = "https://api.github.com"
REQUEST_TIMEOUT: float = 30.0

_SEVERITY_EMOJI: dict[Severity, str] = {
    Severity.critical: "\U0001f6a8",  # 🚨
    Severity.high:     "\u26a0\ufe0f",  # ⚠️
    Severity.medium:   "\U0001f536",  # 🔶
    Severity.low:      "\U0001f4ac",  # 💬
}


def format_comment(issue: ReviewIssue) -> str:
    """Render a ReviewIssue as a markdown comment body.

    Args:
        issue: A single ReviewIssue from the LLM.

    Returns:
        Markdown string with severity emoji, message, and suggestion.
    """
    emoji = _SEVERITY_EMOJI.get(issue.severity, "\u2753")
    return (
        f"{emoji} **{issue.severity.value.upper()}** | {issue.category.value}\n\n"
        f"{issue.message}\n\n"
        f"**Suggestion:** {issue.suggestion}"
    )


async def _get_pr_head_sha(
    repo: str,
    pr_number: int,
    headers: dict[str, str],
) -> str | None:
    """Fetch the HEAD commit SHA of a pull request.

    The GitHub Reviews API requires a commit_id to anchor inline comments.

    Args:
        repo:    GitHub repository in "owner/repo" format.
        pr_number: The PR number.
        headers: Auth + accept headers for the GitHub API.

    Returns:
        The 40-char SHA string, or None on failure.
    """
    url = f"{GITHUB_API}/repos/{repo}/pulls/{pr_number}"
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            return resp.json()["head"]["sha"]
    except (httpx.HTTPStatusError, httpx.RequestError, KeyError) as exc:
        logger.error("Failed to fetch PR head SHA for %s #%s: %s", repo, pr_number, exc)
        return None


async def post_review_comments(
    issues: list[ReviewIssue],
    repo: str,
    pr_number: int,
    github_token: str,
) -> int:
    """Post all review issues as a single PR review with inline comments.

    Uses POST /repos/{owner}/{repo}/pulls/{pull_number}/reviews which
    creates one review containing all comments — much cleaner than
    posting individual comments.

    Args:
        issues:       List of ReviewIssue objects to post as inline comments.
        repo:         GitHub repository in "owner/repo" format.
        pr_number:    The PR number to comment on.
        github_token: PAT used to authenticate with the GitHub API.

    Returns:
        Number of comments successfully posted (0 if the API call fails).
    """
    if not issues:
        return 0

    headers: dict[str, str] = {
        "Authorization": f"Bearer {github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    commit_sha = await _get_pr_head_sha(repo, pr_number, headers)
    if not commit_sha:
        return 0

    comments: list[dict] = []
    for issue in issues:
        comments.append({
            "path": issue.filename,
            "line": issue.line_number,
            "side": "RIGHT",
            "body": format_comment(issue),
        })

    review_payload: dict = {
        "commit_id": commit_sha,
        "event": "COMMENT",
        "body": f"\U0001f916 **LLM Code Review** — found {len(issues)} issue(s)",
        "comments": comments,
    }

    url = f"{GITHUB_API}/repos/{repo}/pulls/{pr_number}/reviews"
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            resp = await client.post(url, json=review_payload, headers=headers)
            resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        logger.error(
            "GitHub review API HTTP %s for %s #%s: %s",
            exc.response.status_code, repo, pr_number, exc.response.text[:500],
        )
        return 0
    except httpx.RequestError as exc:
        logger.error("GitHub review request failed for %s #%s: %s", repo, pr_number, exc)
        return 0

    logger.info("Posted review with %d comment(s) to %s #%s", len(comments), repo, pr_number)
    return len(comments)
