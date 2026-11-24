# keyboards.py
"""
Inline Keyboard Builders for FileScrapper.
Centralizes all Telegram InlineKeyboardMarkup and button configurations.
Provides a modern, balanced, and responsive grid layout.
ALL callback_data strings are strictly preserved for 100% handler compatibility.
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from engines.base import filter_links_by_preference, PROVIDER_PRIORITY, get_host_display_name
import db


# --- Universal & Common Keyboards ---

def build_stop_keyboard() -> InlineKeyboardMarkup:
    """Standardized Stop Extraction button used across all scraper loops."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🛑 Stop Extraction", callback_data="btn_stop_scrape")
    ]])


def get_navigation_keyboard() -> InlineKeyboardMarkup:
    """Persistent navigation buttons shown after completed extractions."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔍 Search Again", callback_data="cb_search"),
            InlineKeyboardButton("📁 Categories", callback_data="sp_choose:fm"),
        ],
        [
            InlineKeyboardButton("🏛️ Main Menu", callback_data="cb_main_menu"),
        ],
    ])


def build_back_cancel_row(
    back_callback: str = "cb_main_menu",
    cancel_callback: str = "sp_cancel",
) -> list[InlineKeyboardButton]:
    """Reusable Back + Cancel button pair."""
    return [
        InlineKeyboardButton("🔙 Back", callback_data=back_callback),
        InlineKeyboardButton("❌ Cancel", callback_data=cancel_callback),
    ]


def build_back_cancel_keyboard(
    back_callback: str = "cb_main_menu",
    cancel_callback: str = "sp_cancel",
) -> InlineKeyboardMarkup:
    """Standard 1-row Back and Cancel inline keyboard."""
    return InlineKeyboardMarkup([build_back_cancel_row(back_callback, cancel_callback)])


# --- Card & Media Action Buttons ---

def build_card_keyboard(details: dict, user_pref: str = "streamtape") -> InlineKeyboardMarkup:
    """Build interactive action buttons for the universal post card."""
    buttons = []
    raw_links = details.get("streaming_links", [])
    watch_url = None
    if raw_links:
        if user_pref == "all":
            candidate = raw_links[0]
        else:
            _, filtered, _ = filter_links_by_preference(raw_links, user_pref)
            candidate = filtered[0] if filtered else raw_links[0]
        if candidate.startswith("http://") or candidate.startswith("https://"):
            watch_url = candidate

    row1 = []
    if watch_url:
        row1.append(InlineKeyboardButton("🎬 Watch Video", url=watch_url))

    if details.get("collection_url") and not details.get("hide_collection_link"):
        col_url = details["collection_url"]
        if col_url.startswith("http://") or col_url.startswith("https://"):
            row1.append(InlineKeyboardButton("📁 Collection", url=col_url))

    if row1:
        buttons.append(row1)

    buttons.append([
        InlineKeyboardButton("🔍 Search Again", callback_data="cb_search"),
        InlineKeyboardButton("🏛️ Main Menu", callback_data="cb_main_menu"),
    ])
    return InlineKeyboardMarkup(buttons)


# --- Main Menu & Command Keyboards ---

def build_main_menu_keyboard() -> InlineKeyboardMarkup:
    """Sleek 2-column menu layout for /start command."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⚡ Today's Drops", callback_data="cb_today"),
            InlineKeyboardButton("🔥 Latest Posts", callback_data="cb_latest"),
        ],
        [
            InlineKeyboardButton("🔍 Search Engine", callback_data="cb_search"),
            InlineKeyboardButton("⚙️ Preferred Player", callback_data="cb_sethost"),
        ],
        [
            InlineKeyboardButton("🔗 LiveCam Links", callback_data="cb_setlink"),
            InlineKeyboardButton("📢 Channel Auto-Feed", callback_data="cb_channel_help"),
        ],
        [
            InlineKeyboardButton("📖 User Guide", callback_data="cb_help"),
        ],
    ])


def get_host_settings_keyboard(current_pref: str = "streamtape") -> InlineKeyboardMarkup:
    """Build host selection keyboard with clear checkmarks in a balanced 2-column grid."""
    host_configs = [
        ("streamtape", "🎬 Streamtape"),
        ("vidara", "⚡ Vidara"),
        ("streamfiles", "📥 StreamFiles"),
        ("iplaygo", "▶️ IPlayGo"),
        ("lplaygo", "▶️ LPlayGo"),
        ("abstream", "📺 AbStream"),
        ("uqload", "⚡ Uqload"),
        ("streamcash", "💰 StreamCash"),
        ("direct_mp4", "⚡ Direct MP4"),
        ("direct_zip", "📦 Direct ZIP"),
        ("doodstream", "🦤 DoodStream"),
        ("streamwish", "💫 StreamWish"),
        ("filelions", "🦁 FileLions"),
        ("dropload", "💧 DropLoad"),
        ("mixdrop", "💧 MixDrop"),
        ("streamruby", "💎 StreamRuby"),
        ("cloudfam", "☁️ Cloudfam"),
    ]

    buttons = []
    for i in range(0, len(host_configs), 2):
        row = []
        for key, label in host_configs[i : i + 2]:
            mark = " ✅" if key == current_pref else ""
            row.append(InlineKeyboardButton(f"{label}{mark}", callback_data=f"sethost_{key}"))
        buttons.append(row)

    all_mark = " ✅" if current_pref == "all" else ""
    buttons.append([InlineKeyboardButton(f"🌐 Show All Providers{all_mark}", callback_data="sethost_all")])
    buttons.append([InlineKeyboardButton("🏛️ Main Menu", callback_data="cb_main_menu")])
    return InlineKeyboardMarkup(buttons)


def get_link_mode_keyboard(current_mode: str = "streaming") -> InlineKeyboardMarkup:
    """Build LiveCam link mode selection keyboard with clear checkmarks."""
    modes = [
        ("streaming", "🍿 Streaming Links Only"),
        ("both", "🍿 Streaming + 🌐 Video Page"),
        ("page", "🌐 Video Page Only"),
    ]
    buttons = []
    for mode_key, label in modes:
        mark = " ✅" if mode_key == current_mode else ""
        buttons.append([InlineKeyboardButton(f"{label}{mark}", callback_data=f"setlink_{mode_key}")])

    buttons.append([InlineKeyboardButton("🏛️ Main Menu", callback_data="cb_main_menu")])
    return InlineKeyboardMarkup(buttons)


# --- Search & Platform Selection Keyboards ---

def build_search_platform_keyboard() -> InlineKeyboardMarkup:
    """Platform selection keyboard for /search with no args (3 buttons per row, with WordPress sites displayed)."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💬 DropMMS", callback_data="sp_choose:fm"),
            InlineKeyboardButton("💬 MMSTown", callback_data="sp_choose:mmst"),
            InlineKeyboardButton("⚡ MMSVibex", callback_data="sp_choose:vibex"),
        ],
        [
            InlineKeyboardButton("📹 LiveCam", callback_data="sp_choose:lc"),
            InlineKeyboardButton("🌐 Omaal63", callback_data="sp_wpsite:omaal"),
            InlineKeyboardButton("🌐 DesiJugar", callback_data="sp_wpsite:desijugar"),
        ],
        [
            InlineKeyboardButton("🌐 GulabiHub", callback_data="sp_wpsite:gulabi"),
        ],
        [
            InlineKeyboardButton("🔙 Back", callback_data="cb_main_menu"),
            InlineKeyboardButton("❌ Cancel", callback_data="sp_cancel"),
        ],
    ])


def build_search_execute_platform_keyboard() -> InlineKeyboardMarkup:
    """Platform execution keyboard for /search with query (3 buttons per row, with WordPress sites displayed)."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💬 DropMMS", callback_data="sp_do:fm"),
            InlineKeyboardButton("💬 MMSTown", callback_data="sp_do:mmst"),
            InlineKeyboardButton("⚡ MMSVibex", callback_data="sp_do:vibex"),
        ],
        [
            InlineKeyboardButton("📹 LiveCam", callback_data="sp_do:lc"),
            InlineKeyboardButton("🌐 Omaal63", callback_data="sp_do:omaal"),
            InlineKeyboardButton("🌐 DesiJugar", callback_data="sp_do:desijugar"),
        ],
        [
            InlineKeyboardButton("🌐 GulabiHub", callback_data="sp_do:gulabi"),
        ],
        [
            InlineKeyboardButton("🔙 Back", callback_data="cb_search"),
            InlineKeyboardButton("❌ Cancel", callback_data="sp_cancel"),
        ],
    ])


def build_wp_site_hub_keyboard(site_key: str, back_callback: str = "cb_search") -> InlineKeyboardMarkup:
    """Hub keyboard for WordPress locker sites (Card 2)."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔍 Search Videos", callback_data=f"sp_wpsearch:{site_key}"),
        ],
        [
            InlineKeyboardButton("⚡ Newest Posts", callback_data=f"sp_wplatest:{site_key}"),
            InlineKeyboardButton("📁 Categories", callback_data=f"sp_wpcats:{site_key}"),
        ],
        [
            InlineKeyboardButton("🔙 Back", callback_data=back_callback),
            InlineKeyboardButton("❌ Cancel", callback_data="sp_cancel"),
        ],
    ])


def build_wp_categories_keyboard(
    categories: list[dict],
    site_key: str,
    back_callback: str | None = None,
) -> InlineKeyboardMarkup:
    """Category selection keyboard for WordPress sites (2 per row with Back/Cancel)."""
    back_cb = back_callback or f"sp_wpsite:{site_key}"
    buttons = []
    for i in range(0, len(categories), 2):
        row = []
        c1 = categories[i]
        row.append(InlineKeyboardButton(f"📁 {c1['name']}", callback_data=f"sp_wpcat:{site_key}:{c1['short_id']}"))
        if i + 1 < len(categories):
            c2 = categories[i + 1]
            row.append(InlineKeyboardButton(f"📁 {c2['name']}", callback_data=f"sp_wpcat:{site_key}:{c2['short_id']}"))
        buttons.append(row)

    buttons.append([
        InlineKeyboardButton("🔙 Back", callback_data=back_cb),
        InlineKeyboardButton("❌ Cancel", callback_data="sp_cancel"),
    ])
    return InlineKeyboardMarkup(buttons)


def build_search_results_keyboard(
    items: list[dict],
    page: int,
    total_pages: int,
    platform: str,
    query: str,
) -> InlineKeyboardMarkup:
    """Build item buttons, pagination controls, and navigation for search results."""
    buttons = []

    # 1. Item action buttons (sc_{short_id})
    for idx, itm in enumerate(items, start=1):
        url = itm.get("url") or itm.get("post_url") or itm.get("video_url")
        if url:
            sid = db.get_or_create_short_id(url)
            t = itm.get("title") or itm.get("model_name") or f"Item #{idx}"
            if len(t) > 30:
                t = t[:27] + "..."
            buttons.append([InlineKeyboardButton(f"🎬 #{idx} {t}", callback_data=f"sc_{sid}")])

    # 2. Pagination row
    if total_pages > 1:
        pag_row = []
        if page > 1:
            pag_row.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"sp_p:{platform}:{query}:{page - 1}"))
        pag_row.append(InlineKeyboardButton(f"📄 {page}/{total_pages}", callback_data="sp_noop"))
        if page < total_pages:
            pag_row.append(InlineKeyboardButton("Next ➡️", callback_data=f"sp_p:{platform}:{query}:{page + 1}"))
        buttons.append(pag_row)

    # 3. Platform switch row
    buttons.append([
        InlineKeyboardButton("🔍 Change Platform", callback_data="cb_search"),
        InlineKeyboardButton("🏛️ Main Menu", callback_data="cb_main_menu"),
    ])
    return InlineKeyboardMarkup(buttons)


# --- Slicing & Mode Selection Keyboards ---

def build_mmsvibex_mode_keyboard(short_id: str) -> InlineKeyboardMarkup:
    """Normal vs Advance mode prompt for multi-part MMSVibex videos."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⚡ Normal Mode", callback_data=f"mv_opt:{short_id}:norm"),
            InlineKeyboardButton("🚀 Advance Mode (All Parts)", callback_data=f"mv_opt:{short_id}:adv"),
        ],
        [
            InlineKeyboardButton("❌ Cancel", callback_data="sp_cancel"),
        ]
    ])


def build_slice_selection_keyboard(
    short_id: str,
    counts: list[int] = None,
    prefix: str = "sp_vrun",
) -> InlineKeyboardMarkup:
    """Quick count slice buttons (Top 5, Top 10, Top 20) with Cancel."""
    if counts is None:
        counts = [5, 10, 20]
    row = [InlineKeyboardButton(f"🔝 Top {c}", callback_data=f"{prefix}:{short_id}:{c}") for c in counts]
    return InlineKeyboardMarkup([
        row,
        [InlineKeyboardButton("❌ Cancel", callback_data="sp_cancel")],
    ])


def build_model_sort_keyboard(short_id: str | int, back_callback: str = "cb_search") -> InlineKeyboardMarkup:
    """Sorting options for LiveCam model pages (Card 3 with Back and Cancel)."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🆕 Newest", callback_data=f"sp_sort:{short_id}:newest"),
            InlineKeyboardButton("🔥 Most Viewed", callback_data=f"sp_sort:{short_id}:most_viewed"),
        ],
        [
            InlineKeyboardButton("❤️ Most Liked", callback_data=f"sp_sort:{short_id}:most_liked"),
            InlineKeyboardButton("⏳ Oldest", callback_data=f"sp_sort:{short_id}:oldest"),
        ],
        [
            InlineKeyboardButton("🔙 Back", callback_data=back_callback),
            InlineKeyboardButton("❌ Cancel", callback_data="sp_cancel"),
        ],
    ])


def build_livecam_models_keyboard(models: list[dict], back_callback: str = "cb_search") -> InlineKeyboardMarkup:
    """Clean model list keyboard for LiveCam (Card 2) with only model buttons and Back/Cancel."""
    buttons = []
    for m in models:
        buttons.append([InlineKeyboardButton(f"📹 {m['name']}", callback_data=f"sp_mdl:{m['short_id']}")])
    buttons.append([
        InlineKeyboardButton("🔙 Back", callback_data=back_callback),
        InlineKeyboardButton("❌ Cancel", callback_data="sp_cancel"),
    ])
    return InlineKeyboardMarkup(buttons)


def build_mmsvibex_hub_keyboard(back_callback: str = "cb_search") -> InlineKeyboardMarkup:
    """Clean 3-row hub keyboard for MMSVibex (Card 1)."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔍 Search Videos", callback_data="sp_choose_kw:vibex"),
        ],
        [
            InlineKeyboardButton("⚡ Newest Videos", callback_data="sp_vsort:latest"),
            InlineKeyboardButton("📸 Photo Albums", callback_data="sp_vsort:photos"),
        ],
        [
            InlineKeyboardButton("🔙 Back", callback_data=back_callback),
            InlineKeyboardButton("❌ Cancel", callback_data="sp_cancel"),
        ],
    ])


def build_mmsvibex_options_keyboard(sort_key: str = "latest", back_callback: str = "sp_choose:vibex") -> InlineKeyboardMarkup:
    """Clean minimal keyboard for MMSVibex range selection and post-extraction resurfacing (Card 2)."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔙 Back", callback_data=back_callback),
            InlineKeyboardButton("❌ Cancel", callback_data="sp_cancel"),
        ],
    ])


def build_forum_sort_keyboard(short_id: str | int, back_callback: str = "sp_choose:fm") -> InlineKeyboardMarkup:
    """Sorting and in-forum search options for forum category pages."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔍 Search in this Forum", callback_data=f"sp_search_forum:{short_id}"),
        ],
        [
            InlineKeyboardButton("🆕 Upload Date (Start Date)", callback_data=f"sp_csort:{short_id}:start_date"),
            InlineKeyboardButton("🔄 Recently Updated", callback_data=f"sp_csort:{short_id}:updated"),
        ],
        [
            InlineKeyboardButton("🔙 Back", callback_data=back_callback),
            InlineKeyboardButton("❌ Cancel", callback_data="sp_cancel"),
        ],
    ])


def build_search_results_clean_keyboard(
    page: int,
    total_pages: int,
    page_callback_prefix: str,
    back_callback: str = "cb_search",
    cancel_callback: str = "sp_cancel",
) -> InlineKeyboardMarkup:
    """
    Clean, minimal search results keyboard.
    Row 1: Previous / Next (Pagination)
    Row 2: Back / Cancel
    Keeps chat uncluttered while user selects topics by typing numbers in chat.
    """
    buttons = []
    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton("⬅️ Previous", callback_data=f"{page_callback_prefix}:{page-1}"))
    if total_pages > 1:
        nav_row.append(InlineKeyboardButton(f"📄 {page}/{total_pages}", callback_data="noop"))
    if page < total_pages:
        nav_row.append(InlineKeyboardButton("Next ➡️", callback_data=f"{page_callback_prefix}:{page+1}"))
    if nav_row:
        buttons.append(nav_row)

    buttons.append([
        InlineKeyboardButton("🔙 Back", callback_data=back_callback),
        InlineKeyboardButton("❌ Cancel", callback_data=cancel_callback),
    ])
    return InlineKeyboardMarkup(buttons)


def build_forum_options_keyboard(short_id: str) -> InlineKeyboardMarkup:
    """Slice and sorting options for forum categories."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⚡ Top 5 Posts", callback_data=f"sp_frun:{short_id}:5"),
            InlineKeyboardButton("⚡ Top 10 Posts", callback_data=f"sp_frun:{short_id}:10"),
        ],
        [
            InlineKeyboardButton("📅 Today Only", callback_data=f"sp_ftoday:{short_id}"),
            InlineKeyboardButton("❌ Cancel", callback_data="sp_cancel"),
        ]
    ])


def build_model_options_keyboard(short_id: str) -> InlineKeyboardMarkup:
    """Options for LiveCam model pages."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔝 Top 5", callback_data=f"sp_mrun:{short_id}:5"),
            InlineKeyboardButton("🔝 Top 10", callback_data=f"sp_mrun:{short_id}:10"),
        ],
        [
            InlineKeyboardButton("📅 Today Only", callback_data=f"sp_mtoday:{short_id}"),
            InlineKeyboardButton("🌐 All Videos", callback_data=f"sp_mall:{short_id}"),
        ],
        [
            InlineKeyboardButton("❌ Cancel", callback_data="sp_cancel"),
        ]
    ])


def build_category_options_keyboard(short_id: int | str, sort_val: str = "start_date") -> InlineKeyboardMarkup:
    """Build the working options keyboard for an IPS forum category (Screenshot 3)."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔍 Search in this Forum", callback_data=f"sp_search_forum:{short_id}"),
        ],
        [
            InlineKeyboardButton("⚡ Today's Posts", callback_data=f"sp_cdate:{short_id}:{sort_val}:today"),
            InlineKeyboardButton("📆 Yesterday & Today", callback_data=f"sp_cdate:{short_id}:{sort_val}:yesterday"),
        ],
        [
            InlineKeyboardButton("🔙 Back", callback_data=f"sp_cat:{short_id}"),
            InlineKeyboardButton("❌ Cancel", callback_data="sp_cancel"),
        ],
    ])


def build_channel_management_keyboard() -> InlineKeyboardMarkup:
    """Buttons for /channels management."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("➕ Add Channel", callback_data="cb_channel_add"),
            InlineKeyboardButton("🗑️ Remove Channel", callback_data="cb_channel_rm"),
        ],
        [
            InlineKeyboardButton("🔄 Refresh List", callback_data="cb_channels"),
            InlineKeyboardButton("🏛️ Main Menu", callback_data="cb_main_menu"),
        ]
    ])
