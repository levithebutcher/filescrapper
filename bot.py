# bot.py

import sys
import html
import time
import asyncio
import logging
import platform
from datetime import datetime
from telegram import (
    Update,
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.error import RetryAfter, BadRequest, TelegramError
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)
from config import (
    BOT_NAME,
    BOT_VERSION,
    REPO_URL,
    BOT_TOKEN,
    POST_SEND_DELAY,
    STREAMING_DOMAINS,
    MAX_POSTS_PER_FORUM,
    REQUEST_TIMEOUT,
    BASE_URL,
    PROXIES,
)
from scraper import (
    get_post_links_from_forum,
    get_post_details,
    is_forum_url,
    is_topic_url,
)

# Logging configuration
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Track start time for uptime metric
BOT_START_TIME = time.time()


def get_uptime_str() -> str:
    """Uptime ko human-readable format mein return karein."""
    uptime_seconds = int(time.time() - BOT_START_TIME)
    days, rem = divmod(uptime_seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, seconds = divmod(rem, 60)
    if days > 0:
        return f"{days}d {hours}h {minutes}m {seconds}s"
    if hours > 0:
        return f"{hours}h {minutes}m {seconds}s"
    if minutes > 0:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def format_post_message(details: dict) -> str:
    """
    Ek post ke details ko safe HTML message text mein badlein.
    html.escape() use karke Telegram HTML parse crash se bachata hai.
    """
    safe_title = html.escape(details.get("title", "Untitled"))
    safe_post_url = html.escape(details.get("post_url", ""))

    text = f"📌 <b>{safe_title}</b>\n\n"
    if safe_post_url:
        text += f"🔗 <a href='{safe_post_url}'>Original Post Link</a>\n\n"

    links = details.get("streaming_links", [])
    if links:
        text += f"🎬 <b>Streaming Links ({len(links)}):</b>\n"
        for link in links:
            safe_link = html.escape(link)
            text += f"• <a href='{safe_link}'>{safe_link}</a>\n"
    else:
        text += "❌ <i>Koi streaming link nahi mila is post mein.</i>\n"

    return text


async def _safe_reply_text(update: Update, text: str):
    """
    Long message ko split karke safely send karein (Telegram 4096 char limit).
    """
    max_len = 4000
    msg = update.effective_message
    if not msg:
        return

    if len(text) <= max_len:
        try:
            await msg.reply_text(
                text,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        except RetryAfter as e:
            logger.warning(f"Flood wait: sleeping {e.retry_after}s")
            await asyncio.sleep(e.retry_after + 1)
            await msg.reply_text(
                text,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        except Exception as e:
            logger.error(f"Error in _safe_reply_text: {e}")
        return

    # Split into chunks by line
    parts = []
    current_part = ""
    for line in text.split("\n"):
        if len(current_part) + len(line) + 1 > max_len:
            parts.append(current_part)
            current_part = line + "\n"
        else:
            current_part += line + "\n"
    if current_part:
        parts.append(current_part)

    for part in parts:
        try:
            await msg.reply_text(
                part,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        except RetryAfter as e:
            await asyncio.sleep(e.retry_after + 1)
            await msg.reply_text(
                part,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        except Exception as e:
            logger.error(f"Error sending split part: {e}")
        await asyncio.sleep(0.5)


async def send_post_details(update: Update, context: ContextTypes.DEFAULT_TYPE, post_url: str):
    """
    Ek post ka detail fetch karke bhejein (image + formatted links).
    Non-blocking execution (asyncio.to_thread).
    """
    msg = update.effective_message
    try:
        details = await asyncio.to_thread(get_post_details, post_url)
    except Exception as e:
        logger.warning(f"Error fetching post {post_url}: {e}")
        safe_err = html.escape(str(e))
        if msg:
            await msg.reply_text(
                f"⚠️ <b>Post fetch nahi ho saka:</b>\n<code>{html.escape(post_url)}</code>\n<i>Wajah: {safe_err}</i>",
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        return

    caption = format_post_message(details)
    thumbnail = details.get("thumbnail")

    # Telegram photo caption limit is 1024 characters
    if thumbnail and len(caption) <= 1024 and msg:
        try:
            await msg.reply_photo(
                photo=thumbnail,
                caption=caption,
                parse_mode="HTML",
            )
            return
        except RetryAfter as e:
            await asyncio.sleep(e.retry_after + 1)
            try:
                await msg.reply_photo(
                    photo=thumbnail,
                    caption=caption,
                    parse_mode="HTML",
                )
                return
            except Exception:
                pass
        except Exception as e:
            logger.warning(f"Failed to send thumbnail, falling back to text: {e}")

    # Fallback to text message if no thumbnail, caption > 1024 chars, or image sending failed
    await _safe_reply_text(update, caption)


def get_start_keyboard() -> InlineKeyboardMarkup:
    """Main menu inline buttons."""
    buttons = [
        [
            InlineKeyboardButton("📖 Help Guide", callback_data="cb_help"),
            InlineKeyboardButton("🌐 Domains", callback_data="cb_domains"),
        ],
        [
            InlineKeyboardButton("📊 Bot Status", callback_data="cb_status"),
            InlineKeyboardButton("⚙️ Settings", callback_data="cb_settings"),
        ],
        [
            InlineKeyboardButton("ℹ️ About", callback_data="cb_about"),
            InlineKeyboardButton("⭐ GitHub Repo", url=REPO_URL),
        ],
    ]
    return InlineKeyboardMarkup(buttons)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command handler with interactive keyboard."""
    welcome_text = (
        f"👋 <b>Namaste! Welcome to {BOT_NAME} (v{BOT_VERSION})</b>\n\n"
        "Main aapke liye forum pages aur post links scan karke verified "
        "<b>streaming video links</b> (Vidara, Streamtape, Streamfiles, etc.) extract karta hoon.\n\n"
        "<b>⚡ Quick Start:</b>\n"
        "• Kisi bhi <b>Post ka link</b> ya <b>Forum ka link</b> direct chat mein bhejein.\n"
        "• Ya <code>/scrape &lt;url&gt;</code> command ka use karein.\n\n"
        "Neeche diye gaye buttons ya commands menu ka upyog karein:"
    )
    msg = update.effective_message
    if msg:
        await msg.reply_text(
            welcome_text,
            parse_mode="HTML",
            reply_markup=get_start_keyboard(),
        )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Help command handler with detailed examples."""
    help_text = (
        "📖 <b>File & Streaming Scraper - User Guide</b>\n\n"
        "<b>1️⃣ Single Post Extract:</b>\n"
        "Kisi bhi specific post/topic ka link bhejein:\n"
        "<code>https://dropmms.com/topic/12345-sample-video/</code>\n"
        "➡️ Bot turant uska Title, Thumbnail aur Streaming links nikaal kar bhejega.\n\n"
        "<b>2️⃣ Forum / Category Scrape:</b>\n"
        "Category page ka link bhejein:\n"
        "<code>https://dropmms.com/forum/2-sample-category/</code>\n"
        "➡️ Bot category ke saare posts dhoondh kar har post ke links baari-baari bhejega.\n\n"
        "<b>🛠️ Available Commands:</b>\n"
        "• <code>/start</code> - Main menu & welcome\n"
        "• <code>/help</code> - Yeh madad sandesh\n"
        "• <code>/scrape &lt;url&gt;</code> - Link scan aur extract karein\n"
        "• <code>/domains</code> - Supported video hosts ki list\n"
        "• <code>/ping</code> - Bot speed aur latency check\n"
        "• <code>/status</code> - Uptime aur system health\n"
        "• <code>/settings</code> - Current limits & configs\n"
        "• <code>/about</code> - Version aur source code info\n\n"
        "<i>💡 Tip: Aap bina kisi command ke bhi direct link paste kar sakte hain!</i>"
    )
    msg = update.effective_message
    if msg:
        await msg.reply_text(
            help_text,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )


async def domains_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List supported streaming domains."""
    domains_list = "\n".join([f"• <code>{d}</code>" for d in STREAMING_DOMAINS])
    text = (
        f"🌐 <b>Supported Streaming Hosts ({len(STREAMING_DOMAINS)}):</b>\n\n"
        f"{domains_list}\n\n"
        "<i>💡 Sirf inhi hosts ke links filter karke extract kiye jaate hain. "
        "Naye domains add karne ke liye <code>.env</code> mein <code>STREAMING_DOMAINS</code> update karein.</i>"
    )
    msg = update.effective_message
    if msg:
        await msg.reply_text(text, parse_mode="HTML")


async def ping_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ping command to test responsiveness and latency."""
    msg = update.effective_message
    if not msg:
        return
    start = time.perf_counter()
    sent_msg = await msg.reply_text("🏓 <i>Pinging...</i>", parse_mode="HTML")
    latency_ms = (time.perf_counter() - start) * 1000
    await sent_msg.edit_text(
        f"🏓 <b>Pong!</b>\n⚡ Latency: <code>{latency_ms:.2f} ms</code>\n⏱️ Uptime: <code>{get_uptime_str()}</code>",
        parse_mode="HTML",
    )


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """System and bot status handler."""
    msg = update.effective_message
    if not msg:
        return
    status_text = (
        f"📊 <b>{BOT_NAME} Status & Metrics:</b>\n\n"
        f"• <b>Version:</b> <code>v{BOT_VERSION}</code>\n"
        f"• <b>Status:</b> 🟢 <code>Online & Running</code>\n"
        f"• <b>Uptime:</b> <code>{get_uptime_str()}</code>\n"
        f"• <b>Python:</b> <code>{platform.python_version()}</code>\n"
        f"• <b>Platform:</b> <code>{platform.system()} {platform.release()}</code>\n"
        f"• <b>Max Posts/Forum:</b> <code>{MAX_POSTS_PER_FORUM}</code>\n"
        f"• <b>Post Send Delay:</b> <code>{POST_SEND_DELAY}s</code>\n"
        f"• <b>Request Timeout:</b> <code>{REQUEST_TIMEOUT}s</code>\n"
        f"• <b>Active Domains:</b> <code>{len(STREAMING_DOMAINS)} hosts</code>\n"
    )
    await msg.reply_text(status_text, parse_mode="HTML")


async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show current bot settings."""
    msg = update.effective_message
    if not msg:
        return
    proxy_status = "Enabled" if PROXIES else "Disabled (Direct)"
    settings_text = (
        "⚙️ <b>Current Bot Configuration:</b>\n\n"
        f"• <b>Target Base URL:</b> <code>{BASE_URL}</code>\n"
        f"• <b>Max Posts per Forum:</b> <code>{MAX_POSTS_PER_FORUM}</code>\n"
        f"• <b>Post Delay (Flood Protection):</b> <code>{POST_SEND_DELAY}s</code>\n"
        f"• <b>HTTP Timeout:</b> <code>{REQUEST_TIMEOUT}s</code>\n"
        f"• <b>Proxy Support:</b> <code>{proxy_status}</code>\n"
        f"• <b>Supported Streaming Hosts:</b> <code>{len(STREAMING_DOMAINS)}</code>\n\n"
        "<i>Aap in values ko <code>.env</code> file ke dwara customize kar sakte hain.</i>"
    )
    await msg.reply_text(settings_text, parse_mode="HTML")


async def about_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """About command handler."""
    msg = update.effective_message
    if not msg:
        return
    about_text = (
        f"🤖 <b>{BOT_NAME}</b>\n"
        f"• <b>Version:</b> <code>v{BOT_VERSION}</code>\n"
        "• <b>Language:</b> Python 3.10+\n"
        "• <b>Framework:</b> python-telegram-bot (v22+)\n"
        "• <b>Parser:</b> BeautifulSoup4 & Requests\n"
        f"• <b>Repository:</b> <a href='{REPO_URL}'>GitHub Source</a>\n"
        "• <b>License:</b> MIT\n\n"
        "Yeh bot forums aur websites se direct streaming video links "
        "extract karne ke liye banaya gaya hai."
    )
    await msg.reply_text(
        about_text,
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel operation handler."""
    msg = update.effective_message
    if msg:
        await msg.reply_text("✅ Koi active long-running operation nahi hai jise cancel kiya jaye.")


async def process_url(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str):
    """Core logic to process either a post URL or forum URL."""
    msg = update.effective_message
    if not msg:
        return

    url = url.strip()
    if not url.startswith("http://") and not url.startswith("https://"):
        await msg.reply_text(
            "⚠️ Kripya ek valid URL bhejein (jo <code>http://</code> ya <code>https://</code> se shuru hota ho).\n\n"
            "Example:\n<code>/scrape https://dropmms.com/topic/12345-title/</code>",
            parse_mode="HTML",
        )
        return

    try:
        # Case 1: Topic / Post Link
        if is_topic_url(url):
            status_msg = await msg.reply_text("🔍 <i>Post scan kiya ja raha hai...</i>", parse_mode="HTML")
            await send_post_details(update, context, url)
            try:
                await status_msg.delete()
            except Exception:
                pass

        # Case 2: Forum / Category Page
        elif is_forum_url(url):
            status_msg = await msg.reply_text(
                "🔍 <i>Forum page scan ho raha hai, post links dhoondh raha hoon...</i>",
                parse_mode="HTML",
            )

            post_links = await asyncio.to_thread(get_post_links_from_forum, url)

            if not post_links:
                try:
                    await status_msg.edit_text("❌ Is forum page par koi topic/post nahi mila.")
                except BadRequest:
                    pass
                return

            total = len(post_links)
            try:
                await status_msg.edit_text(
                    f"✅ <b>{total} posts mile!</b> Ab streaming links extract kiye ja rahe hain...",
                    parse_mode="HTML",
                )
            except BadRequest:
                pass

            for i, post_url in enumerate(post_links, start=1):
                await send_post_details(update, context, post_url)
                if i < total:
                    await asyncio.sleep(POST_SEND_DELAY)

        # Case 3: Other link format
        else:
            await msg.reply_text(
                "❓ Yeh link pehchan mein nahi aaya.\n"
                "Kripya forum category (<code>/forum/...</code>) ya direct post (<code>/topic/...</code>) ka link bhejein.",
                parse_mode="HTML",
            )

    except Exception as e:
        logger.exception(f"Error handling URL: {url}")
        safe_err = html.escape(str(e))
        await msg.reply_text(
            f"❌ <b>Error aaya:</b>\n<code>{safe_err}</code>",
            parse_mode="HTML",
        )


async def scrape_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Scrape command handler (/scrape <url>)."""
    msg = update.effective_message
    if not msg:
        return

    if not context.args or len(context.args) == 0:
        await msg.reply_text(
            "ℹ️ <b>Kripya command ke saath URL bhejein:</b>\n\n"
            "<b>Usage:</b>\n"
            "<code>/scrape https://dropmms.com/topic/12345-sample/</code>\n"
            "<code>/scrape https://dropmms.com/forum/2-sample/</code>\n\n"
            "<i>💡 Tip: Aap seedhe link bhi chat mein bhej sakte hain bina /scrape likhe.</i>",
            parse_mode="HTML",
        )
        return

    target_url = context.args[0].strip()
    await process_url(update, context, target_url)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User plain text message (URL) handler."""
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()
    # Check if text is a URL
    if text.startswith("http://") or text.startswith("https://"):
        await process_url(update, context, text)
    else:
        await update.message.reply_text(
            "❓ <b>Samajh nahi aaya!</b>\n\n"
            "Mujhe ek valid URL bhejein (jaise <code>https://...</code>) ya <code>/help</code> dabayein.",
            parse_mode="HTML",
        )


async def callback_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inline keyboard button callback handler."""
    query = update.callback_query
    if not query:
        return

    await query.answer()
    data = query.data

    if data == "cb_help":
        await help_command(update, context)
    elif data == "cb_domains":
        await domains_command(update, context)
    elif data == "cb_status":
        await status_command(update, context)
    elif data == "cb_settings":
        await settings_command(update, context)
    elif data == "cb_about":
        await about_command(update, context)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Global error handler for telegram bot exceptions."""
    logger.error("Exception while handling an update:", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "⚠️ Bot par ek unexpected error aaya. Kripya thodi der baad dobara prayas karein."
            )
        except Exception:
            pass


async def post_init(application: Application):
    """Register bot commands in Telegram UI command menu on startup."""
    commands = [
        BotCommand("start", "Start the bot & show main menu"),
        BotCommand("help", "How to use this bot & examples"),
        BotCommand("scrape", "Extract streaming links from a URL"),
        BotCommand("domains", "List supported video streaming hosts"),
        BotCommand("ping", "Check bot latency & responsiveness"),
        BotCommand("status", "Show bot status & system info"),
        BotCommand("settings", "View current scraping configuration"),
        BotCommand("about", "About this bot & source code"),
        BotCommand("cancel", "Cancel active operations"),
    ]
    try:
        await application.bot.set_my_commands(commands)
        logger.info("✅ Telegram Bot Commands successfully registered with BotFather API!")
    except Exception as e:
        logger.warning(f"Could not register bot commands with Telegram: {e}")


def main():
    if not BOT_TOKEN or BOT_TOKEN == "your_bot_token_here":
        print("\n" + "=" * 60)
        print("❌ ERROR: BOT_TOKEN set nahi hai!")
        print("Kripya `.env` file mein apna Telegram Bot Token daalein:")
        print("BOT_TOKEN=your_token_here")
        print("=" * 60 + "\n")
        sys.exit(1)

    print(f"🤖 Initializing {BOT_NAME} v{BOT_VERSION}...")
    print(f"🔑 Token prefix: {BOT_TOKEN[:10]}...{BOT_TOKEN[-5:] if len(BOT_TOKEN) > 15 else ''}")

    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    # Command Handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("scrape", scrape_command))
    app.add_handler(CommandHandler("extract", scrape_command))  # alias
    app.add_handler(CommandHandler("domains", domains_command))
    app.add_handler(CommandHandler("ping", ping_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("settings", settings_command))
    app.add_handler(CommandHandler("about", about_command))
    app.add_handler(CommandHandler("cancel", cancel_command))

    # Callback Query Handler for Buttons
    app.add_handler(CallbackQueryHandler(callback_query_handler))

    # Text message handler (URLs or fallback)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Global Error Handler
    app.add_error_handler(error_handler)

    logger.info("✅ Bot successfully initialized and polling started...")
    print("🚀 Bot is LIVE! Press Ctrl+C to stop.")
    app.run_polling()


if __name__ == "__main__":
    main()
