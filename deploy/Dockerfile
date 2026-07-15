FROM python:3.12.11-slim@sha256:47ae396f09c1303b8653019811a8498470603d7ffefc29cb07c88f1f8cb3d19f AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MORPHEUS_DATA_DIR=/var/lib/morpheus

RUN addgroup --system morpheus \
    && adduser --system --ingroup morpheus morpheus \
    && install -d -o morpheus -g morpheus -m 0750 /var/lib/morpheus
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .
USER morpheus
EXPOSE 7400
CMD ["morpheus-api"]
