FROM nvidia/cuda:12.4.0-runtime-ubuntu22.04

# Install Python and ffmpeg
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-dev ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Make python3 the default
RUN ln -sf /usr/bin/python3 /usr/bin/python

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Download model on first run (cached in volume)
ENV WHISPER_MODEL_DIR=/models

CMD ["uvicorn", "worker:app", "--host", "0.0.0.0", "--port", "8001"]
