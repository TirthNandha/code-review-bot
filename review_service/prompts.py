# prompts.py
# Holds all prompt text sent to the LLM.
# SYSTEM_PROMPT instructs GPT-4o to act as a code reviewer and reply with
# a strict JSON structure (no prose, no markdown fences).
# build_user_prompt(chunk) injects the diff hunk text into the user turn
# so the model knows exactly which code to review.
