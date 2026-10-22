FROM python:3.11-slim
WORKDIR /srv
COPY pyproject.toml ./
COPY app app
COPY mcp_servers mcp_servers
COPY demo_service demo_service
COPY runbooks runbooks
RUN pip install --no-cache-dir .
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
