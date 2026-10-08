FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends fonts-noto-cjk tzdata && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY quota_display ./quota_display
USER 65534:65534
EXPOSE 8486
CMD ["python", "-m", "quota_display.server", "--host", "0.0.0.0", "--input", "/data/quota/quota.json"]
