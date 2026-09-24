# ============================================================
# main.py — FastAPI server
# Media Downloader API
# ============================================================

import asyncio
import json
import os
import sys
from pathlib import Path

# backend qovluğunu axtarış yoluna əlavə et
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from downloader import (
    DOWNLOAD_DIR,
    cleanup_file,
    detect_platform,
    download_media,
    fetch_info,
)

# ── FastAPI tətbiqini yarat ──────────────────────────────────
app = FastAPI(
    title="Media Downloader API",
    description="YouTube, TikTok, Instagram və digər platformalardan media yükləmə API-si",
    version="1.0.0",
)

# ── CORS — frontend ilə rahat işləmək üçün ──────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # İstehsalda öz domeninizi yazın
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Frontend statik faylları xidmət et ──────────────────────
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/app", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")


# ── Cookie və yt-dlp konfiqurasiyası ────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
COOKIE_PATH = os.path.join(BASE_DIR, "downloads", "cookies.txt")
if not os.path.exists(COOKIE_PATH):
    COOKIE_PATH = os.path.join(BASE_DIR, "cookies.txt")

ydl_opts = {
    'extractor_args': {
        'youtube': {
            'player_client': ['ios', 'android', 'mweb']
        }
    },
}
if os.path.exists(COOKIE_PATH):
    ydl_opts['cookiefile'] = COOKIE_PATH

# ── Pydantic sxemləri ────────────────────────────────────────

class InfoRequest(BaseModel):
    url: str

class DownloadRequest(BaseModel):
    url: str
    format: str = "mp4"       # "mp4" | "mp3"
    no_watermark: bool = True


# ── Yardımçı: dostyana xəta mesajları ───────────────────────

def friendly_error(e) -> str:
    """Exception və ya string qəbul edir, Azərbaycanca mesaj qaytarır."""
    msg = str(e).lower()
    if "format" in msg and ("not available" in msg or "unsupported" in msg):
        return "Bu video formatı dəstəklənmir və ya mövcud deyil."
    if "video unavailable" in msg or "this video is unavailable" in msg or "does not exist" in msg:
        return "Bu video mövcud deyil və ya silinib."
    if "bot" in msg or "confirm you're not a bot" in msg:
        return "YouTube serveri bot kimi qəbul etdi (Render IP bloku)."
    if "members only" in msg or "requires a subscription" in msg:
        return "Bu video yalnız abunəçilər/üzvlər üçündür."
    if "private" in msg:
        return "Bu video gizlidir (şəxsidir) və yüklənə bilmir."
    if "login" in msg or "sign in" in msg:
        return "YouTube giriş və ya təhlükəsizlik təsdiqi tələb edir."
    if "copyright" in msg or "removed" in msg:
        return "Bu video müəllif hüquqları ilə qorunub və yüklənə bilmir."
    if "age" in msg:
        return "Bu video yaşa görə məhdudlaşdırılıb."
    if "429" in msg or "too many" in msg:
        return "Çox sorğu göndərildi. Bir neçə saniyə gözləyib yenidən cəhd edin."
    if "network" in msg or "connection" in msg or "timeout" in msg:
        return "İnternet bağlantısında problem var. Bir az sonra yenidən cəhd edin."
    return "Xəta baş verdi. Linki yoxlayıb yenidən cəhd edin."


def normalize_url(url: str) -> str:
    """URL-də https:// yoxdursa avtomatik əlavə edir."""
    u = url.strip()
    if not u:
        return ""
    if not u.startswith("http://") and not u.startswith("https://"):
        return f"https://{u}"
    return u


# ── Endpointlər ──────────────────────────────────────────────

@app.get("/api/health")
async def health_check():
    """Server sağlamlıq yoxlaması."""
    return {"status": "ok", "message": "Server işləyir ✓"}


@app.post("/api/info")
async def get_info(body: InfoRequest):
    """
    Link haqqında metadata qaytarır.
    Frontend bu endpoint-i linki yapışdırandan dərhal sonra çağırır.
    """
    url = normalize_url(body.url)
    if not url:
        raise HTTPException(status_code=400, detail="URL boş ola bilməz.")
    try:
        info = await fetch_info(url)
        return info
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=friendly_error(e))


@app.post("/api/download")
async def start_download(body: DownloadRequest):
    """
    Yükləməni başladır və SSE (Server-Sent Events) vasitəsilə
    real-time progress göndərir.
    """
    url = normalize_url(body.url)
    if not url:
        raise HTTPException(status_code=400, detail="URL boş ola bilməz.")

    if body.format not in ("mp4", "mp3"):
        raise HTTPException(status_code=400, detail="Format yalnız 'mp4' və ya 'mp3' ola bilər.")

    async def event_generator():
        try:
            async for event in download_media(
                url=url,
                format_type=body.format,
                no_watermark=body.no_watermark,
            ):
                # SSE formatı: "data: <json>\n\n"
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

                # "done" hadisəsindən sonra faylı gecikmə ilə sil
                if event["status"] == "done":
                    asyncio.create_task(cleanup_file(event["filename"]))
                    break
                elif event["status"] == "error":
                    break
        except Exception as e:
            error_msg = friendly_error(e)
            yield f"data: {json.dumps({'status': 'error', 'message': error_msg}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # Nginx buffering-i söndür
        },
    )


@app.get("/api/file/{filename}")
async def serve_file(filename: str, title: str | None = None):
    """
    Yüklənmiş faylı istifadəçiyə göndərir.
    Fayl adında yalnız alphanumeric simvollar + nöqtə qəbul edilir (təhlükəsizlik).
    İstifadəçiyə təqdim edilən ad isə videonun öz başlığı olur.
    """
    import re
    if not re.match(r"^[a-f0-9]+\.(mp4|mp3|webm|m4a)$", filename):
        raise HTTPException(status_code=400, detail="Yanlış fayl adı.")

    file_path = DOWNLOAD_DIR / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Fayl tapılmadı və ya artıq silinib.")

    ext = file_path.suffix.lower()
    if title:
        from downloader import sanitize_filename
        clean_name = sanitize_filename(title)
        if not clean_name.lower().endswith(ext):
            display_name = f"{clean_name}{ext}"
        else:
            display_name = clean_name
    else:
        display_name = filename

    media_type = "audio/mpeg" if ext == ".mp3" else "video/mp4"
    return FileResponse(
        path=file_path,
        media_type=media_type,
        filename=display_name,
    )


# ── Kök URL → frontend-ə yönləndir ──────────────────────────
@app.get("/")
async def root():
    """Ana səhifə — frontend index.html-ə yönləndirir."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/app/index.html")


# ── Tətbiqi birbaşa işə sal ─────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    host = os.environ.get("HOST", "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1")
    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        reload=False if os.environ.get("PORT") else True,
        log_level="info",
    )
