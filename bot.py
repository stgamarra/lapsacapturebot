import os
import re
import uuid
from dotenv import load_dotenv
from telegram import Update, InputMediaPhoto, InputMediaVideo
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, filters, ContextTypes
import yt_dlp

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

SUPPORTED_PLATFORMS = ["youtube.com", "youtu.be", "tiktok.com", "instagram.com", "twitter.com", "x.com"]

DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.webp'}
VIDEO_EXTS = {'.mp4', '.mov', '.webm', '.mkv'}

# Telegram album limit
ALBUM_MAX = 10

def extract_url(text):
    pattern = r'(https?://[^\s]+)'
    urls = re.findall(pattern, text)
    return urls[0] if urls else None

def is_supported(url):
    return any(platform in url for platform in SUPPORTED_PLATFORMS)

def download_media(url, session_id):
    output_template = os.path.join(DOWNLOAD_DIR, f"{session_id}_%(playlist_index)s.%(ext)s")
    
    ydl_opts = {
        'format': 'best[filesize<50M]/best',
        'outtmpl': output_template,
        'quiet': True,
        'no_warnings': True,
    }
    
    # If cookies file exists, use it (enables stories & private content)
    if os.path.exists('cookies.txt'):
        ydl_opts['cookiefile'] = 'cookies.txt'
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.extract_info(url, download=True)
    
    files = []
    for f in os.listdir(DOWNLOAD_DIR):
        if f.startswith(session_id):
            files.append(os.path.join(DOWNLOAD_DIR, f))
    return sorted(files)

def classify_file(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in IMAGE_EXTS:
        return 'image'
    elif ext in VIDEO_EXTS:
        return 'video'
    return 'unknown'

async def send_as_album(update, files):
    """Send files as Telegram media groups (albums of up to 10)."""
    # Filter out oversized files
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
    
    # Single item → send normally (albums need 2+ items)
    if len(valid_files) == 1:
        path = valid_files[0]
        kind = classify_file(path)
        with open(path, 'rb') as f:
            if kind == 'image':
                await update.message.reply_photo(f)
            elif kind == 'video':
                await update.message.reply_video(f)
        return
    
    # Split into chunks of 10 (Telegram's album limit)
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
                    media_group.append(InputMediaVideo(f))
            
            if media_group:
                await update.message.reply_media_group(media_group)
        finally:
            for f in open_files:
                f.close()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Send me a link and I'll fetch the media!\n\n"
        "Supported: YouTube, TikTok, Instagram, X/Twitter\n"
        "Works with: posts, reels, carousels, videos"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    url = extract_url(text)

    if not url or not is_supported(url):
        return

    status_msg = await update.message.reply_text("⏳ Fetching media...")
    session_id = str(uuid.uuid4())[:8]
    files = []

    try:
        files = download_media(url, session_id)

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
                "Stories and private accounts need authentication via a cookies.txt file."
            )
        elif 'not available' in err or '404' in err:
            await status_msg.edit_text("❌ Content unavailable (deleted or region-locked).")
        else:
            await status_msg.edit_text(f"❌ Couldn't download: {str(e)[:150]}")

    except Exception as e:
        await status_msg.edit_text(f"❌ Unexpected error: {str(e)[:150]}")

    finally:
        for path in files:
            if os.path.exists(path):
                os.remove(path)

app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

print("🤖 Bot is running...")
app.run_polling()