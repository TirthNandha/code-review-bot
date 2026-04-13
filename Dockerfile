FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY review_service/ review_service/

EXPOSE 8000

CMD ["uvicorn", "review_service.main:app", "--host", "0.0.0.0", "--port", "8000"]
