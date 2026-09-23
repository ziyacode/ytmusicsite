# MediaGet — Video & Musiqi Yükləyici

Modern, sürətli və sadə media yükləmə vebsaytı.

## 🌟 Xüsusiyyətlər

- ✅ YouTube, TikTok, Instagram, +1000 sayt
- ✅ MP4 (video) və MP3 (audio) formatları
- ✅ TikTok/Instagram loqosuz (watermark-sız) yükləmə
- ✅ Real-time progress bar (SSE ilə)
- ✅ Dark/Light mode
- ✅ Tam responsive (telefon, planşet, kompüter)
- ✅ Azerbaycan dilində dostyana xəta mesajları

## 🚀 Tez Başlatma (Windows)

### Tələblər
1. **Python 3.10+** — [python.org](https://www.python.org/downloads/)
2. **FFmpeg** (MP3 üçün) — [ffmpeg.org](https://ffmpeg.org/download.html)
   - Yükləyin → `C:\ffmpeg\bin` qovluğuna çıxarın → PATH-a əlavə edin

### Başlatma
```
start.bat faylına iki dəfə klikləyin
```

Bu qədər! Brauzer `http://localhost:8000` ünvanında açılacaq.

---

## 🛠️ Manual Quraşdırma

```powershell
# 1. Virtual environment yarat
cd "yt music site"
python -m venv backend/venv

# 2. Aktivləşdir
backend\venv\Scripts\activate

# 3. Asılılıqları quraşdır
pip install -r backend/requirements.txt

# 4. Serveri başlat
python backend/main.py
```

## 📁 Layihə Strukturu

```
yt music site/
├── backend/
│   ├── main.py          ← FastAPI server (API endpointlər)
│   ├── downloader.py    ← yt-dlp inteqrasiyası, progress generator
│   ├── requirements.txt ← Python asılılıqları
│   └── downloads/       ← Müvəqqəti fayllar (avtomatik silinir)
├── frontend/
│   ├── index.html       ← Əsas səhifə (Tailwind CDN)
│   ├── app.js           ← State machine, SSE, platform tanıma
│   └── style.css        ← Animasiyalar, dark mode, custom stillər
└── start.bat            ← Windows üçün tez başlatma
```

## 🔌 API Endpointləri

| Method | URL | Açıqlama |
|--------|-----|----------|
| GET  | `/api/health`      | Server sağlamlıq yoxlaması |
| POST | `/api/info`        | Link metadata-sı (başlıq, thumbnail, müddət) |
| POST | `/api/download`    | Yükləməni başlat (SSE stream) |
| GET  | `/api/file/{name}` | Yüklənmiş faylı göndər |

### `/api/download` SSE Hadisələri
```json
// Progress
{"status": "progress", "percent": 42.5, "speed": "1.2MB/s", "eta": "00:05"}

// Tamamlandı
{"status": "done", "download_url": "/api/file/abc123.mp4", "percent": 100}

// Xəta
{"status": "error", "message": "İstifadəçi dostyana Azərbaycan mesajı"}
```

## 🔒 Təhlükəsizlik

- Fayl adları UUID ilə generasiya edilir (path traversal qarşısı)
- Yüklənmiş fayllar 5 dəqiqə sonra avtomatik silinir
- Yalnız `.mp4`, `.mp3`, `.webm`, `.m4a` uzantıları qəbul edilir

## 🔮 Gələcək Funksiyalar (hazır arxitektura)

- [ ] Yükləmə tarixçəsi (localStorage)
- [ ] Batch yükləmə (YouTube playlist)
- [ ] Keyfiyyət seçimi (720p, 1080p, 4K)
- [ ] Yükləmə kuyruksu (queue)
- [ ] Telegram Bot inteqrasiyası
# ytmusicsite
