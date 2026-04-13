"""comment_poster.py

Posts inline review comments to a GitHub PR via the GitHub REST API.
Stubbed for now — will be implemented in Step 7.
"""

from __future__ import annotations

import logging

from review_service.models import ReviewIssue

logger = logging.getLogger(__name__)


async def post_review_comments(
    issues: list[ReviewIssue],
    repo: str,
    pr_number: int,
    github_token: str,
) -> int:
    """Post review comments to a GitHub PR (stub — logs and returns 0).

    Args:
        issues:       List of ReviewIssue objects to post as inline comments.
        repo:         GitHub repository in "owner/repo" format.
        pr_number:    The PR number to comment on.
        github_token: PAT used to authenticate with the GitHub API.

    Returns:
        Number of comments successfully posted.
    """
    logger.info(
        "STUB: would post %d comment(s) to %s PR #%s",
        len(issues), repo, pr_number,
    )
    for issue in issues:
        logger.info("  [%s] %s:%d — %s", issue.severity.value, issue.filename, issue.line_number, issue.message)
    return 0
