# AGENTS.md — Master Architecture & Engineering Directives

This document defines the strict engineering guidelines, architecture patterns, UI standards, and contribution policies for all AI coding agents and human developers working on the FileScrapper Bot codebase.

---

## 1. System Architecture & Modular Layout

The repository is structured to maintain high cohesion and low coupling. No monolithic files (e.g., files over 1,500 lines) should be created or expanded.

```text
├── bot.py                  # Application entry point, CLI flags, lifecycle & dispatch initialization
├── handlers/               # Modular event & message handlers
│   ├── __init__.py         # Package exports
│   ├── commands.py         # Standard commands (/start, /mode, /help, /search, /cancel, etc.)
│   ├── search_flow.py      # Search orchestration, state tracking & pagination
│   ├── global_search.py    # Cross-platform federated search & deduplication engine
│   ├── text_input.py       # Message router for manual text queries, numbers, and pagination input
│   └── callbacks/          # Prefix-based callback query dispatchers
│       ├── __init__.py     # Callback router registry
│       ├── base.py         # Common callback response helpers
│       ├── lz.py           # LeakedZone platform callbacks (lz_*)
│       ├── kvs.py          # KVS platforms callbacks: X-Video Tube (xvid_*) & HornySapiens (hs_*)
│       ├── tc.py           # ThotChicks platform callbacks (tc_*)
│       ├── desi.py         # MMSDesi platform callbacks (desi_*)
│       └── mms.py          # MMSMaza & Invision forum callbacks (mms_*, sp_*)
├── engines/                # Isolated platform scrapers & network interfaces
│   ├── base.py             # Network client, curl_cffi Cloudflare session, HTML parsers, headers
│   ├── kvs.py              # KVS platform engine (X-Video Tube, HornySapiens)
│   ├── leakedzone.py       # LeakedZone engine (WAF-aware candidate probing)
│   ├── thotchicks.py       # ThotChicks engine
│   ├── invision.py         # Forum & topics engines (MMSMaza, DropMMS, etc.)
│   └── livecam.py          # Livecamrips engine
├── keyboards.py            # Standardized Telegram inline keyboard factories
├── ui.py                   # Presentation layer: Card templates, HTML message formatters
├── db.py                   # SQLite persistence, schema, caching & scrape session management
└── tests/                  # Automated test suite (100% pass mandatory)
```

---

## 2. Standardized UI & Keyboard Layout Rules

All platform hubs and cards must strictly follow these standardized layout tiers to provide a uniform user experience across existing and future sites:

### 2.1 Platform Hub Keyboards
Every platform hub (Sites 1–4, Forum Hubs, etc.) must adhere to a 3-tier structure:
1. **Top Row:** Dedicated search action button: `[🔍 Search <Platform/Type>]`
2. **Middle Rows:** Platform-specific feature buttons (e.g., Sorting options: Latest, Top Rated, Most Viewed; Categories; Popular Models; Page Navigation)
3. **Bottom Row:** Fixed two-button control footer: `[🔙 Back]` and `[❌ Cancel]`

### 2.2 Model / Search Selection Results
- **Selection by Buttons Only:** When presenting a list of matching models, categories, or video items, **DO NOT** duplicate the items in the message text body (e.g. do not print `1. Diana\n2. Kristilacroix`).
- The message body must contain only a concise header (e.g. `🔍 <b>X-Video Tube Models Matching 'query':</b>\n\n<i>Select a model below:</i>`).
- The inline buttons themselves serve as the interactive selection list.

### 2.3 Post Card Standards (Sites 1–4)
For Platforms 1 to 4 (LeakedZone, X-Video Tube, HornySapiens, ThotChicks):
- **NO `Watch Video` Button:** The inline keyboard must NEVER include a `[🎬 Watch Video]` button.
- **NO `Source Webpage` Link:** Do not display redundant source webpage buttons on post cards.
- **Direct Video URL in Code Block:** The direct playable/downloadable video link (MP4/HLS) must be displayed inside an HTML `<code>...</code>` block so users can copy or stream directly with a single tap.
- **Card Footer:** The inline keyboard on post cards must consist only of navigation controls: `[🔙 Back]` and `[❌ Cancel]`.

---

## 3. Search Relevance & Engine Standards

### 3.1 Strict Model Matching (KVS & Directory Engines)
- When a user searches for a specific model (e.g., `Jasmine Sherni`), the search engine must perform token-based or substring validation against the retrieved models.
- **Never Fall Back to Random Models:** If no models match the query, the engine must return 0 results (an empty list) rather than returning default, popular, or unrelated models.
- If 0 matches are found, the UI must report `❌ No models found matching '<query>'.` with a `[🔙 Back]` button.

### 3.2 Streaming Engine Priority
When resolving multi-host streaming links (e.g. on MMSMaza or forums), priority order is:
1. `Streamtape` (primary default)
2. `DoodStream`
3. `Streamwish`
4. Direct / other available hosts

---

## 4. Global Multi-Platform Search Engine (`[🌐 Search All Sites]`)

The bot features a federated cross-platform search capability:
1. **Entry Point:** `[🌐 Search All Sites]` button on the top row of the main `/search` menu.
2. **Concurrent Execution:** Queries all enabled platform engines simultaneously using `asyncio.gather` with isolated timeout boundaries per engine.
3. **Smart Deduplication & Merger Pipeline:**
   - **Fuzzy Title Match:** Titles are normalized (punctuation stripped, lowercased, common filler tokens removed). If title similarity is $\ge 80\%$, items are candidates for consolidation.
   - **Duration Tolerance:** If video duration is available on both items and matches within $\pm 10$ seconds, items are treated as duplicate mirrors of the same video.
   - **Unified Mirror Card:** Duplicate items are merged into a single post card that displays all available streaming and source links as mirror options (e.g. `Mirror 1: X-Video Tube`, `Mirror 2: HornySapiens`).

---

## 5. Developer & Operational Policies

### 5.1 ZERO Adult Terms in Git Commits (CRITICAL)
- All Git commit messages, branch names, pull request descriptions, and public-facing comments **MUST STRICTLY AVOID** adult terms, adult platform names, or explicit vocabulary.
- Always use professional engineering terminology:
  - *Incorrect:* `fix: xvideo model search porn video url`
  - *Correct:* `fix(engine): optimize token matching and direct media link extraction`
  - *Correct:* `feat(handlers): implement unified multi-source search pipeline`
  - *Correct:* `refactor(ui): standardize keyboard layout and suppress redundant action buttons`

### 5.2 100% Test Pass Requirement
- Before any code commit, run the full test suite:
  ```bash
  python -m unittest discover tests
  ```
- All tests must pass with zero failures and zero errors before changes are finalized.
- Whenever new handlers or engines are introduced, comprehensive unit tests must be added in `tests/`.
