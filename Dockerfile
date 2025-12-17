FROM python:3.12-alpine

WORKDIR /app

# Set timezone to Brazil
ENV TZ=America/Sao_Paulo

# Install system dependencies
RUN apk add --no-cache \
    curl \
    tzdata \
    docker-cli \
    docker-cli-compose \
    && cp /usr/share/zoneinfo/$TZ /etc/localtime \
    && echo $TZ > /etc/timezone

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
