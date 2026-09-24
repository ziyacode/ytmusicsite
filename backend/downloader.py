# ============================================================
# downloader.py — yt-dlp ilə media yükləmə məntiqi (v2 — düzəldilmiş)
# ============================================================

import yt_dlp
import uuid
import asyncio
import re
import requests
from pathlib import Path
from typing import AsyncGenerator

# Yüklənmiş faylların saxlandığı müvəqqəti qovluq
DOWNLOAD_DIR = Path(__file__).parent / "downloads"
DOWNLOAD_DIR.mkdir(exist_ok=True)

# ── Platform tanıma ──────────────────────────────────────────

PLATFORM_PATTERNS = {
    "youtube": [r"youtube\.com", r"youtu\.be"],
    "tiktok":  [r"tiktok\.com", r"vm\.tiktok\.com"],
    "instagram": [r"instagram\.com"],
}

def detect_platform(url: str) -> str:
    """URL-dən platformanı müəyyən edir."""
    lower = url.lower()
    for platform, patterns in PLATFORM_PATTERNS.items():
        if any(re.search(p, lower) for p in patterns):
            return platform
    return "generic"


def get_youtube_id(url: str) -> str:
    """YouTube URL-dən video ID-sini çıxarır."""
    patterns = [
        r'(?:v=|\/shorts\/|youtu\.be\/|\/embed\/)([0-9A-Za-z_-]{11})',
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def sanitize_filename(title: str, max_length: int = 100) -> str:
    """Windows və digər ƏS-lər üçün fayl adından qadağan simvolları təmizləyir."""
    # Qadağan simvollar: \ / : * ? " < > |
    clean = re.sub(r'[\\/*?:"<>|]', '', title)
    clean = re.sub(r'[\r\n\t]+', ' ', clean)
    clean = re.sub(r'\s+', ' ', clean).strip()
    if not clean:
        clean = "media"
    return clean[:max_length]


def get_uid() -> str:
    """UUID-based unikal fayl adı."""
    return uuid.uuid4().hex


# FFmpeg yerini tap (sistem PATH və ya imageio-ffmpeg paketindən)
import os
import shutil
FFMPEG_PATH = shutil.which("ffmpeg")
if not FFMPEG_PATH:
    try:
        import imageio_ffmpeg
        FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        FFMPEG_PATH = None

# ── Cookie faylı və ya Render Environment Variable ───────────
COOKIE_FILE = None

# 1. Render Environment Variable (YOUTUBE_COOKIES — Render üçün ən rahat və təhlükəsiz yol)
cookie_env = os.environ.get("YOUTUBE_COOKIES")
if cookie_env:
    env_cookie_path = Path(__file__).parent / "cookies.txt"
    try:
        env_cookie_path.write_text(cookie_env.strip(), encoding="utf-8")
        COOKIE_FILE = str(env_cookie_path.resolve())
    except Exception as e:
        print(f"[Warning] Failed to write YOUTUBE_COOKIES: {e}")

# 2. Əgər fayl kimi mövcuddursa (downloads/cookies.txt prioritet olmaqla)
if not COOKIE_FILE:
    candidates = [
        DOWNLOAD_DIR / "cookies.txt",
        Path("backend/downloads/cookies.txt"),
        Path("downloads/cookies.txt"),
        Path("cookies.txt"),
        Path(__file__).parent / "cookies.txt",
        Path(__file__).parent.parent / "cookies.txt",
    ]
    for cand in candidates:
        if cand.exists() and cand.stat().st_size > 0:
            COOKIE_FILE = str(cand.resolve())
            break

# ── yt-dlp seçənəkləri (ydl_opts) ──────────────────────────

ydl_opts = {
    'format': 'bestaudio/best',
    'cookiefile': COOKIE_FILE if (COOKIE_FILE and Path(COOKIE_FILE).exists()) else None,
    'extractor_args': {
        'youtube': {
            'player_client': ['ios', 'android', 'mweb']
        }
    },
    # YouTube-un bot yoxlamasını təmkinlə keçmək üçün əlavə parametrlər
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'no_warnings': True,
    'socket_timeout': 30,
    'geo_bypass': True,
}

COMMON_OPTS = {
    **ydl_opts,
    "quiet": True,
    "noplaylist": True,
    # İstifadəçi agent — bot blokunu azaldır
    "http_headers": {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    },
    # Şəbəkə xətaları üçün retry
    "retries": 5,
    "fragment_retries": 5,
    "file_access_retries": 3,
}

if COOKIE_FILE:
    COMMON_OPTS["cookiefile"] = COOKIE_FILE
elif "cookiefile" in COMMON_OPTS and not Path(COMMON_OPTS["cookiefile"]).exists():
    del COMMON_OPTS["cookiefile"]

if FFMPEG_PATH:
    COMMON_OPTS["ffmpeg_location"] = FFMPEG_PATH


# ── Metadata əldə etmə ──────────────────────────────────────

async def fetch_info(url: str) -> dict:
    """
    Link haqqında metadata qaytarır (yükləmir).
    Bütün xətaları tutub ValueError qaldırır.
    """
    platform = detect_platform(url)

    # Əgər platforma YouTube-dursa, Piped API istifadə edirik (Bot blokuna düşməmək üçün)
    if platform == "youtube":
        vid_id = get_youtube_id(url)
        if vid_id:
            # Piped serverləri (aktiv coffee serveri + kavin.rocks)
            piped_endpoints = [
                "https://api.piped.private.coffee",
                "https://pipedapi.kavin.rocks",
            ]
            for api_base in piped_endpoints:
                try:
                    api_url = f"{api_base}/streams/{vid_id}"
                    response = requests.get(api_url, timeout=5)
                    if response.status_code == 200:
                        data = response.json()
                        return {
                            "title": data.get("title", "YouTube Video"),
                            "thumbnail": data.get("thumbnailUrl", ""),
                            "duration": data.get("duration", 0),
                            "platform": "youtube",
                            "uploader": data.get("uploader", ""),
                            "view_count": data.get("views", 0),
                            "estimated_size": "~çıxarıla bilər",
                        }
                except Exception:
                    continue  # Xəta olarsa növbəti serverə və ya yt-dlp-yə keçir

    # Digər hallarda (və ya Piped işləmədikdə) köhnə yt-dlp üsulu işləyir
    opts = {
        **COMMON_OPTS,
        "skip_download": True,
    }

    def _extract():
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(url, download=False)

    loop = asyncio.get_running_loop()
    try:
        info = await loop.run_in_executor(None, _extract)
    except yt_dlp.utils.DownloadError as e:
        raise ValueError(_friendly_ydl_error(str(e)))
    except Exception as e:
        raise ValueError(f"Xəta: {str(e)[:300]}")

    # Təxmini ölçü
    size_bytes = info.get("filesize") or info.get("filesize_approx")
    size_str = ""
    if size_bytes:
        mb = round(size_bytes / (1024 * 1024), 1)
        size_str = f"~{mb} MB" if mb >= 1.0 else f"~{round(size_bytes / 1024, 0)} KB"

    return {
        "title":          info.get("title", "Bilinməyən"),
        "thumbnail":      _best_thumbnail(info),
        "duration":       info.get("duration") or 0,
        "platform":       detect_platform(url),
        "uploader":       info.get("uploader") or info.get("channel") or "",
        "view_count":     info.get("view_count") or 0,
        "estimated_size": size_str,
    }


def _best_thumbnail(info: dict) -> str:
    """Ən yaxşı thumbnail URL-ni qaytarır."""
    # Birbaşa thumbnail
    thumb = info.get("thumbnail", "")
    if thumb:
        return thumb
    # Siyahıdan ən yüksək keyfiyyətlisi
    thumbs = info.get("thumbnails", [])
    if thumbs:
        # Ən böyük preference-ə görə sırala
        best = max(thumbs, key=lambda t: t.get("preference", 0) or t.get("width", 0) or 0)
        return best.get("url", "")
    return ""


# ── İstifadəçi dostyana xəta mesajları ──────────────────────

def _friendly_ydl_error(msg: str) -> str:
    low = msg.lower()
    if "ffmpeg" in low:
        return "Video/audio birləşdirmək üçün FFmpeg tələb olunur."
    if "format" in low and ("not available" in low or "unsupported" in low):
        return "Bu video formatı dəstəklənmir və ya mövcud deyil."
    if "video unavailable" in low or "this video is unavailable" in low or "does not exist" in low:
        return "Bu video mövcud deyil və ya silinib."
    if "bot" in low or "confirm you're not a bot" in low:
        return "YouTube server IP-sini bloklayıb (Bot yoxlaması)."
    if "members only" in low or "requires a subscription" in low:
        return "Bu video yalnız abunəçilər/üzvlər üçündür."
    if "private" in low:
        return "Bu video gizlidir (şəxsidir) və yüklənə bilmir."
    if "login" in low or "sign in" in low:
        return "YouTube giriş və ya təhlükəsizlik təsdiqi tələb edir."
    if "copyright" in low or "removed" in low:
        return "Bu video müəllif hüquqları səbəbiylə mövcud deyil."
    if "network" in low or "connection" in low or "timeout" in low or "unable to download" in low:
        return "İnternet bağlantısında problem var. Bir az sonra yenidən cəhd edin."
    if "age" in low or "18" in low:
        return "Bu video yaşa görə məhdudlaşdırılıb."
    return "Link emal edilə bilmədi və ya yükləmə xətası baş verdi. Yenidən cəhd edin."


# ── Yükləmə — SSE stream üçün asinxron generator ────────────

async def download_media(
    url: str,
    format_type: str = "mp4",
    no_watermark: bool = True,
) -> AsyncGenerator[dict, None]:
    """
    Hybrid yükləmə: Əvvəlcə alternativ API-ləri sınayır,
    alınmadıqda mövcud yt-dlp/fallback mexanizminə keçir.
    """
    uid = get_uid()
    platform = detect_platform(url)
    
    yield {"status": "progress", "percent": 20, "speed": "", "eta": "", "phase": "Sorğu emal edilir...", "size_info": ""}
    await asyncio.sleep(0.3)

    local_filename = f"{uid}.{'mp3' if format_type == 'mp3' else 'mp4'}"
    local_path = DOWNLOAD_DIR / local_filename
    loop = asyncio.get_running_loop()

    success = False
    display_name = "media"
    file_size_bytes = 0

    # 1. CƏHD: Əgər TikTok və ya Instagram-dırsa, birbaşa yt-dlp ilə yoxlayaq 
    # (Çünki TikTok/Insta-da Render IP bloku yoxdur, mükəmməl işləyir)
    if platform in ("tiktok", "instagram"):
        yield {"status": "progress", "percent": 50, "speed": "", "eta": "", "phase": "Media yüklənir...", "size_info": ""}
        
        # Mövcud COMMON_OPTS ilə yükləmə
        outtmpl = str(DOWNLOAD_DIR / f"{uid}.%(ext)s")
        ydl_opts = {
            **COMMON_OPTS,
            "format": "b[ext=mp4]/best[ext=mp4]/best",
            "outtmpl": outtmpl,
        }
        if platform == "tiktok" and no_watermark:
            ydl_opts.setdefault("extractor_args", {})
            ydl_opts["extractor_args"]["tiktok"] = {
                "api_hostname": "api16-normal-c-useast1a.tiktokv.com"
            }
        
        def _run_ytdlp():
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    return info.get("title")
            except Exception:
                return None

        title = await loop.run_in_executor(None, _run_ytdlp)
        if title:
            found = _find_output_file(uid)
            if found and found.exists():
                success = True
                raw_title = title
                clean_title = sanitize_filename(raw_title)
                display_name = f"{clean_title}{found.suffix}"
                local_filename = found.name
                local_path = found

    # 2. CƏHD: Əgər YouTube-dursa və ya yuxarıdakı uğursuz olduysa, 
    # yt-dlp-nin özü ilə (cookies və player_client parametrləri ilə) şansımızı yoxlayaq
    if not success:
        yield {"status": "progress", "percent": 50, "speed": "", "eta": "", "phase": "Alternativ kanal ilə yoxlanılır...", "size_info": ""}
        
        outtmpl = str(DOWNLOAD_DIR / f"{uid}.%(ext)s")
        if format_type == "mp3":
            fmt = "bestaudio/best"
            postprocessors = [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}]
        else:
            fmt = (
                "b[ext=mp4]/best[ext=mp4]/"
                "bestvideo[ext=mp4]+bestaudio[ext=m4a]/"
                "best"
            )
            postprocessors = []

        ydl_opts = {
            **COMMON_OPTS,
            "format": fmt,
            "outtmpl": outtmpl,
        }
        if postprocessors:
            ydl_opts["postprocessors"] = postprocessors
        if platform == "youtube":
            ydl_opts.setdefault("extractor_args", {})
            ydl_opts["extractor_args"]["youtube"] = {
                "player_client": ["ios", "android", "mweb"]
            }

        def _run_fallback():
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    return info.get("title")
            except Exception as e:
                return None

        title = await loop.run_in_executor(None, _run_fallback)
        if title:
            found = _find_output_file(uid)
            if found and found.exists():
                success = True
                raw_title = title
                clean_title = sanitize_filename(raw_title)
                display_name = f"{clean_title}{found.suffix}"
                local_filename = found.name
                local_path = found

    # Əgər hər iki üsul da bloklanıbsa və ya alınıbsa
    if not success or not local_path.exists():
        yield {
            "status": "error", 
            "message": "YouTube server IP ünvanını bloklayıb. TikTok və Instagram linkləri sərbəst işləyir."
        }
        return

    file_size_bytes = local_path.stat().st_size
    size_mb = round(file_size_bytes / (1024 * 1024), 2)
    size_formatted = f"{size_mb} MB" if size_mb >= 1.0 else f"{round(file_size_bytes / 1024, 1)} KB"

    from urllib.parse import quote
    yield {
        "status": "done",
        "filename": local_filename,
        "display_name": display_name,
        "size_formatted": size_formatted,
        "size_bytes": file_size_bytes,
        "format": format_type.upper(),
        "download_url": f"/api/file/{local_filename}?title={quote(display_name)}",
        "percent": 100,
    }


def _find_output_file(uid: str) -> Path | None:
    """
    yt-dlp-nin yaratdığı faylı UID ilə tapır.
    Extension fərqli ola bilər (mp4, webm, m4a, mp3...).
    """
    for f in DOWNLOAD_DIR.iterdir():
        if f.stem == uid and f.is_file():
            return f
    return None


# ── Fayl təmizliyi ───────────────────────────────────────────

async def cleanup_file(filename: str, delay: int = 300):
    """
    Yüklədikdən sonra faylı gecikdirmə ilə silir.
    Standart: 5 dəqiqə.
    """
    if "cookies.txt" in filename.lower():
        return
    await asyncio.sleep(delay)
    target = DOWNLOAD_DIR / filename
    if target.exists():
        try:
            target.unlink()
        except OSError:
            pass
