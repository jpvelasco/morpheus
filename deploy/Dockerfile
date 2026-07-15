FROM python:3.12-alpine3.23@sha256:601d3d3797e90e2534782e69c85fafb7971b43f24c7b1b079b7e48dd435e458d AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MORPHEUS_DATA_DIR=/var/lib/morpheus

RUN addgroup -S morpheus \
    && adduser -S -D -H -G morpheus morpheus \
    && install -d -o morpheus -g morpheus -m 0750 /var/lib/morpheus
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .
USER morpheus
EXPOSE 7400
CMD ["morpheus-api"]
