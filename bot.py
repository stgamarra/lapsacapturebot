import os
import re
import uuid
import asyncio
import subprocess
import json
from dotenv import load_dotenv
from telegram import Update, InputMediaPhoto, InputMediaVideo
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, filters, ContextTypes
import yt_dlp
import imageio_ffmpeg

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

# ==========================================
# VERSION & CHANGELOG
# ==========================================
VERSION = "1.1.1"

CHANGELOG = {
    "1.1.1": [
        "🎞️ Fixed vertical videos showing as squares (aspect ratio fix)",
        "📐 Videos now include correct dimensions and duration",
    ],
    "1.1.0": [
        "➕ Added support for Threads links",
        "➕ Added support for Facebook Reels and fb.watch links",
        "🔁 Added automatic retry on failed downloads",
        "📢 Added /updates command to see latest changes",
    ],
    "1.0.0": [
        "🎉 Initial release",
        "📥 Auto-download from Instagram, TikTok, Facebook, X/Twitter, YouTube",
        "🖼️ Carousel support sent as Telegram albums",
        "🔒 Graceful handling of private/unavailable content",
    ],
}

# ==========================================
# PLATFORMS
# ==========================================
SUPPORTED_PLATFORMS = [
    "youtube.com", "youtu.be",
    "tiktok.com",
    "instagram.com",
    "twitter.com", "x.com",
    "facebook.com", "fb.watch", "fb.com",
    "threads.net", "threads.com",
]

DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.webp'}
VIDEO_EXTS = {'.mp4', '.mov', '.webm', '.mkv'}
ALBUM_MAX = 10

NON_RETRYABLE_KEYWORDS = ['login', 'private', 'not available', '404', 'restricted', 'unavailable']


# ==========================================
# HELPERS
# ==========================================
def extract_url(text):
    pattern = r'(https?://[^\s]+)'
    urls = re.findall(pattern, text)
    return urls[0] if urls else None


def is_supported(url):
    return any(platform in url for platform in SUPPORTED_PLATFORMS)


def is_retryable_error(error_msg):
    err = str(error_msg).lower()
    return not any(keyword in err for keyword in NON_RETRYABLE_KEYWORDS)


def get_video_info(path):
    """Extract width, height, and duration from a video file using ffprobe."""
    try:
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        ffprobe_exe = ffmpeg_exe.replace('ffmpeg', 'ffprobe')
        
        result = subprocess.run(
            [ffprobe_exe, '-v', 'quiet', '-print_format', 'json',
             '-show_streams', '-show_format', path],
            capture_output=True, text=True, timeout=10
        )
        data = json.loads(result.stdout)
        
        video_stream = next(
            (s for s in data.get('streams', []) if s.get('codec_type') == 'video'),
            None
        )
        if not video_stream:
            return None
        
        return {
            'width': int(video_stream.get('width', 0)),
            'height': int(video_stream.get('height', 0)),
            'duration': int(float(data.get('format', {}).get('duration', 0))),
        }
    except Exception:
        return None


def classify_file(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in IMAGE_EXTS:
        return 'image'
    elif ext in VIDEO_EXTS:
        return 'video'
    return 'unknown'


# ==========================================
# DOWNLOAD
# ==========================================
def download_media(url, session_id):
    output_template = os.path.join(DOWNLOAD_DIR, f"{session_id}_%(playlist_index)s.%(ext)s")
    
    ydl_opts = {
        'format': 'best[filesize<50M]/best',
        'outtmpl': output_template,
        'quiet': True,
        'no_warnings': True,
        'socket_timeout': 30,
    }
    
    if os.path.exists('cookies.txt'):
        ydl_opts['cookiefile'] = 'cookies.txt'
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.extract_info(url, download=True)
    
    files = []
    for f in os.listdir(DOWNLOAD_DIR):
        if f.startswith(session_id):
            files.append(os.path.join(DOWNLOAD_DIR, f))
    return sorted(files)


async def download_with_retry(url, session_id, max_retries=1):
    """Try to download. Retry once on retryable errors."""
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            return download_media(url, session_id)
        except Exception as e:
            last_error = e
            if attempt < max_retries and is_retryable_error(e):
                await asyncio.sleep(2)
                continue
            raise last_error


# ==========================================
# SEND
# ==========================================
async def send_as_album(update, files):
    valid_files = []
    skipped = 0
    for path in files:
        size_mb = os.path.getsize(path) / (1024 * 1024)
        if size_mb > 50:
            skipped += 1
            continue
        valid_files.append(path)
    
    if skipped > 0:
        await update.message.reply_text(f"⚠️ Skipped {skipped} oversized file(s) (>50MB)")
    
    if not valid_files:
        return
    
    # Single item — send directly (albums require 2+ items)
    if len(valid_files) == 1:
        path = valid_files[0]
        kind = classify_file(path)
        with open(path, 'rb') as f:
            if kind == 'image':
                await update.message.reply_photo(f)
            elif kind == 'video':
                info = get_video_info(path)
                if info and info['width'] and info['height']:
                    await update.message.reply_video(
                        f,
                        width=info['width'],
                        height=info['height'],
                        duration=info['duration'],
                        supports_streaming=True,
                    )
                else:
                    await update.message.reply_video(f, supports_streaming=True)
        return
    
    # Multiple items — send as album(s) of up to 10
    for i in range(0, len(valid_files), ALBUM_MAX):
        chunk = valid_files[i:i + ALBUM_MAX]
        media_group = []
        open_files = []
        
        try:
            for path in chunk:
                kind = classify_file(path)
                f = open(path, 'rb')
                open_files.append(f)
                
                if kind == 'image':
                    media_group.append(InputMediaPhoto(f))
                elif kind == 'video':
                    info = get_video_info(path)
                    if info and info['width'] and info['height']:
                        media_group.append(InputMediaVideo(
                            f,
                            width=info['width'],
                            height=info['height'],
                            duration=info['duration'],
                            supports_streaming=True,
                        ))
                    else:
                        media_group.append(InputMediaVideo(f, supports_streaming=True))
            
            if media_group:
                await update.message.reply_media_group(media_group)
        finally:
            for f in open_files:
                f.close()


# ==========================================
# COMMANDS
# ==========================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"👋 Hey! I'm LapsaCaptureBot v{VERSION}\n\n"
        "Send me a link from Instagram, TikTok, Facebook, X, Threads, or YouTube "
        "and I'll fetch the media for you!\n\n"
        "Type /updates to see the latest changes."
    )


async def updates(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send only the latest version's changelog."""
    latest_version = next(iter(CHANGELOG))
    latest_changes = CHANGELOG[latest_version]
    
    message = f"📢 *What's new in v{latest_version}*\n\n"
    for change in latest_changes:
        message += f"{change}\n"
    
    await update.message.reply_text(message, parse_mode='Markdown')


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    
    # Support "@lapsacapturebot updates" mention
    bot_username = context.bot.username.lower()
    if f"@{bot_username}" in text.lower() and "updates" in text.lower():
        await updates(update, context)
        return
    
    url = extract_url(text)
    if not url or not is_supported(url):
        return

    status_msg = await update.message.reply_text("⏳ Fetching media...")
    session_id = str(uuid.uuid4())[:8]
    files = []

    try:
        files = await download_with_retry(url, session_id, max_retries=1)

        if not files:
            await status_msg.edit_text("❌ No media found at that link.")
            return

        await status_msg.edit_text(f"📦 Found {len(files)} item(s), sending...")
        await send_as_album(update, files)
        await status_msg.delete()

    except yt_dlp.utils.DownloadError as e:
        err = str(e).lower()
        if 'login' in err or 'private' in err or 'rate' in err or 'restricted' in err or 'cookies' in err:
            await status_msg.edit_text(
                "🔒 This content requires login.\n\n"
                "Stories and private accounts need authentication."
            )
        elif 'not available' in err or '404' in err or 'unavailable' in err:
            await status_msg.edit_text("❌ Content unavailable (deleted or region-locked).")
        else:
            await status_msg.edit_text(f"❌ Couldn't download after retry: {str(e)[:150]}")

    except Exception as e:
        await status_msg.edit_text(f"❌ Unexpected error: {str(e)[:150]}")

    finally:
        for path in files:
            if os.path.exists(path):
                os.remove(path)


# ==========================================
# MAIN
# ==========================================
app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("updates", updates))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

print(f"🤖 LapsaCaptureBot v{VERSION} is running...")
app.run_polling()