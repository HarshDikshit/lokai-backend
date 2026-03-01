FROM python:3.11-slim

WORKDIR /app

# RUN apt-get update && apt-get install -y --no-install-recommends \
#     gcc \
#     curl \
#     && rm -rf /var/lib/apt/lists/*

# Upgrade pip first — critical to resolve pydantic-core wheels correctly
RUN pip install --no-cache-dir --upgrade pip==24.0

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p uploads/images uploads/audio uploads/verifications

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]