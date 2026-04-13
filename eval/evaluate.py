"""evaluate.py

Offline evaluation harness for the review bot.
Loads ground_truth.json, runs each diff through the review pipeline,
then computes precision, recall, F1, and false-positive rate per issue category.
Also contains a helper to programmatically create synthetic test PRs via the GitHub API.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from collections import defaultdict
from pathlib import Path

import httpx
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from review_service.diff_chunker import chunk_by_token_limit, parse_diff
from review_service.llm_client import review_chunk
from review_service.models import ReviewIssue

load_dotenv()

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s")

GROUND_TRUTH_PATH: Path = Path(__file__).parent / "ground_truth.json"
GITHUB_API: str = "https://api.github.com"


def _issues_match(expected: dict, actual: ReviewIssue, line_tolerance: int = 3) -> bool:
    """Check if an LLM-found issue matches a ground-truth issue.

    Matching criteria:
      - Same filename
      - Same category
      - Line number within ±line_tolerance

    Args:
        expected:       One entry from ground_truth expected_issues.
        actual:         A ReviewIssue returned by the LLM.
        line_tolerance: Allowed line-number drift.

    Returns:
        True if the issues match.
    """
    if expected["filename"] != actual.filename:
        return False
    if expected["category"] != actual.category.value:
        return False
    if abs(expected["line_number"] - actual.line_number) > line_tolerance:
        return False
    return True

async def _review_diff(raw_diff: str) -> list[ReviewIssue]:
    """Run the full chunk → LLM pipeline on a raw diff string.

    Args:
        raw_diff: The unified diff text.

    Returns:
        Flat list of ReviewIssues found by the LLM.
    """
    chunks = chunk_by_token_limit(parse_diff(raw_diff))
    results = await asyncio.gather(*[review_chunk(c) for c in chunks])
    issues: list[ReviewIssue] = []
    for resp in results:
        if resp is not None:
            issues.extend(resp.issues)
    return issues


async def evaluate() -> dict:
    """Run evaluation on all ground-truth entries and print metrics.

    Returns:
        Dict with overall and per-category precision, recall, F1, and FPR.
    """
    with open(GROUND_TRUTH_PATH) as f:
        ground_truth: list[dict] = json.load(f)

    tp_by_cat: dict[str, int] = defaultdict(int)
    fp_by_cat: dict[str, int] = defaultdict(int)
    fn_by_cat: dict[str, int] = defaultdict(int)
    total_clean_chunks: int = 0
    false_positives_on_clean: int = 0

    for entry in ground_truth:
        entry_id = entry["id"]
        expected_issues: list[dict] = entry["expected_issues"]
        logger.info("Evaluating %s ...", entry_id)

        actual_issues = await _review_diff(entry["diff"])
        logger.info("  LLM found %d issue(s), expected %d", len(actual_issues), len(expected_issues))

        matched_expected: set[int] = set()
        matched_actual: set[int] = set()

        for ei, exp in enumerate(expected_issues):
            for ai, act in enumerate(actual_issues):
                if ai not in matched_actual and _issues_match(exp, act):
                    tp_by_cat[exp["category"]] += 1
                    matched_expected.add(ei)
                    matched_actual.add(ai)
                    break

        for ei, exp in enumerate(expected_issues):
            if ei not in matched_expected:
                fn_by_cat[exp["category"]] += 1
                logger.info("  FN: %s", exp["description"])

        for ai, act in enumerate(actual_issues):
            if ai not in matched_actual:
                fp_by_cat[act.category.value] += 1
                logger.info("  FP: [%s] %s", act.category.value, act.message)

        if not expected_issues:
            total_clean_chunks += 1
            false_positives_on_clean += len(actual_issues)

    all_categories = set(tp_by_cat) | set(fp_by_cat) | set(fn_by_cat)
    results: dict = {"per_category": {}, "overall": {}}

    total_tp = sum(tp_by_cat.values())
    total_fp = sum(fp_by_cat.values())
    total_fn = sum(fn_by_cat.values())

    for cat in sorted(all_categories):
        tp, fp, fn = tp_by_cat[cat], fp_by_cat[cat], fn_by_cat[cat]
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
        results["per_category"][cat] = {
            "tp": tp, "fp": fp, "fn": fn,
            "precision": round(precision, 3),
            "recall": round(recall, 3),
            "f1": round(f1, 3),
        }

    overall_prec = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0.0
    overall_rec = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0.0
    overall_f1 = (
        2 * overall_prec * overall_rec / (overall_prec + overall_rec)
        if (overall_prec + overall_rec) > 0 else 0.0
    )
    fpr = (
        false_positives_on_clean / total_clean_chunks
        if total_clean_chunks > 0 else 0.0
    )

    results["overall"] = {
        "tp": total_tp, "fp": total_fp, "fn": total_fn,
        "precision": round(overall_prec, 3),
        "recall": round(overall_rec, 3),
        "f1": round(overall_f1, 3),
        "false_positive_rate_on_clean": round(fpr, 3),
    }

    return results


def _print_results(results: dict) -> None:
    """Pretty-print evaluation results to stdout.

    Args:
        results: The dict returned by evaluate().
    """
    print("\n" + "=" * 60)
    print("EVALUATION RESULTS")
    print("=" * 60)

    print("\nPer-category breakdown:")
    print(f"  {'Category':<14} {'TP':>4} {'FP':>4} {'FN':>4} {'Prec':>7} {'Rec':>7} {'F1':>7}")
    print("  " + "-" * 50)
    for cat, m in results["per_category"].items():
        print(f"  {cat:<14} {m['tp']:>4} {m['fp']:>4} {m['fn']:>4}"
              f" {m['precision']:>7.3f} {m['recall']:>7.3f} {m['f1']:>7.3f}")

    o = results["overall"]
    print(f"\nOverall:")
    print(f"  Precision:  {o['precision']:.3f}")
    print(f"  Recall:     {o['recall']:.3f}")
    print(f"  F1:         {o['f1']:.3f}")
    print(f"  FPR (clean): {o['false_positive_rate_on_clean']:.3f}")
    print(f"  TP={o['tp']}  FP={o['fp']}  FN={o['fn']}")
    print("=" * 60)

SYNTHETIC_BUGS: list[dict] = [
    {
        "filename": "src/db/queries.py",
        "content": 'import sqlite3\n\ndef get_user(uid):\n    conn = sqlite3.connect("app.db")\n    return conn.execute(f"SELECT * FROM users WHERE id = \'{uid}\'").fetchone()\n',
        "bug_type": "sql_injection",
    },
    {
        "filename": "src/config.py",
        "content": 'AWS_ACCESS_KEY = "AKIAIOSFODNN7EXAMPLE"\nAWS_SECRET_KEY = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"\n',
        "bug_type": "hardcoded_secret",
    },
    {
        "filename": "src/api/users.py",
        "content": 'def get_name(user):\n    return user["profile"]["name"].lower()\n',
        "bug_type": "null_deref",
    },
    {
        "filename": "src/utils/pagination.py",
        "content": 'def paginate(items, page, size=10):\n    start = page * size + 1\n    return items[start:start+size]\n',
        "bug_type": "off_by_one",
    },
    {
        "filename": "src/api/admin.py",
        "content": 'from fastapi import APIRouter\nrouter = APIRouter()\n\n@router.delete("/users/{uid}")\nasync def delete_user(uid: int):\n    db.execute(f"DELETE FROM users WHERE id={uid}")\n    return {"ok": True}\n',
        "bug_type": "missing_auth",
    },
]


async def create_synthetic_prs(
    repo: str,
    base_branch: str = "main",
    github_token: str | None = None,
    count: int = 20,
) -> list[str]:
    """Create synthetic test PRs with known injected bugs.

    Creates `count` PRs by cycling through SYNTHETIC_BUGS. Each PR gets
    one bug file committed to a new branch, then a PR is opened.

    Args:
        repo:         GitHub repository in "owner/repo" format.
        base_branch:  Branch to open PRs against.
        github_token: PAT with repo scope. Falls back to GITHUB_TOKEN env var.
        count:        Number of PRs to create.

    Returns:
        List of PR URLs created.
    """
    token = github_token or os.getenv("GITHUB_TOKEN", "")
    if not token:
        raise ValueError("GITHUB_TOKEN is required")

    headers: dict[str, str] = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    async with httpx.AsyncClient(timeout=30.0, headers=headers) as client:
        base_resp = await client.get(f"{GITHUB_API}/repos/{repo}/git/ref/heads/{base_branch}")
        base_resp.raise_for_status()
        base_sha: str = base_resp.json()["object"]["sha"]

        pr_urls: list[str] = []

        for i in range(count):
            bug = SYNTHETIC_BUGS[i % len(SYNTHETIC_BUGS)]
            branch_name = f"eval/synthetic-{bug['bug_type']}-{i:03d}"

            ref_resp = await client.post(
                f"{GITHUB_API}/repos/{repo}/git/refs",
                json={"ref": f"refs/heads/{branch_name}", "sha": base_sha},
            )
            if ref_resp.status_code == 422:
                logger.warning("Branch %s already exists, skipping", branch_name)
                continue
            ref_resp.raise_for_status()

            import base64
            encoded = base64.b64encode(bug["content"].encode()).decode()
            file_resp = await client.put(
                f"{GITHUB_API}/repos/{repo}/contents/{bug['filename']}",
                json={
                    "message": f"eval: inject {bug['bug_type']} bug (#{i})",
                    "content": encoded,
                    "branch": branch_name,
                },
            )
            file_resp.raise_for_status()

            pr_resp = await client.post(
                f"{GITHUB_API}/repos/{repo}/pulls",
                json={
                    "title": f"[Eval] Synthetic bug: {bug['bug_type']} (#{i})",
                    "body": f"Auto-generated for evaluation.\nBug type: `{bug['bug_type']}`\nFile: `{bug['filename']}`",
                    "head": branch_name,
                    "base": base_branch,
                },
            )
            pr_resp.raise_for_status()
            pr_url = pr_resp.json()["html_url"]
            pr_urls.append(pr_url)
            logger.info("Created PR %d/%d: %s", i + 1, count, pr_url)

        return pr_urls

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Evaluate the LLM code review bot")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("run", help="Run evaluation against ground_truth.json")

    gen_parser = sub.add_parser("generate-prs", help="Create synthetic test PRs")
    gen_parser.add_argument("--repo", required=True, help="owner/repo")
    gen_parser.add_argument("--base", default="main", help="Base branch (default: main)")
    gen_parser.add_argument("--count", type=int, default=20, help="Number of PRs (default: 20)")

    args = parser.parse_args()

    if args.command == "run":
        results = asyncio.run(evaluate())
        _print_results(results)
        out_path = Path(__file__).parent / "results.json"
        with open(out_path, "w") as f:
            json.dump(results, f, indent=2)
        print(f"\nResults saved to {out_path}")

    elif args.command == "generate-prs":
        urls = asyncio.run(create_synthetic_prs(repo=args.repo, base_branch=args.base, count=args.count))
        print(f"\nCreated {len(urls)} PR(s)")

    else:
        parser.print_help()
