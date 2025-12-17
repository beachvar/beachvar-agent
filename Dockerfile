FROM python:3.12-slim

WORKDIR /app

# Set timezone to Brazil
ENV TZ=America/Sao_Paulo

# Install system dependencies (docker CLI for compose commands)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    tzdata \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
    && echo $TZ > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

# Install Docker CLI
RUN curl -fsSL https://get.docker.com | sh

# Install uv for fast dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy dependency file
COPY pyproject.toml .

# Install dependencies
RUN uv pip install --system -e .

# Copy application code
COPY src/ src/
COPY main.py .

# Environment variables
ENV PYTHONUNBUFFERED=1

CMD ["python", "main.py"]
