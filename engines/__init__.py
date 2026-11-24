# engines/__init__.py
"""
Modular Scraper Engines package for FileScrapper.
Provides extensible CMS engines (Invision, WordPress, Tube, LiveCam) and central registry.
"""

from engines.base import (
    BaseEngine,
    HEADERS,
    IST_TZ,
    PROVIDER_PRIORITY,
    _create_session,
    _session,
    _cffi_session,
    get_cffi_session,
    _fetch_url,
    _fetch_soup,
    _is_streaming_link,
    _extract_streaming_links_from_html,
    get_host_display_name,
    get_host_key,
    filter_links_by_preference,
    extract_tags_and_quality,
    UniversalSort,
    SORT_DISPLAY_NAMES,
    UniversalDateResolver,
    parse_relative_to_ist,
    parse_to_ist,
    format_date_ist,
    check_date_filter_match,
    _is_posted_today,
    resolve_cloudfam_url,
    _is_valid_thumbnail_url,
    _clean_highres_image_url,
    _extract_all_image_candidates,
    _extract_thumbnail,
    is_valid_image_bytes,
    is_valid_thumbnail_image,
    optimize_image_for_telegram,
    _resolve_image_viewer_url,
    download_image_bytes,
    parse_slicing_args,
    apply_slice,
    parse_model_range_input,
)

from engines.invision import (
    InvisionCommunityEngine,
    CURATED_DROP_FORUMS,
    CURATED_FORUM_IDS,
    DEFAULT_DROP_FORUMS,
    CURATED_MMSTOWN_FORUMS,
    CURATED_MMSTOWN_FORUM_IDS,
    MMSTOWN_BASE_URL,
    _clean_topic_url,
    is_topic_url,
    is_forum_url,
    is_mmstown_url,
    is_mmstown_topic_url,
    is_mmstown_forum_url,
    _extract_topics_from_soup,
    get_forum_topics,
    get_dropmms_forums,
    get_mmstown_forums,
    get_dropmms_category_stats,
    get_ips_category_stats,
    search_forum,
    get_post_links_from_forum,
    get_post_details,
)

from engines.wordpress import (
    WordPressLockerEngine,
    is_wp_locker_url,
    is_wp_locker_listing_url,
    is_wp_locker_post_url,
    get_wp_post_details,
    get_wp_listing_posts,
    get_wp_categories,
)

from engines.tube import (
    MediaTubeEngine,
    is_mmsvibex_url,
    is_mmsvibex_photo_url,
    is_mmsvibex_listing_url,
    is_mmsvibex_video_url,
    get_mmsvibex_video_details,
    get_mmsvibex_actor_videos,
    get_mmsvibex_photo_details,
    get_mmsvibex_listing_items,
    search_mmsvibex,
)

from engines.livecam import (
    LiveCamEngine,
    is_livecam_url,
    is_livecam_video_url,
    is_livecam_model_url,
    clean_livecam_title,
    format_livecam_date,
    is_livecam_today,
    is_livecam_older_than_today,
    get_livecam_model_stats,
    get_livecam_model_videos,
    get_livecam_video_details,
    format_livecam_card,
    search_livecam_models,
)

from engines.leakedzone import (
    LeakedZoneEngine,
    is_leakedzone_url,
    is_leakedzone_video_url,
    is_leakedzone_model_url,
    decode_leakedzone_token,
    get_leakedzone_video_details,
    get_leakedzone_model_videos,
    search_leakedzone,
)

from engines.kvs import (
    KvsEngine,
    is_kvs_url,
    is_kvs_video_url,
    is_kvs_listing_url,
    clean_kvs_video_url,
    get_kvs_video_details,
    get_kvs_listing_items,
    search_kvs,
)

from engines.thotchicks import (
    ThotChicksEngine,
    is_thotchicks_url,
    is_thotchicks_actor_url,
    is_thotchicks_video_url,
    get_thotchicks_video_details,
    get_thotchicks_listing_items,
    search_thotchicks,
)

from engines.mmsdesi import (
    MmsDesiEngine,
    MMSDESI_CATEGORIES,
    is_mmsdesi_url,
    is_mmsdesi_video_url,
    is_mmsdesi_listing_url,
    get_mmsdesi_video_details,
    get_mmsdesi_category_videos,
    search_mmsdesi,
)

from engines.universal import (
    UniversalFallbackEngine,
    get_universal_post_details,
    is_valid_http_url,
)

from engines.registry import (
    EngineRegistry,
    registry,
    get_engine_for_url,
)
