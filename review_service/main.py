# main.py
# FastAPI application entry point.
# Exposes POST /review (accepts diff + PR metadata, orchestrates chunker → LLM → comment poster)
# and GET /health (used by Docker health checks and the Actions workflow to confirm the service is live).
