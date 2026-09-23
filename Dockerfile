FROM python:3.10-slim

# FFmpeg, NodeJS və sistem alətlərini quraşdırırıq (NodeJS YouTube JS problemlərini həll edir)
RUN apt-get update && apt-get install -y ffmpeg nodejs curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Asılılıqları quraşdırırıq və yt-dlp-ni ən son versiyaya qaldırırıq
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && pip install --no-cache-dir -U yt-dlp

# Bütün layihə fayllarını kopyalayırıq
COPY . .

# Render port tənzimləməsi
ENV PORT=8000
EXPOSE 8000

# Serveri işə salırıq
CMD uvicorn backend.main:app --host 0.0.0.0 --port $PORT
