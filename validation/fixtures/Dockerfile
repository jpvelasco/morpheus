FROM python:3.12-alpine3.23@sha256:601d3d3797e90e2534782e69c85fafb7971b43f24c7b1b079b7e48dd435e458d

RUN addgroup -S fixture && adduser -S -D -H -G fixture fixture
WORKDIR /app
COPY --chown=fixture:fixture server.py /app/server.py
COPY --chown=fixture:fixture probe.py /app/probe.py
USER fixture
EXPOSE 8000
CMD ["python", "/app/server.py"]
