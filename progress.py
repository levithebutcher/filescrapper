# progress.py
"""
Progress and visual status indicators for FileScrapper.
Provides customizable ASCII/Unicode progress bars and visual progress cards for Telegram.
All visual symbols, widths, and counter styles can be edited here without touching business logic.
"""

import html


def render_progress_bar(
    current: int,
    total: int,
    length: int = 10,
    fill_char: str = "█",
    empty_char: str = "░",
) -> str:
    """
    Render a clean text progress bar with percentage.
    Example: [██████░░░░] 60% (6/10)
    """
    if total <= 0:
        return f"[{fill_char * length}] 100% ({current}/{current})"

    fraction = max(0.0, min(1.0, current / total))
    filled_len = int(round(length * fraction))
    empty_len = length - filled_len
    percent = int(round(fraction * 100))

    bar = (fill_char * filled_len) + (empty_char * empty_len)
    return f"[{bar}] {percent}% ({current}/{total})"


def format_progress_card(
    action_title: str,
    current: int,
    total: int,
    item_name: str = "",
    extra_info: str = "",
) -> str:
    """
    Format a complete Telegram progress card with title, progress bar, and item status.
    """
    bar_str = render_progress_bar(current, total, length=10)
    lines = [
        "<blockquote>",
        f"⏳ <b>{html.escape(action_title)}</b>",
        f"<code>{bar_str}</code>",
    ]
    if item_name:
        lines.append(f"📦 <i>Current: {html.escape(item_name)}</i>")
    if extra_info:
        lines.append(f"ℹ️ {html.escape(extra_info)}")
    lines.append("</blockquote>")
    return "\n".join(lines)
