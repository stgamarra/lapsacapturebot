import os
import re
import uuid
import asyncio
import subprocess
import json
from dotenv import load_dotenv
from telegram import Update, InputMediaPhoto, InputMediaVideo, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, CallbackQueryHandler, filters, ContextTypes
import yt_dlp
import imageio_ffmpeg

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

# ==========================================
# VERSION & CHANGELOG
# ==========================================
VERSION = "1.4.0"

CHANGELOG = {
    "1.4.0": [
        "🍪 Added YouTube Shorts support via authenticated cookies",
        "🚫 Bot now ignores long YouTube videos to keep groups clean",
    ],
    "1.3.0": [
        "🔄 Added retry button when downloads fail due to network/timeout",
    ],
    "1.2.0": [
        "🥚 Added easter egg responses",
    ],
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

def is_youtube_long_video(url):
    """Check if URL is a long YouTube video (not a Short)."""
    if "youtube.com/shorts/" in url:
        return False  # It's a Short, allow it
    if "youtube.com/watch" in url or "youtu.be/" in url:
        return True  # Regular video, skip
    return False


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

# In-memory store for retry URLs (keyed by message ID)
RETRY_STORE = {}

def make_retry_keyboard(url):
    """Create an inline keyboard with a retry button."""
    # We can't put the URL directly in callback_data (64 byte limit)
    # So we store it and pass a short ID
    retry_id = str(uuid.uuid4())[:8]
    RETRY_STORE[retry_id] = url
    
    keyboard = [[InlineKeyboardButton("🔄 Retry", callback_data=f"retry:{retry_id}")]]
    return InlineKeyboardMarkup(keyboard)

async def send_as_album_from_query(query, files):
    """Same as send_as_album but for callback queries."""
    valid_files = []
    skipped = 0
    for path in files:
        size_mb = os.path.getsize(path) / (1024 * 1024)
        if size_mb > 50:
            skipped += 1
            continue
        valid_files.append(path)
    
    if skipped > 0:
        await query.message.reply_text(f"⚠️ Skipped {skipped} oversized file(s) (>50MB)")
    
    if not valid_files:
        return
    
    if len(valid_files) == 1:
        path = valid_files[0]
        kind = classify_file(path)
        with open(path, 'rb') as f:
            if kind == 'image':
                await query.message.reply_photo(f)
            elif kind == 'video':
                info = get_video_info(path)
                if info and info['width'] and info['height']:
                    await query.message.reply_video(
                        f, width=info['width'], height=info['height'],
                        duration=info['duration'], supports_streaming=True,
                    )
                else:
                    await query.message.reply_video(f, supports_streaming=True)
        return
    
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
                            f, width=info['width'], height=info['height'],
                            duration=info['duration'], supports_streaming=True,
                        ))
                    else:
                        media_group.append(InputMediaVideo(f, supports_streaming=True))
            if media_group:
                await query.message.reply_media_group(media_group)
        finally:
            for f in open_files:
                f.close()


# ==========================================
# DOWNLOAD
# ==========================================
def download_media(url, session_id):
    output_template = os.path.join(DOWNLOAD_DIR, f"{session_id}_%(playlist_index)s.%(ext)s")
    
    ydl_opts = {
        'format': 'bv*[filesize<50M]+ba/b[filesize<50M]/bv*+ba/b',
        'merge_output_format': 'mp4',
        'outtmpl': output_template,
        'quiet': True,
        'no_warnings': True,
        'socket_timeout': 30,
    }
    
    # Use YouTube cookies from environment variable (for YouTube links only)
    cookies_path = None
    youtube_cookies = os.getenv("YOUTUBE_COOKIES")
    is_youtube = any(domain in url for domain in ["youtube.com", "youtu.be"])
    
    if youtube_cookies and is_youtube:
        print(f"🍪 Using YouTube cookies (length: {len(youtube_cookies)} chars)")
        cookies_path = os.path.join(DOWNLOAD_DIR, f"{session_id}_yt_cookies.txt")
        with open(cookies_path, 'w') as f:
            f.write(youtube_cookies)
        ydl_opts['cookiefile'] = cookies_path
    elif is_youtube:
        print(f"⚠️ YouTube URL but no cookies set!")
    elif os.path.exists('cookies.txt'):
        ydl_opts['cookiefile'] = 'cookies.txt'
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.extract_info(url, download=True)
    finally:
        # Clean up the temp cookies file
        if cookies_path and os.path.exists(cookies_path):
            os.remove(cookies_path)
    
    files = []
    for f in os.listdir(DOWNLOAD_DIR):
        if f.startswith(session_id) and not f.endswith('_yt_cookies.txt'):
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
    
    # Skip long YouTube videos silently (only Shorts are supported)
    if is_youtube_long_video(url):
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
            # No retry — login won't fix itself
        elif 'not available' in err or '404' in err or 'unavailable' in err:
            await status_msg.edit_text("❌ Content unavailable (deleted or region-locked).")
            # No retry — content is gone
        else:
            # Network/timeout — retry might work!
            await status_msg.edit_text(
                f"❌ Couldn't download: {str(e)[:150]}",
                reply_markup=make_retry_keyboard(url)
            )

    except Exception as e:
        await status_msg.edit_text(
            f"❌ Unexpected error: {str(e)[:150]}",
            reply_markup=make_retry_keyboard(url)
        )

    finally:
        for path in files:
            if os.path.exists(path):
                os.remove(path)

async def handle_retry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the retry button tap."""
    query = update.callback_query
    await query.answer()  # Removes the loading state on the button
    
    # Extract retry ID from callback data
    callback_data = query.data
    if not callback_data.startswith("retry:"):
        return
    
    retry_id = callback_data.split(":", 1)[1]
    url = RETRY_STORE.get(retry_id)
    
    if not url:
        await query.edit_message_text("❌ Retry expired. Please send the link again.")
        return
    
    # Remove the retry button and show "retrying"
    await query.edit_message_text("🔄 Retrying download...")
    
    session_id = str(uuid.uuid4())[:8]
    files = []
    
    try:
        files = await download_with_retry(url, session_id, max_retries=1)
        
        if not files:
            await query.edit_message_text("❌ No media found at that link.")
            return
        
        await query.edit_message_text(f"📦 Found {len(files)} item(s), sending...")
        await send_as_album_from_query(query, files)
        await query.delete_message()
        
        # Clean up the retry store
        RETRY_STORE.pop(retry_id, None)
    
    except yt_dlp.utils.DownloadError as e:
        err = str(e).lower()
        if 'login' in err or 'private' in err:
            await query.edit_message_text("🔒 This content requires login.")
        elif 'not available' in err or '404' in err:
            await query.edit_message_text("❌ Content unavailable.")
        else:
            await query.edit_message_text(
                f"❌ Still failing: {str(e)[:150]}",
                reply_markup=make_retry_keyboard(url)
            )
    
    except Exception as e:
        await query.edit_message_text(
            f"❌ Error: {str(e)[:150]}",
            reply_markup=make_retry_keyboard(url)
        )
    
    finally:
        for path in files:
            if os.path.exists(path):
                os.remove(path)


# ==========================================
# EASTER EGGS 🥚
# ==========================================
EASTER_EGG_STICKERS = {
    "AgAD4gEAAjlmLwAB": "Chúpate tu esa, cachón. ¿Tú no respetas?",
}

async def handle_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Respond to specific stickers, but only when replying to the bot."""
    sticker = update.message.sticker
    if not sticker or sticker.file_unique_id not in EASTER_EGG_STICKERS:
        return
    
    # Only respond if this sticker is a REPLY to one of the bot's messages
    replied_to = update.message.reply_to_message
    if not replied_to or not replied_to.from_user:
        return
    
    if replied_to.from_user.id != context.bot.id:
        return
    
    response = EASTER_EGG_STICKERS[sticker.file_unique_id]
    await update.message.reply_text(response)

# ==========================================
# MAIN
# ==========================================
app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("updates", updates))
app.add_handler(MessageHandler(filters.Sticker.ALL, handle_sticker))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
app.add_handler(CallbackQueryHandler(handle_retry, pattern=r'^retry:')) 

print(f"🤖 LapsaCaptureBot v{VERSION} is running...")
app.run_polling()