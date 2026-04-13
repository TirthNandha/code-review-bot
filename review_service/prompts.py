"""prompts.py

All prompt text sent to the LLM lives here.
SYSTEM_PROMPT sets the model's role and output contract.
build_user_prompt() injects a specific diff chunk into the user turn.
"""

from review_service.models import ReviewResponse

SYSTEM_PROMPT: str = """\
You are an expert code reviewer. Your job is to review a git diff chunk and \
report any issues you find.

Focus areas (in priority order):
1. **Security** — injection, hardcoded secrets, auth bypass, path traversal
2. **Bugs** — null/None dereference, off-by-one, race conditions, wrong logic
3. **Performance** — unnecessary allocations in hot paths, O(n²) when O(n) is possible
4. **Style** — naming, dead code, missing type hints, unclear intent

Rules:
- Only report issues that appear in the ADDED (+) lines of the diff. \
Never flag removed (-) or context lines.
- Each issue must reference the exact filename and line number from the diff.
- If the chunk looks clean, return an empty issues list.
- Be precise. Do not speculate about code outside the diff.

You MUST respond with a single JSON object matching this schema — \
no markdown fences, no prose before or after:

""" + ReviewResponse.model_json_schema().__repr__() + """

Example of a valid response with no issues:
{"issues": []}
"""


def build_user_prompt(filename: str, chunk_body: str) -> str:
    """Build the user-turn message for a single diff chunk.

    Args:
        filename: Relative path of the file being reviewed.
        chunk_body: The raw diff hunk text (including +/- lines and @@ header).

    Returns:
        A formatted string ready to be sent as the user message.
    """
    return (
        f"Review the following diff chunk from `{filename}`.\n"
        f"Report every issue you find as JSON.\n\n"
        f"```diff\n{chunk_body}\n```"
    )
