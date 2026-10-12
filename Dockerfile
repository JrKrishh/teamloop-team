# TeamLoop hub + board in one container. Runs on Hugging Face Spaces (Docker SDK, port 7860) or anywhere.
# Agent S's model: set NEBIUS_API_KEY as a secret (NVIDIA Nemotron on Token Factory).
FROM python:3.12-slim
WORKDIR /app
COPY agent_s ./agent_s
COPY hub ./hub
RUN pip install --no-cache-dir ./agent_s ./hub && useradd -m teamloop
USER teamloop
ENV HUB_DB=/tmp/teamloop-hub.db \
    HUB_DEMO_ROOM=demo \
    PORT=7860
EXPOSE 7860
CMD ["sh", "-c", "uvicorn hub.app:app_from_env --factory --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
