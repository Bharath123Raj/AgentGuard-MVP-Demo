FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY agentguard ./agentguard
RUN pip install --no-cache-dir .
RUN useradd -m -u 10001 guard && mkdir -p /app/data && chown guard:guard /app/data
USER guard
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/ready', timeout=3)" || exit 1
CMD ["uvicorn", "agentguard.api:app_from_env", "--factory", "--host", "0.0.0.0", "--port", "8000"]
