# 🚀 FileScrapper Telegram Bot (v2.0)

[![Python Version](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Telegram Bot](https://img.shields.io/badge/Telegram-Bot%20API%20v22-blue?logo=telegram)](https://core.telegram.org/bots)
[![Open in Colab](https://colab.research.google.com/assets/colab-badge.svg)](FileScrapper_Runner.ipynb)

A premium, minimal, and asynchronous **Telegram Bot** designed to monitor forum releases (DropMMS / Invision Community), extract direct streaming video links, provide date-wise daily drops, in-bot keyword search, and automatically broadcast new releases to linked Telegram Channels 24/7.

---

## ✨ Features

- 💎 **Premium & Minimal UI:** Clean video cards, quality badges (`#1080p`, `#Exclusive`), and an interactive grid of direct streaming buttons (`⚡ Vidara`, `🎬 Streamtape`, `📥 Streamfiles`, `✨ Streamwish`).
- 📅 **Date-Wise Daily Drops (`/today`):** Filters forum topics by upload date, delivering a clean daily release digest.
- ⚡ **Latest Releases (`/latest`):** One-tap access to freshly uploaded videos with quick-view buttons.
- 🔍 **In-Bot Keyword Search (`/search <name>`):** Search the forum database directly from Telegram without visiting the site.
- 📢 **Auto-Pilot Channel Linking (`/setchannel`):**
  - **Zero-Config Auto-Link:** Simply add the bot to any Telegram Channel as **Administrator** — it auto-detects, links, and begins broadcasting new releases!
  - **Manual Control:** Use `/setchannel <category_url>` or `/channels` to customize or unlink.
  - **Duplication Shield:** Built-in SQLite database tracks seen posts so channels never receive duplicate posts.
- 🛡️ **Zero-Leak Security Test Suite:** Pre-commit credential leak detector to safeguard bot tokens and secrets.
- ☁️ **Google Colab Cloud Runner:** Includes `FileScrapper_Runner.ipynb` with an **Ultra Anti-Sleep Shield** for 24/7 free cloud hosting.

---

## 📋 Available Commands

| Command | Description |
| :--- | :--- |
| `/start` | Minimal welcome menu with quick action buttons |
| `/today` | Today's fresh uploads (Daily release digest) |
| `/latest` | View the top latest releases from the forum |
| `/search <query>` | Search videos by title or keyword directly |
| `/scrape <url>` | Manually scrape any specific topic or category |
| `/setchannel [url]` | Link current or specified channel for auto-feed |
| `/channels` | View and manage all active broadcast channels |
| `/domains` | List supported video streaming providers |
| `/help` | Detailed bot user manual |

> 💡 **Tip:** Users can also simply paste any forum URL directly into the chat without typing any command!

---

## 🌐 Supported Streaming Hosts

The bot automatically identifies and generates direct streaming buttons for:
- `vidara.to` (⚡ Vidara)
- `streamtape.com` (🎬 Streamtape)
- `streamfiles.net` (📥 Streamfiles)
- `doodstream.com` / `dood.` (🎥 Doodstream)
- `streamwish` (✨ Streamwish)
- `lplaygo.com` (▶️ Lplaygo)
- `filelions` (🦁 Filelions)
- `dropload` (📦 Dropload)
- `mixdrop` (💧 Mixdrop)
- `streamruby` (💎 Streamruby)

---

## 🚀 Quick Setup & Installation

### 1. Clone the Repository
```bash
git clone https://github.com/levithebutcher/filescrapper.git
cd filescrapper
```

### 2. Create Virtual Environment
```bash
python -m venv .venv
# On Windows:
.venv\Scripts\activate
# On Linux / macOS:
source .venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```
Edit `.env` and set your Telegram Bot Token (from [@BotFather](https://t.me/BotFather)):
```env
BOT_TOKEN=your_bot_token_here
BASE_URL=https://dropmms.com
DEFAULT_CATEGORY_URL=https://dropmms.com/forum/2-general/
FEED_CHECK_INTERVAL=900
MAX_POSTS_PER_FORUM=15
POST_SEND_DELAY=1.5
```

### 5. Launch the Bot
```bash
python bot.py
```

---

## ☁️ Running on Google Colab (24/7 Hosting)

1. Open [`FileScrapper_Runner.ipynb`](FileScrapper_Runner.ipynb) in [Google Colab](https://colab.research.google.com/).
2. Enter your `BOT_TOKEN` in **Step 1** (or add it securely in Colab Secrets 🔑).
3. Click **Runtime ➜ Run all** (`Ctrl + F9`).
4. The runner includes the **Ultra Anti-Sleep Shield** (silent audio loop + DOM pinger + background heartbeat) to maintain uptime.

---

## 🧪 Security & Test Suite

Run tests to ensure everything is operating cleanly:

```bash
# Pre-push security & credential audit
python check_leaks.py

# Full unit test suite
python -m unittest discover tests
```

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
