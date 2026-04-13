# LLM Code Review Bot

An automated CI/CD code review bot that uses an LLM to review every GitHub Pull Request for bugs, security vulnerabilities, performance issues, and style problems — then posts inline comments directly on the PR via the GitHub API.

## Architecture

```
┌──────────────────────┐     ┌───────────────────────────────────────────────────┐
│   GitHub Actions     │     │          Review Service (FastAPI)                 │
│                      │     │                                                   │
│  PR opened/updated   │     │  ┌──────────────┐  ┌────────────┐  ┌───────────┐  │
│         │            │     │  │ diff_chunker │→ │ llm_client │→ │ comment   │  │
│    git diff → file   │────→│  │  parse diff  │  │ call LLM   │  │ _poster   │  │
│         │            │POST │  │  into chunks │  │ per chunk  │  │ post to   │  │
│    curl POST to      │     │  └──────────────┘  └────────────┘  │ GitHub PR │  │
│    review service    │     │                                    └───────────┘  │
└──────────────────────┘     └───────────────────────────────────────────────────┘
                                        │                  │
                                        ▼                  ▼
                               ┌──────────────┐   ┌──────────────┐
                               │  OpenRouter  │   │  GitHub REST │
                               │  LLM API     │   │  API         │
                               │  (Qwen/GPT)  │   │  (PR reviews)│
                               └──────────────┘   └──────────────┘
```

### Flow

1. A developer opens (or updates) a Pull Request on GitHub.
2. The **GitHub Actions** workflow triggers automatically.
3. The runner checks out the code, runs `git diff` to extract the changes, and POSTs the diff file to the review service.
4. The **FastAPI service** receives the diff and:
   - **Parses** it into structured chunks (one per diff hunk) using `diff_chunker.py`
   - **Splits** oversized chunks so they fit within the LLM's context budget
   - **Sends** each chunk to the LLM (via OpenRouter) concurrently (capped by a semaphore)
   - **Validates** the LLM's JSON response against Pydantic models
   - **Posts** all findings as a single inline PR review via the GitHub REST API
5. The developer sees inline comments on the exact lines where issues were found.

## Project Structure

```
llm-review-bot/
├── .github/workflows/
│   └── code-review.yml        # GitHub Actions workflow — triggers on PR events,
│                               # extracts the diff, and POSTs it to the review service
├── review_service/
│   ├── __init__.py
│   ├── main.py                # FastAPI app — POST /review orchestrates the full pipeline,
│   │                          # GET /health serves as a Docker/uptime probe
│   ├── diff_chunker.py        # Parses raw unified diff text into DiffChunk dataclasses,
│   │                          # splits oversized hunks by token count
│   ├── llm_client.py          # Async HTTP client for OpenRouter's Chat Completions API,
│   │                          # sends one chunk, returns validated ReviewResponse or None
│   ├── comment_poster.py      # Posts inline review comments to a GitHub PR as a single
│   │                          # review via the GitHub REST API
│   ├── prompts.py             # System prompt (reviewer persona + JSON schema) and
│   │                          # user prompt builder for each diff chunk
│   └── models.py              # Pydantic v2 models: ReviewIssue (single finding) and
│                               # ReviewResponse (top-level envelope the LLM must return)
├── eval/
│   ├── evaluate.py            # Offline evaluation harness — runs diffs through the LLM,
│   │                          # computes precision/recall/F1/FPR by category.
│   │                          # Also generates synthetic test PRs via GitHub API.
│   ├── ground_truth.json      # 5 labelled test cases (TP, FP, FN mix) with expected issues
│   └── results.json           # Output of the last evaluation run (auto-generated)
├── Dockerfile                 # Builds the FastAPI service into a Python 3.12 slim image
├── docker-compose.yml         # Runs the service container with env vars and health checks
├── requirements.txt           # Pinned Python dependencies
├── .env.example               # Template for required environment variables
└── .env                       # Your actual secrets (gitignored, never committed)
```

## Tech Stack

| Component | Technology |
|-----------|------------|
| Web framework | FastAPI 0.115 |
| HTTP client | httpx 0.28 (async) |
| LLM provider | OpenRouter (free-tier models like `qwen/qwen3-coder:free`) |
| Data validation | Pydantic v2 |
| Token counting | tiktoken |
| Containerization | Docker + Docker Compose |
| CI/CD | GitHub Actions |
| Code hosting API | GitHub REST API v3 |

## Prerequisites

- **Python 3.12+**
- **Docker** and **Docker Compose** (v2)
- An **OpenRouter API key** (free at [openrouter.ai/settings/keys](https://openrouter.ai/settings/keys))
- A **GitHub Personal Access Token** (classic) with `repo` scope ([github.com/settings/tokens](https://github.com/settings/tokens))
- **ngrok** (for exposing local service to GitHub Actions during development)

## Setup & Running Locally

### 1. Clone and configure environment

```bash
git clone https://github.com/YOUR_USERNAME/code-review-bot.git
cd code-review-bot/llm-review-bot

cp .env.example .env
# Edit .env and fill in your OPENROUTER_API_KEY and GITHUB_TOKEN
```

### 2. Environment variables

| Variable | Description |
|----------|-------------|
| `OPENROUTER_API_KEY` | Your OpenRouter API key |
| `OPENROUTER_MODEL` | Model to use (default: `qwen/qwen3-coder:free`) |
| `OPENROUTER_MAX_TOKENS` | Max tokens per LLM response (default: `2048`) |
| `OPENROUTER_TEMPERATURE` | Sampling temperature, 0 = deterministic (default: `0`) |
| `GITHUB_TOKEN` | GitHub PAT with `repo` scope |
| `MAX_CONCURRENT_LLM_CALLS` | Concurrency cap for LLM requests (default: `3`) |
| `CHUNK_TOKEN_LIMIT` | Max tokens per diff chunk before splitting (default: `1500`) |

### 3. Run without Docker

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Start the server
uvicorn review_service.main:app --reload --port 8000

# Test health endpoint (in another terminal)
curl http://localhost:8000/health
# → {"status":"ok"}
```

### 4. Run with Docker

```bash
# Build and start
sudo docker compose up --build

# Verify
curl http://localhost:8000/health
# → {"status":"ok"}

# Check container health status
docker compose ps

# View logs
docker compose logs -f

# Stop
docker compose down
```

### 5. Test the /review endpoint manually

```bash
# Create a test diff file
cat > /tmp/test.diff << 'EOF'
diff --git a/app.py b/app.py
index aaa..bbb 100644
--- a/app.py
+++ b/app.py
@@ -1,3 +1,5 @@
 import os
+API_KEY = "sk-secret-hardcoded-key"
+password = hashlib.md5("admin").hexdigest()
 def main():
     pass
EOF

# Send to review service
curl -X POST http://localhost:8000/review \
  -F "diff_file=@/tmp/test.diff" \
  -F "pr_number=1" \
  -F "repo=octocat/hello-world" \
  -F "github_token=fake-for-now"
# → {"issues_found": N, "comments_posted": 0}
```

## Setting Up GitHub Actions (End-to-End)

### 1. Expose local service with ngrok

```bash
# Install ngrok
sudo snap install ngrok

# Authenticate
ngrok config add-authtoken YOUR_NGROK_TOKEN

# Start tunnel
ngrok http 8000
# Note the https://xxxx.ngrok-free.app URL
```

### 2. Add repository secrets

Go to your GitHub repo → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**:

| Secret name | Value |
|-------------|-------|
| `REVIEW_SERVICE_URL` | Your ngrok URL (e.g. `https://a1b2c3d4.ngrok-free.app`) |
| `GH_PAT` | Your GitHub Personal Access Token |

### 3. Trigger a review

1. Make sure Docker container is running and ngrok is forwarding
2. Create a branch, make a change, push, and open a PR
3. The workflow triggers automatically — check the **Actions** tab
4. Once complete, inline review comments appear on the PR's **Files changed** tab

## Running the Evaluation

The evaluation harness tests the bot against labelled ground-truth diffs and computes standard IR metrics.

```bash
source .venv/bin/activate

# Run evaluation against ground_truth.json
python eval/evaluate.py run
```

Output example:
```
============================================================
EVALUATION RESULTS
============================================================

Per-category breakdown:
  Category         TP   FP   FN    Prec     Rec      F1
  --------------------------------------------------
  bug               1    0    0   1.000   1.000   1.000
  security          4    0    1   1.000   0.800   0.889
  style             0    5    0   0.000   0.000   0.000

Overall:
  Precision:  0.500
  Recall:     0.833
  F1:         0.625
  FPR (clean): 0.000
  TP=5  FP=5  FN=1
============================================================
```

Results are saved to `eval/results.json`.

### Generate synthetic test PRs

Creates branches with known injected bugs and opens PRs automatically:

```bash
python eval/evaluate.py generate-prs --repo YOUR_USERNAME/test-repo --count 5
```

Bug types injected: SQL injection, hardcoded secrets, null dereference, off-by-one errors, missing auth checks.

## Issues Encountered During Development & Solutions

### 1. Docker permission denied

**Error:**
```
permission denied while trying to connect to the Docker daemon socket at
unix:///var/run/docker.sock
```

**Cause:** The current user wasn't in the `docker` group.

**Fix:**
```bash
# Quick fix
sudo docker compose up --build

# Permanent fix
sudo usermod -aG docker $USER
# Then log out and log back in
```

### 2. LLM returning `null` content — `TypeError: expected string or bytes-like object, got 'NoneType'`

**Error:**
```
File "/app/review_service/llm_client.py", line 45, in _extract_json
    match = _FENCE_RE.search(text)
TypeError: expected string or bytes-like object, got 'NoneType'
```

**Cause:** Some free-tier models on OpenRouter occasionally return `null` in the `content` field of the response's `choices` array, instead of a string.

**Fix:** Added an explicit null check before attempting to parse the content:
```python
content = body["choices"][0]["message"]["content"]
if content is None:
    logger.warning("LLM returned null content for %s — skipping", chunk.filename)
    return None
```

### 3. GitHub Actions curl timeout (exit code 28)

**Error:**
```
Error: Process completed with exit code 28.
```

**Cause:** The GitHub Actions runner couldn't reach the local review service. The ngrok tunnel was either not running, had expired, or the URL in the `REVIEW_SERVICE_URL` secret was outdated (ngrok generates a new URL every restart on the free tier).

**Fix:**
- Ensure ngrok is running before triggering the workflow
- Update the `REVIEW_SERVICE_URL` secret in GitHub whenever ngrok restarts
- Verify the tunnel works first: `curl https://YOUR-NGROK-URL.ngrok-free.app/health`

### 4. GitHub Actions curl exit code 22 (HTTP 500)

**Error:**
```
Error: Process completed with exit code 22.
```

**Cause:** The review service received the request but crashed during processing (the `null` content bug above), returning HTTP 500 to curl. curl's `-f` flag converts HTTP errors into non-zero exit codes.

**Fix:** Same as issue #2 — the null content fix resolved the crash, which eliminated the 500 response.

### 5. `docker compose ps` — "no configuration file provided"

**Error:**
```
no configuration file provided: not found
```

**Cause:** Running `docker compose ps` from the wrong directory. Docker Compose looks for `docker-compose.yml` in the current working directory.

**Fix:** `cd` into the `llm-review-bot/` directory (where `docker-compose.yml` lives) before running any `docker compose` commands.

### 6. OpenRouter JSON mode compatibility

**Issue:** The initial implementation used OpenAI's `response_format: {"type": "json_object"}` parameter. Most free models on OpenRouter don't support this feature and return errors.

**Fix:**
- Removed the `response_format` parameter from the API payload
- Added `_extract_json()` helper that strips markdown code fences (`` ```json ... ``` ``) from responses, since free models often wrap their JSON output in fences despite being asked not to
- The system prompt's strict instructions handle JSON enforcement at the prompt level instead

## API Endpoints

### `GET /health`

Liveness probe. Returns `200` with:
```json
{"status": "ok"}
```

### `POST /review`

Runs the full review pipeline. Accepts `multipart/form-data`:

| Field | Type | Description |
|-------|------|-------------|
| `diff_file` | file | Raw unified diff text file |
| `pr_number` | int | Pull request number |
| `repo` | string | Repository in `owner/repo` format |
| `github_token` | string | GitHub PAT with `repo` scope |

Returns:
```json
{
  "issues_found": 3,
  "comments_posted": 3
}
```

## License

MIT
