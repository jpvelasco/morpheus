FROM python:3.12.11-slim@sha256:27f90d79cc85e9b7b2560063ef44fa0e9eaae7a7c3f5a9f745fb6078c9c4f6c6 AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MORPHEUS_DATA_DIR=/var/lib/morpheus

RUN addgroup --system morpheus && adduser --system --ingroup morpheus morpheus
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .
USER morpheus
EXPOSE 7400
CMD ["morpheus-api"]
