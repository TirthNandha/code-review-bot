# Dockerfile
# Builds the review_service into a minimal Python 3.12 image.
# Installs dependencies from requirements.txt, copies the service source,
# and starts uvicorn on port 8000.
# Used by docker-compose and (optionally) deployed directly to a VPS or cloud run.
