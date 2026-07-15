FROM node:22.17.1-alpine3.22@sha256:5539840ce9d013fa13e3b9814c9353024be7ac75aca5db6d039504a56c04ea59 AS build
WORKDIR /build
COPY web/package.json web/package-lock.json ./
RUN npm ci --ignore-scripts
COPY web/ ./
RUN npm run build

FROM python:3.12-alpine3.23@sha256:601d3d3797e90e2534782e69c85fafb7971b43f24c7b1b079b7e48dd435e458d AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 MORPHEUS_DASHBOARD_DIR=/app/web
RUN addgroup -S morpheus && adduser -S -D -H -G morpheus morpheus
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY --from=build /build/dist ./web
RUN pip install --no-cache-dir .
USER morpheus
EXPOSE 7401
CMD ["morpheus-dashboard"]
