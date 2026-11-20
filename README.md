# 🚀 FileScrapper Telegram Bot

[![Python Version](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Telegram Bot](https://img.shields.io/badge/Telegram-Bot%20API%20v22-blue?logo=telegram)](https://core.telegram.org/bots)
[![Open in Colab](https://colab.research.google.com/assets/colab-badge.svg)](FileScrapper_Runner.ipynb)

A high-performance, asynchronous **Telegram Bot** designed to scan forum topics and categories (such as DropMMS / IPS Community forums) and extract verified, direct video streaming host links (Vidara, Streamtape, Streamfiles, Lplaygo, Doodstream, Streamwish, Filelions, Dropload, Mixdrop, Streamruby).

---

## ✨ Features

- 🎯 **Dual Scraping Modes:**
  - **Single Topic / Post (`/topic/...`):** Extracts title, poster/thumbnail image, and all streaming links.
  - **Forum Category (`/forum/...`):** Scans an entire category and extracts links for all topics found with automatic rate-limit spacing.
- ⚡ **Asynchronous & Non-blocking:** Built on `python-telegram-bot` v22+ with `asyncio.to_thread` for fast, responsive multi-user handling.
- 🛡️ **FloodWait & Rate-Limit Shield:** Built-in delays and retry handlers to avoid Telegram flood limits.
- 📱 **Interactive UI:** Inline buttons and registered slash commands menu in Telegram.
- 🔒 **Zero-Leak Security Test Suite:** Pre-commit credential leak detector to prevent API tokens or secrets from being committed or pushed.
- ☁️ **Google Colab Cloud Runner:** Includes `FileScrapper_Runner.ipynb` with an **Ultra Anti-Sleep Shield** for free cloud hosting.

---

## 📋 Available Commands

| Command | Description |
| :--- | :--- |
| `/start` | Welcome message & interactive menu buttons |
| `/help` | Detailed guide with examples for single topics and forum pages |
| `/scrape <url>` | Scrape and extract links from a specific URL (alias: `/extract`) |
| `/domains` | List all currently supported video streaming hosts |
| `/ping` | Test bot response latency and connection speed |
| `/status` | View bot uptime, system info, and runtime metrics |
| `/settings` | Display active configuration limits and proxy status |
| `/about` | Bot information, version, and repository details |
| `/cancel` | Cancel any active long-running operation |

> 💡 **Tip:** Users can also simply paste any URL directly into the chat without typing any command!

---

## 🌐 Supported Video Hosts

By default, the bot extracts verified video links from:
- `vidara.to`
- `streamtape.com`
- `streamfiles.net`
- `lplaygo.com`
- `doodstream.com` / `dood.`
- `streamwish`
- `filelions`
- `dropload`
- `mixdrop`
- `streamruby`

*(Custom streaming domains can easily be configured via the `STREAMING_DOMAINS` variable in `.env`)*

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
Edit `.env` and paste your Telegram Bot Token (obtained from [@BotFather](https://t.me/BotFather)):
```env
BOT_TOKEN=your_bot_token_here
BASE_URL=https://dropmms.com
MAX_POSTS_PER_FORUM=15
POST_SEND_DELAY=1.5
REQUEST_TIMEOUT=15
```

### 5. Launch the Bot
```bash
python bot.py
```

---

## ☁️ Running on Google Colab (Free 24/7 Hosting)

You can run this bot completely free in the cloud using Google Colab:
1. Open the included [`FileScrapper_Runner.ipynb`](FileScrapper_Runner.ipynb) file in [Google Colab](https://colab.research.google.com/).
2. Enter your `BOT_TOKEN` in **Step 1** (or add it securely in Colab Secrets 🔑).
3. Click **Runtime ➜ Run all** (`Ctrl + F9`).
4. The notebook includes an **Ultra Anti-Sleep Shield** (silent audio loop + DOM pinger + background heartbeat) to prevent idle disconnects.

---

## 🧪 Security & Test Suite

Before making changes or pushing to GitHub, you can run the security audit and unit tests:

### 1. Run Credential Leak Check
```bash
python check_leaks.py
```
*Ensures `.gitignore` is intact, `.env` is ignored, and no real API keys or tokens are in any committable file.*

### 2. Run Full Unit Test Suite
```bash
python -m unittest discover tests
```

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
