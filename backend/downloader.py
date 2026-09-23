# ============================================================
# downloader.py — yt-dlp ilə media yükləmə məntiqi (v2 — düzəldilmiş)
# ============================================================

import yt_dlp
import uuid
import asyncio
import re
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

# 2. Əgər fayl kimi mövcuddursa
if not COOKIE_FILE:
    candidates = [
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
    'cookiefile': COOKIE_FILE or 'cookies.txt',
    'extractor_args': {
        'youtube': {
            'player_client': ['android', 'web', 'tv_embedded'],
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
    Faylı yükləyir və real-time progress göndərir.

    Yield:
        {"status": "progress", "percent": float, "speed": str, "eta": str}
        {"status": "done", "filename": str, "download_url": str}
        {"status": "error", "message": str}
    """
    uid = get_uid()
    platform = detect_platform(url)

    # Output şablonu — yt-dlp özü extensionu əlavə edir
    outtmpl = str(DOWNLOAD_DIR / f"{uid}.%(ext)s")

    # ── Progress callback ────────────────────────────────────
    progress_data = {"percent": 0.0, "speed": "", "eta": "", "phase": "", "size_info": ""}

    def _progress_hook(d):
        status = d.get("status", "")
        if status == "downloading":
            raw = d.get("_percent_str", "0%").strip()
            clean = re.sub(r"\x1b\[[0-9;]*m", "", raw)  # ANSI rəngləri sil
            try:
                pct = float(clean.replace("%", "").strip())
                # Bəzən 100%+ gəlir (fragment yükləmələri) — klamp et
                progress_data["percent"] = min(pct, 99.0)
            except ValueError:
                pass
            progress_data["speed"] = d.get("_speed_str", "") or ""
            progress_data["eta"]   = d.get("_eta_str", "") or ""
            progress_data["phase"] = "Yüklənir"

            total = d.get("_total_bytes_str") or d.get("_total_bytes_estimate_str") or ""
            downloaded = d.get("_downloaded_bytes_str", "")
            if total and downloaded:
                progress_data["size_info"] = f"{downloaded} / {total}"
            elif total:
                progress_data["size_info"] = total
            else:
                progress_data["size_info"] = ""
        elif status == "finished":
            progress_data["percent"] = 99.0
            progress_data["phase"] = "Çevrilir"
            progress_data["speed"] = ""
            progress_data["eta"]   = ""

    # ── Format stringi ───────────────────────────────────────
    if format_type == "mp3":
        # MP3 üçün FFmpeg mütləq lazımdır
        fmt = "bestaudio/best"
        postprocessors = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }]
        merge_format = None
    else:
        # MP4 — FFmpeg olmadan da işləyən formatlar öncelikli
        # "b[ext=mp4]" — artıq birləşdirilmiş (audio+video bir yerdə) MP4
        # Sona "best" qoyulur ki, hər halda bir şey yüklənsin
        if platform == "youtube":
            fmt = (
                "b[ext=mp4]/best[ext=mp4]/"             # Birləşdirilmiş MP4
                "bestvideo[ext=mp4]+bestaudio[ext=m4a]/" # Ayrı (FFmpeg lazım)
                "best"                                   # Son çarə
            )
        elif platform in ("tiktok", "instagram"):
            fmt = "b[ext=mp4]/best[ext=mp4]/best"
        else:
            fmt = "b[ext=mp4]/best[ext=mp4]/best[ext=mp4]/best"
        postprocessors = []
        merge_format = "mp4"

    # ── yt-dlp seçənəkləri ───────────────────────────────────
    ydl_opts = {
        **COMMON_OPTS,
        "format": fmt,
        "outtmpl": outtmpl,
        "progress_hooks": [_progress_hook],
    }

    if postprocessors:
        ydl_opts["postprocessors"] = postprocessors

    if merge_format:
        ydl_opts["merge_output_format"] = merge_format

    # Platform spesifik extractor_args əlavə et
    ydl_opts.setdefault("extractor_args", {})
    if platform == "youtube":
        ydl_opts["extractor_args"]["youtube"] = {
            "player_client": ["android", "web", "tv_embedded"]
        }
    elif platform == "tiktok" and no_watermark:
        ydl_opts["extractor_args"]["tiktok"] = {
            "api_hostname": "api16-normal-c-useast1a.tiktokv.com"
        }
    elif platform == "instagram":
        ydl_opts["extractor_args"]["instagram"] = {}

    # ── Asinxron yükləmə başlat ──────────────────────────────
    loop = asyncio.get_running_loop()
    done_event = asyncio.Event()
    error_holder: dict = {"msg": None}
    info_holder: dict = {"title": None}

    def _run_download():
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info_res = ydl.extract_info(url, download=True)
                if info_res:
                    info_holder["title"] = info_res.get("title")
        except yt_dlp.utils.DownloadError as e:
            error_holder["msg"] = _friendly_ydl_error(str(e))
        except Exception as e:
            error_holder["msg"] = _friendly_ydl_error(str(e))
        finally:
            loop.call_soon_threadsafe(done_event.set)

    # Thread-pool-da işə sal (event loop-u bloklamasın)
    loop.run_in_executor(None, _run_download)

    # ── Progress göndər ──────────────────────────────────────
    while not done_event.is_set():
        await asyncio.sleep(0.4)

        # Xəta baş verdisə dərhal bildiriş göndər
        if error_holder["msg"]:
            yield {"status": "error", "message": error_holder["msg"]}
            return

        yield {
            "status":    "progress",
            "percent":   round(progress_data["percent"], 1),
            "speed":     progress_data["speed"],
            "eta":       progress_data["eta"],
            "phase":     progress_data["phase"],
            "size_info": progress_data.get("size_info", ""),
        }

    # Thread bitdi — son xəta yoxlaması
    if error_holder["msg"]:
        yield {"status": "error", "message": error_holder["msg"]}
        return

    # ── Yaradılmış faylı tap ─────────────────────────────────
    found = _find_output_file(uid)
    if not found:
        yield {
            "status": "error",
            "message": "Fayl yaradıla bilmədi. Zəhmət olmasa yenidən cəhd edin."
        }
        return

    file_size_bytes = found.stat().st_size
    size_mb = round(file_size_bytes / (1024 * 1024), 2)
    size_formatted = f"{size_mb} MB" if size_mb >= 1.0 else f"{round(file_size_bytes / 1024, 1)} KB"

    raw_title = info_holder.get("title") or "media"
    clean_title = sanitize_filename(raw_title)
    display_name = f"{clean_title}{found.suffix}"

    from urllib.parse import quote
    yield {
        "status":         "done",
        "filename":       found.name,
        "display_name":   display_name,
        "size_formatted": size_formatted,
        "size_bytes":     file_size_bytes,
        "format":         format_type.upper(),
        "download_url":   f"/api/file/{found.name}?title={quote(display_name)}",
        "percent":        100,
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
    await asyncio.sleep(delay)
    target = DOWNLOAD_DIR / filename
    if target.exists():
        try:
            target.unlink()
        except OSError:
            pass
