FROM python:3.10-slim

# FFmpeg və sistem alətlərini quraşdırırıq
RUN apt-get update && apt-get install -y ffmpeg curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Asılılıqları quraşdırırıq
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Bütün layihə fayllarını kopyalayırıq
COPY . .

# Render port tənzimləməsi
ENV PORT=8000
EXPOSE 8000

# Serveri işə salırıq
CMD uvicorn backend.main:app --host 0.0.0.0 --port $PORT
