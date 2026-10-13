FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
COPY pyproject.toml ./
COPY achadinhos ./achadinhos
RUN pip install ".[postgres]"
VOLUME ["/app/data"]
EXPOSE 8000
CMD ["python", "-m", "achadinhos", "serve", "--host", "0.0.0.0", "--port", "8000"]
