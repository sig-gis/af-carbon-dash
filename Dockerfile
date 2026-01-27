# Use a Python image with uv pre-installed
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

# Install the project into `/app`
WORKDIR /app

# Enable bytecode compilation
ENV UV_COMPILE_BYTECODE=1

# Copy from the cache instead of linking since it's a mounted volume
ENV UV_LINK_MODE=copy

# Omit development dependencies
ENV UV_NO_DEV=1

# Ensure installed tools can be executed out of the box
ENV UV_TOOL_BIN_DIR=/usr/local/bin

# install system deps + Quarto
RUN apt-get update && apt-get install -y \
    wget \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN wget -q https://quarto.org/download/latest/quarto-linux-amd64.deb \
    && dpkg -i quarto-linux-amd64.deb \
    && rm quarto-linux-amd64.deb

# Fail the build if Quarto is not available
RUN quarto --version
# -------------------------------

# Copy the lockfile and settings
COPY ./pyproject.toml ./uv.lock ./.python-version /app/

# Install the project's dependencies using the lockfile and settings
RUN uv sync --locked --no-install-project

# Copy application code
COPY model_service/ ./model_service/
COPY conf/ ./conf/
COPY utils/ ./utils/

# Install project itself
RUN uv sync --locked

# Place executables in the environment at the front of the path
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH=/app

# Expose the port the app runs on
EXPOSE 8080

# Command to run the application
CMD ["uvicorn", "model_service.main:app", "--host", "0.0.0.0", "--port", "8080"]