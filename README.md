# 🎬 LapsaCaptureBot

> The official media bot of **LAPSA** — share a link, get the video. Simple as that.

---

## What is this?

LapsaCaptureBot is a Telegram bot that lives in the LAPSA group chat. Whenever someone shares a link from Instagram, TikTok, Facebook, or Twitter/X, the bot automatically downloads the video or photos and posts them directly in the chat — no more "I can't open this link" or being forced to open another app.

Just share the link. The bot handles the rest. 🤙

---

## ✨ Features

- 📥 **Auto-detects** social media links in the group chat
- 🎥 **Downloads and reposts** videos instantly
- 🖼️ **Supports photo carousels** — sent as a clean Telegram album
- 🔇 **Silent by default** — ignores regular messages, only reacts to supported links
- ⚠️ **Handles errors gracefully** — private accounts, deleted posts, oversized files
- ☁️ **Runs 24/7** in the cloud — no laptop needed

---

## 📱 Supported Platforms

| Platform | Videos | Photos | Carousels | Reels |
|----------|--------|--------|-----------|-------|
| Instagram | ✅ | ✅ | ✅ | ✅ |
| TikTok | ✅ | ✅ | ✅ | ✅ |
| Facebook | ✅ | ✅ | — | — |
| Twitter / X | ✅ | ✅ | — | — |
| YouTube | ⚠️ | — | — | ⚠️ |

> ⚠️ YouTube requires additional authentication setup.

---

## 🚀 How It Works

```
Someone shares a link in LAPSA
          ↓
Bot detects the URL
          ↓
yt-dlp downloads the media
          ↓
Bot sends it back as video or album
          ↓
LAPSA goes 🔥
```

---

## 🛠️ Tech Stack

- **Python 3** — core language
- **python-telegram-bot** — Telegram Bot API wrapper
- **yt-dlp** — the powerhouse behind all media downloads
- **python-dotenv** — secure environment variable management
- **Render** — cloud hosting (24/7 uptime)

---

## 🔧 Local Development

### Prerequisites
- Python 3.8+
- A Telegram Bot token from [@BotFather](https://t.me/BotFather)

### Setup

```bash
# Clone the repo
git clone https://github.com/stgamarra/lapsacapturebot.git
cd lapsacapturebot

# Install dependencies
pip3 install -r requirements.txt

# Create your environment file
cp .env.example .env
# Add your BOT_TOKEN to .env

# Run the bot
python3 bot.py
```

### Environment Variables

Create a `.env` file in the root directory:

```
BOT_TOKEN=your_telegram_bot_token_here
```

> ⚠️ Never commit your `.env` file. It's already in `.gitignore`.

---

## ☁️ Deployment

The bot is deployed on **Render** as a Background Worker.

Every push to the `main` branch on GitHub **automatically redeploys** the bot on Render.

```
git add .
git commit -m "your changes"
git push origin main
# Render picks it up automatically ✅
```

---

## 📁 Project Structure

```
lapsacapturebot/
├── bot.py              # Main bot logic
├── requirements.txt    # Python dependencies
├── Procfile            # Render start command
├── .gitignore          # Keeps secrets out of GitHub
└── README.md           # You are here
```

---

## ⚠️ Known Limitations

- **50MB file size limit** — Telegram bots can't send files larger than 50MB. Oversized files are skipped with a warning.
- **Private accounts** — Content from private profiles requires authentication and is not currently supported.
- **YouTube** — Requires cookies from a logged-in session due to bot detection on cloud IPs.
- **Stories** — Instagram and TikTok stories require authentication to access.

---

## 🤝 Contributing

This bot was built for LAPSA. If you're part of the group and want to suggest a feature or report a bug, hit up [@stgamarra](https://github.com/stgamarra) on GitHub.

---

## 📜 License

Built with ❤️ for LAPSA. For private use only.

---

<div align="center">
  <sub>Made for the homies 🫂</sub>
</div>
