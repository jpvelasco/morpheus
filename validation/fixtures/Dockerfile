FROM python:3.12.11-slim@sha256:47ae396f09c1303b8653019811a8498470603d7ffefc29cb07c88f1f8cb3d19f

RUN addgroup --system fixture && adduser --system --ingroup fixture fixture
WORKDIR /app
COPY --chown=fixture:fixture server.py /app/server.py
COPY --chown=fixture:fixture probe.py /app/probe.py
USER fixture
EXPOSE 8000
CMD ["python", "/app/server.py"]
