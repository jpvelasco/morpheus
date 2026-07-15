FROM node:22.17.1-alpine3.22@sha256:5539840ce9d013fa13e3b9814c9353024be7ac75aca5db6d039504a56c04ea59 AS build
WORKDIR /build
COPY web/package.json web/package-lock.json ./
RUN npm ci --ignore-scripts
COPY web/ ./
RUN npm run build

FROM python:3.12.11-slim@sha256:47ae396f09c1303b8653019811a8498470603d7ffefc29cb07c88f1f8cb3d19f AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 MORPHEUS_DASHBOARD_DIR=/app/web
RUN addgroup --system morpheus && adduser --system --ingroup morpheus morpheus
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY --from=build /build/dist ./web
RUN pip install --no-cache-dir .
USER morpheus
EXPOSE 7401
CMD ["morpheus-dashboard"]
