FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN groupadd -r -g 10001 novel \
    && useradd -r -u 10001 -g novel novel

# Dependencies first so code changes do not reinstall the world,
# pinned to the same uv.lock the quality gates approve.
COPY pyproject.toml uv.lock README.md ./
RUN pip install --no-cache-dir uv \
    && uv export --frozen --no-dev --format requirements-txt \
        -o /tmp/requirements.txt \
    && grep -v "^-e \.$" /tmp/requirements.txt > /tmp/deps.txt \
    && pip install --no-cache-dir -r /tmp/deps.txt \
    && rm /tmp/requirements.txt /tmp/deps.txt
COPY src/ ./src/
COPY novels.yaml ./
COPY config/ ./config/
COPY novel-sources/ ./novel-sources/

RUN pip install --no-cache-dir --no-deps . \
    && chown -R novel:novel /app

USER novel

EXPOSE 8000

CMD ["novel-translator-web"]
