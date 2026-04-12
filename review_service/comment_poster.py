# comment_poster.py
# Posts inline review comments to a GitHub PR via the GitHub REST API.
# post_review_comments() fetches the latest commit SHA for the PR, then
# submits a single pull request review containing all LLM-generated comments
# anchored to their exact file + line positions.
# format_comment() renders each ReviewIssue as severity-emoji + markdown body.
