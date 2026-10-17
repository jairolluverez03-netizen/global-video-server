FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg libgomp1 && rm -rf /var/lib/apt/lists/*
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN mkdir -p /models && python -m piper.download_voices es_ES-davefx-medium --data-dir /models
COPY server.py index.html instructor.png ./
RUN mkdir -p /data
ENV VIDEO_DATA=/data PIPER_MODEL=/models/es_ES-davefx-medium.onnx
EXPOSE 8000
CMD ["sh", "-c", "exec uvicorn server:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
