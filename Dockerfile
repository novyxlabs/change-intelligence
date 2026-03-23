FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    HOST=0.0.0.0

WORKDIR /app

COPY pyproject.toml README.md ./
COPY change_intelligence ./change_intelligence

RUN pip install --no-cache-dir .

EXPOSE 8080

CMD ["python", "-m", "change_intelligence.server"]
