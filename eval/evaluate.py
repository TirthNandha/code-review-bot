# evaluate.py
# Offline evaluation harness for the review bot.
# Loads ground_truth.json, runs the review pipeline against each sample diff,
# then computes precision, recall, F1, and false-positive rate broken down by issue type.
# Also contains a helper to programmatically create synthetic test PRs via the GitHub API.
