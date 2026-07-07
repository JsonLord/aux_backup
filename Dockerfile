# Use a base image with Python
FROM python:3.12-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    git \
    gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y nodejs \
    && npm install -g @google/jules \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m -u 1000 user

# Set working directory
WORKDIR /app

# Install uv
RUN pip install --no-cache-dir uv

# Copy requirements and install as root using uv --system
COPY requirements.txt .
RUN uv pip install --system --no-cache -r requirements.txt

# Pre-clone and pre-install external dependencies
RUN mkdir -p /app/external
RUN git clone -b fix/jules-final-submission-branch https://github.com/JsonLord/TinyTroupe.git /app/external/TinyTroupe
RUN git clone --recursive https://github.com/MartenBE/mkslides.git /app/external/mkslides
RUN sed -i 's/requires-python = ">=3.13"/requires-python = ">=3.12"/' /app/external/mkslides/pyproject.toml
RUN uv pip install --system /app/external/mkslides

# Copy the rest of the application
COPY . .

# Change ownership to non-root user
RUN chown -R user:user /app

# Switch to non-root user
USER user
ENV PATH="/home/user/.local/bin:$PATH"

# Set environment variables
ENV GRADIO_SERVER_NAME="0.0.0.0"
ENV GRADIO_SERVER_PORT=7860

# Expose the port
EXPOSE 7860

# Entry point
CMD ["python", "app.py"]
