#!/usr/bin/env python3
"""
Offline Twitter - Web App Backend
A local web application that mimics Twitter's interface with offline content.
"""

import json
import os
import re
import sys
import threading
import time
import urllib.request
import urllib.parse
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

# Load .env file if it exists
_env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(_env_path):
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and "=" in _line and not _line.startswith("#"):
                _key, _value = _line.split("=", 1)
                os.environ.setdefault(_key.strip(), _value.strip())

# ============================================================
# Configuration
# ============================================================
CONFIG = {
    "host": "0.0.0.0",
    "port": 5210,
    "media_base": os.path.join(os.path.dirname(os.path.abspath(__file__)), "media"),
    "proxy": "http://127.0.0.1:1081",
    "db_path": None,  # will be set below
    "fetch_interval": 1800,  # 30 minutes
    "default_count": 100,
}

CONFIG["db_path"] = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tweets.db")

app = Flask(__name__, static_folder="static", static_url_path="")
CORS(app)

# ============================================================
# Database (SQLite via stdlib)
# ============================================================
import sqlite3

def get_db():
    """Get a database connection with row factory."""
    conn = sqlite3.connect(CONFIG["db_path"], timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


@contextmanager
def db_conn():
    """Context manager that ensures DB connection is properly closed."""
    conn = get_db()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def parse_twitter_date(date_str: str) -> int:
    """Convert Twitter date string to Unix timestamp."""
    if not date_str:
        return 0
    try:
        dt = datetime.strptime(date_str, "%a %b %d %H:%M:%S %z %Y")
        return int(dt.timestamp())
    except (ValueError, TypeError):
        return 0


def init_db():
    """Initialize database tables."""
    with db_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                display_name TEXT,
                avatar_url TEXT,
                banner_url TEXT,
                bio TEXT,
                followers_count INTEGER DEFAULT 0,
                following_count INTEGER DEFAULT 0,
                tweets_count INTEGER DEFAULT 0,
                last_fetched TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS tweets (
                id TEXT PRIMARY KEY,
                username TEXT NOT NULL,
                text TEXT,
                created_at TEXT,
                created_at_ts INTEGER DEFAULT 0,
                reply_count INTEGER DEFAULT 0,
                retweet_count INTEGER DEFAULT 0,
                like_count INTEGER DEFAULT 0,
                view_count INTEGER DEFAULT 0,
                bookmark_count INTEGER DEFAULT 0,
                is_retweet INTEGER DEFAULT 0,
                is_reply INTEGER DEFAULT 0,
                conversation_id TEXT,
                in_reply_to_id TEXT,
                language TEXT,
                source TEXT,
                fetched_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (username) REFERENCES users(username)
            );

            CREATE TABLE IF NOT EXISTS media (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tweet_id TEXT NOT NULL,
                media_type TEXT NOT NULL,
                url TEXT,
                local_path TEXT,
                width INTEGER,
                height INTEGER,
                alt_text TEXT,
                duration_ms INTEGER,
                preview_url TEXT,
                sort_order INTEGER DEFAULT 0,
                FOREIGN KEY (tweet_id) REFERENCES tweets(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS follow_list (
                username TEXT PRIMARY KEY,
                added_at TEXT DEFAULT (datetime('now')),
                fetch_count INTEGER DEFAULT 100,
                auto_fetch INTEGER DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS deleted_tweets (
                tweet_id TEXT PRIMARY KEY,
                deleted_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS favorites (
                tweet_id TEXT PRIMARY KEY,
                added_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (tweet_id) REFERENCES tweets(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_tweets_username ON tweets(username);
            CREATE INDEX IF NOT EXISTS idx_media_tweet ON media(tweet_id);
        """)
        # Add created_at_ts column if missing (migration)
        cols = [r[1] for r in conn.execute("PRAGMA table_info(tweets)").fetchall()]
        if "created_at_ts" not in cols:
            conn.execute("ALTER TABLE tweets ADD COLUMN created_at_ts INTEGER DEFAULT 0")
            rows = conn.execute("SELECT id, created_at FROM tweets WHERE created_at_ts = 0").fetchall()
            for r in rows:
                ts = parse_twitter_date(r["created_at"])
                conn.execute("UPDATE tweets SET created_at_ts = ? WHERE id = ?", (ts, r["id"]))
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tweets_created_ts ON tweets(created_at_ts DESC)")


# ============================================================
# Twitter GraphQL API helpers (replaces bird CLI)
# ============================================================
TWITTER_BEARER = "AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"

# GraphQL query IDs — these may need updating if Twitter changes their API
QUERY_USER_BY_SCREEN_NAME = "IGgvgiOx4QZndDHuD3x9TQ"
QUERY_USER_TWEETS = "naBcZ4al-iTCFBYGOAMzBQ"
QUERY_TWEET_DETAIL = "QrLp7AR-eMyamw8D1N9l6A"


def _twitter_headers() -> dict:
    auth_token = os.environ.get("AUTH_TOKEN", "")
    ct0 = os.environ.get("CT0", "")
    return {
        "Authorization": f"Bearer {TWITTER_BEARER}",
        "x-csrf-token": ct0,
        "x-twitter-auth-type": "OAuth2Session",
        "x-twitter-active-user": "yes",
        "x-twitter-client-language": "en",
        "Cookie": f"auth_token={auth_token}; ct0={ct0}",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Content-Type": "application/json",
        "Referer": "https://x.com/",
    }


def _twitter_api_get(url: str, proxy: str | None = None) -> dict | None:
    headers = _twitter_headers()
    req = urllib.request.Request(url, headers=headers)
    if proxy:
        proxy_handler = urllib.request.ProxyHandler({"http": proxy, "https": proxy})
        opener = urllib.request.build_opener(proxy_handler)
    else:
        opener = urllib.request.build_opener()
    try:
        with opener.open(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"[twitter API error] {e}", file=sys.stderr)
        return None


def _twitter_api_post(url: str, body: dict, proxy: str | None = None) -> dict | None:
    headers = _twitter_headers()
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    if proxy:
        proxy_handler = urllib.request.ProxyHandler({"http": proxy, "https": proxy})
        opener = urllib.request.build_opener(proxy_handler)
    else:
        opener = urllib.request.build_opener()
    try:
        with opener.open(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"[twitter API error] {e}", file=sys.stderr)
        return None


def get_user_id(username: str, proxy: str | None = None) -> str | None:
    """Get Twitter user ID from username via GraphQL API."""
    variables = {"screen_name": username, "withSafetyModeUserFields": True}
    features = {
        "hidden_profile_subscriptions_enabled": True,
        "rweb_tipjar_consumption_enabled": True,
        "responsive_web_graphql_exclude_directive_enabled": True,
        "verified_phone_label_enabled": False,
        "subscriptions_verification_info_is_identity_verified_enabled": True,
        "subscriptions_verification_info_verified_since_enabled": True,
        "highlights_tweets_tab_ui_enabled": True,
        "responsive_web_twitter_article_notes_tab_enabled": True,
        "subscriptions_feature_can_gift_premium": True,
        "creator_subscriptions_tweet_preview_api_enabled": True,
        "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
        "responsive_web_graphql_timeline_navigation_enabled": True,
    }
    url = f"https://x.com/i/api/graphql/{QUERY_USER_BY_SCREEN_NAME}/UserByScreenName?variables={urllib.parse.quote(json.dumps(variables))}&features={urllib.parse.quote(json.dumps(features))}"
    data = _twitter_api_get(url, proxy)
    if not data:
        return None
    try:
        return data["data"]["user"]["result"]["rest_id"]
    except (KeyError, TypeError):
        print(f"[twitter] Failed to get user ID for @{username}: {json.dumps(data)[:200]}", file=sys.stderr)
        return None


def _parse_tweet(tweet_result: dict) -> dict | None:
    """Parse a tweet result from GraphQL API into our format."""
    try:
        legacy = tweet_result.get("legacy", {})
        core = tweet_result.get("core", {})
        user_results = core.get("user_results", {}).get("result", {})
        user_legacy = user_results.get("legacy", {})

        tweet_id = legacy.get("id_str", "")
        if not tweet_id:
            return None

        # Get media
        media_list = []
        for m in legacy.get("extended_entities", {}).get("media", []):
            media_type = m.get("type", "photo")
            entry = {
                "type": media_type,
                "url": m.get("media_url_https", ""),
                "width": m.get("original_info", {}).get("width", 0),
                "height": m.get("original_info", {}).get("height", 0),
                "altText": m.get("ext_alt_text", ""),
            }
            if media_type == "video":
                variants = m.get("video_info", {}).get("variants", [])
                best = max(
                    [v for v in variants if v.get("content_type") == "video/mp4"],
                    key=lambda v: v.get("bitrate", 0),
                    default={},
                )
                entry["videoUrl"] = best.get("url", "")
                entry["durationMs"] = m.get("video_info", {}).get("duration_millis", 0)
            media_list.append(entry)

        return {
            "id": tweet_id,
            "text": legacy.get("full_text", ""),
            "createdAt": legacy.get("created_at", ""),
            "author": {
                "name": user_legacy.get("name", ""),
                "username": user_legacy.get("screen_name", ""),
            },
            "metrics": {
                "replyCount": legacy.get("reply_count", 0),
                "retweetCount": legacy.get("retweet_count", 0),
                "likeCount": legacy.get("favorite_count", 0),
                "viewCount": int(tweet_result.get("views", {}).get("count", 0)) if tweet_result.get("views") else 0,
                "bookmarkCount": legacy.get("bookmark_count", 0),
            },
            "isRetweet": "retweeted_status_result" in legacy or legacy.get("retweeted", False),
            "isReply": bool(legacy.get("in_reply_to_status_id_str")),
            "conversationId": legacy.get("conversation_id_str", ""),
            "inReplyToId": legacy.get("in_reply_to_status_id_str", ""),
            "language": legacy.get("lang", ""),
            "source": tweet_result.get("source", ""),
            "media": media_list,
        }
    except Exception as e:
        print(f"[twitter] Parse tweet error: {e}", file=sys.stderr)
        return None


def fetch_user_tweets(username: str, count: int = 100, proxy: str | None = None) -> tuple:
    """Fetch tweets via Twitter GraphQL API. Returns (tweets_list, display_name)."""
    clean_name = username.lstrip("@")
    user_id = get_user_id(clean_name, proxy)
    if not user_id:
        return [], None

    tweets = []
    cursor = None
    display_name = None

    while len(tweets) < count:
        variables = {
            "userId": user_id,
            "count": min(40, count - len(tweets)),
            "includePromotedContent": False,
            "withQuickPromoteEligibilityTweetFields": True,
            "withVoice": True,
            "withV2Timeline": True,
        }
        if cursor:
            variables["cursor"] = cursor

        features = {
            "rweb_tipjar_consumption_enabled": True,
            "responsive_web_graphql_exclude_directive_enabled": True,
            "verified_phone_label_enabled": False,
            "creator_subscriptions_tweet_preview_api_enabled": True,
            "responsive_web_graphql_timeline_navigation_enabled": True,
            "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
            "communities_web_enable_tweet_community_results_fetch": True,
            "c9s_tweet_anatomy_moderator_badge_enabled": True,
            "articles_preview_enabled": True,
            "responsive_web_edit_tweet_api_enabled": True,
            "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
            "view_counts_everywhere_api_enabled": True,
            "longform_notetweets_consumption_enabled": True,
            "responsive_web_twitter_article_tweet_consumption_enabled": True,
            "tweet_awards_web_tipping_enabled": False,
            "creator_subscriptions_quote_tweet_preview_enabled": False,
            "freedom_of_speech_not_reach_fetch_enabled": True,
            "standardized_nudges_misinfo": True,
            "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
            "rweb_video_timestamps_enabled": True,
            "longform_notetweets_rich_text_read_enabled": True,
            "longform_notetweets_inline_media_enabled": True,
            "responsive_web_enhance_cards_enabled": False,
        }

        url = f"https://x.com/i/api/graphql/{QUERY_USER_TWEETS}/UserTweets?variables={urllib.parse.quote(json.dumps(variables))}&features={urllib.parse.quote(json.dumps(features))}"
        data = _twitter_api_get(url, proxy)
        if not data:
            break

        try:
            result = data["data"]["user"]["result"]
            # Handle both timeline and timeline_v2 keys
            timeline_data = result.get("timeline_v2") or result.get("timeline")
            if not timeline_data:
                print(f"[twitter] No timeline data for @{clean_name}", file=sys.stderr)
                break
            timeline = timeline_data["timeline"]
        except (KeyError, TypeError) as e:
            print(f"[twitter] Failed to parse timeline for @{clean_name}: {e}", file=sys.stderr)
            break

        new_tweets = 0
        for instruction in timeline.get("instructions", []):
            # Handle both "entries" (plural) and "entry" (singular) formats
            entries = instruction.get("entries", [])
            if not entries and "entry" in instruction:
                entries = [instruction["entry"]]

            for entry in entries:
                content = entry.get("content", {})
                item_content = content.get("itemContent", {})
                tweet_results = item_content.get("tweet_results", {})
                result = tweet_results.get("result", {})

                # Handle tweet with visibility results
                if result.get("__typename") == "TweetWithVisibilityResults":
                    result = result.get("tweet", {})

                if result.get("__typename") == "Tweet":
                    tweet = _parse_tweet(result)
                    if tweet:
                        tweets.append(tweet)
                        new_tweets += 1
                        if not display_name:
                            display_name = tweet["author"].get("name")

                # Get cursor for next page
                if content.get("entryType") == "TimelineTimelineCursor":
                    if content.get("cursorType") == "Bottom":
                        cursor = content.get("value")

        if new_tweets == 0:
            break

    return tweets[:count], display_name


def fetch_user_profile(username: str, proxy: str | None = None) -> dict | None:
    """Fetch user profile info via Twitter GraphQL API."""
    clean_name = username.lstrip("@")
    user_id = get_user_id(clean_name, proxy)
    if not user_id:
        return None

    features = {
        "hidden_profile_subscriptions_enabled": True,
        "rweb_tipjar_consumption_enabled": True,
        "responsive_web_graphql_exclude_directive_enabled": True,
        "verified_phone_label_enabled": False,
        "subscriptions_verification_info_is_identity_verified_enabled": True,
        "highlights_tweets_tab_ui_enabled": True,
        "responsive_web_graphql_timeline_navigation_enabled": True,
    }
    variables = {"screen_name": clean_name, "withSafetyModeUserFields": True}
    url = f"https://x.com/i/api/graphql/{QUERY_USER_BY_SCREEN_NAME}/UserByScreenName?variables={urllib.parse.quote(json.dumps(variables))}&features={urllib.parse.quote(json.dumps(features))}"
    data = _twitter_api_get(url, proxy)
    if not data:
        return None
    try:
        result = data["data"]["user"]["result"]
        legacy = result.get("legacy", {})
        core = result.get("core", {})
        avatar = result.get("avatar", {})
        avatar_url = avatar.get("image_url", legacy.get("profile_image_url_https", ""))
        if avatar_url:
            avatar_url = avatar_url.replace("_normal", "_400x400")
        return {
            "name": core.get("name", legacy.get("name", "")),
            "username": core.get("screen_name", legacy.get("screen_name", "")),
            "bio": legacy.get("description", ""),
            "followers_count": legacy.get("followers_count", 0),
            "following_count": legacy.get("friends_count", 0),
            "tweets_count": legacy.get("statuses_count", 0),
            "avatar_url": avatar_url,
            "banner_url": legacy.get("profile_banner_url", ""),
        }
    except (KeyError, TypeError):
        return None


# ============================================================
# Media download helpers
# ============================================================
def download_file(url: str, dest: Path, proxy: str | None = None) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        if proxy:
            proxy_handler = urllib.request.ProxyHandler({"http": proxy, "https": proxy})
            opener = urllib.request.build_opener(proxy_handler)
        else:
            opener = urllib.request.build_opener()
        with opener.open(req, timeout=120) as resp:
            with open(dest, "wb") as f:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
        return True
    except Exception as e:
        print(f"  ERROR downloading {url}: {e}", file=sys.stderr)
        return False


def get_media_ext(url: str, media_type: str) -> str:
    path = urllib.parse.urlparse(url).path
    path = re.sub(r':(small|medium|large|thumb|orig)$', '', path)
    known_exts = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".mp4", ".mov", ".avi"}
    for ext in known_exts:
        if path.lower().endswith(ext):
            return ext
    if media_type == "video":
        return ".mp4"
    return ".jpg"


def sanitize_filename(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name).strip('. ')[:80]


# ============================================================
# Core: Fetch & Store
# ============================================================
def fetch_and_store(username: str, count: int = 100, proxy: str | None = None) -> dict:
    """Fetch tweets for a user, download media, store in DB. Returns stats."""
    proxy = proxy or CONFIG["proxy"]
    clean_name = username.lstrip("@")

    print(f"[fetch] Fetching @{clean_name} ...")
    tweets, display_name = fetch_user_tweets(clean_name, count, proxy=proxy)

    if not tweets:
        print(f"[fetch] No tweets found for @{clean_name}")
        return {"new_tweets": 0, "new_media": 0}

    profile = fetch_user_profile(clean_name, proxy=proxy)
    dn = display_name or clean_name
    safe_name = sanitize_filename(dn)
    folder_name = f"{safe_name}(@{clean_name})"

    new_tweets = 0
    new_media = 0

    with db_conn() as conn:
        if profile:
            conn.execute("""
                INSERT INTO users (username, display_name, avatar_url, banner_url, bio,
                                 followers_count, following_count, tweets_count, last_fetched)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(username) DO UPDATE SET
                    display_name=excluded.display_name,
                    avatar_url=excluded.avatar_url,
                    banner_url=excluded.banner_url,
                    bio=excluded.bio,
                    followers_count=excluded.followers_count,
                    following_count=excluded.following_count,
                    tweets_count=excluded.tweets_count,
                    last_fetched=datetime('now')
            """, (
                clean_name,
                profile.get("name", display_name or clean_name),
                profile.get("avatar_url", ""),
                profile.get("banner_url", ""),
                profile.get("bio", ""),
                profile.get("followers_count", 0),
                profile.get("following_count", 0),
                profile.get("tweets_count", 0),
            ))
        else:
            conn.execute("""
                INSERT INTO users (username, display_name, last_fetched)
                VALUES (?, ?, datetime('now'))
                ON CONFLICT(username) DO UPDATE SET
                    display_name=COALESCE(excluded.display_name, users.display_name),
                    last_fetched=datetime('now')
            """, (clean_name, display_name or clean_name))

        for tweet in tweets:
            if not insert_tweet(conn, tweet, clean_name):
                continue
            new_tweets += 1

            tweet_id = str(tweet.get("id", ""))
            created_at = tweet.get("createdAt", "")

            for idx, media in enumerate(tweet.get("media", [])):
                media_type = media.get("type", "photo")
                url = media.get("videoUrl", "") if media_type == "video" else media.get("url", "")
                if not url:
                    continue

                orig_url = url
                if media_type == "photo":
                    base_url = re.sub(r':(small|medium|large|thumb|orig)$', '', url)
                    orig_url = base_url + "?format=jpg&name=orig"

                ext = get_media_ext(url, media_type)
                filename = f"{tweet_id}_{idx+1}{ext}"

                try:
                    dt = datetime.strptime(created_at, "%a %b %d %H:%M:%S %z %Y")
                    date_str = dt.strftime("%Y-%m-%d")
                except (ValueError, TypeError):
                    date_str = "unknown-date"

                local_rel = f"{folder_name}/{date_str}/{filename}"
                local_abs = Path(CONFIG["media_base"]) / local_rel

                if not local_abs.exists():
                    print(f"  Downloading: {filename}")
                    download_file(orig_url, local_abs, proxy=proxy)

                conn.execute("""
                    UPDATE media SET local_path = ? WHERE tweet_id = ? AND sort_order = ?
                """, (local_rel, tweet_id, idx))
                new_media += 1

    print(f"[fetch] @{clean_name}: {new_tweets} new tweets, {new_media} new media")
    return {"new_tweets": new_tweets, "new_media": new_media}


# ============================================================
# Background auto-fetch scheduler
# ============================================================
_scheduler_running = False

def update_query_ids(proxy: str | None = None):
    """Update GraphQL query IDs from Twitter's web app bundle."""
    global QUERY_USER_BY_SCREEN_NAME, QUERY_USER_TWEETS, QUERY_TWEET_DETAIL

    proxy = proxy or CONFIG["proxy"]
    print("[query] Updating query IDs...")

    try:
        # Fetch main page to find bundle URLs
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        }
        req = urllib.request.Request("https://x.com", headers=headers)
        if proxy:
            proxy_handler = urllib.request.ProxyHandler({"http": proxy, "https": proxy})
            opener = urllib.request.build_opener(proxy_handler)
        else:
            opener = urllib.request.build_opener()

        with opener.open(req, timeout=30) as resp:
            html = resp.read().decode("utf-8")

        # Find JavaScript bundle URLs
        bundle_urls = re.findall(r'https://abs\.twimg\.com/responsive-web/client-web[^"]*\.js', html)
        if not bundle_urls:
            print("[query] No bundle URLs found")
            return False

        # Search bundles for query IDs
        for url in bundle_urls:
            try:
                req = urllib.request.Request(url, headers=headers)
                with opener.open(req, timeout=30) as resp:
                    js = resp.read().decode("utf-8")

                # Look for UserByScreenName
                match = re.search(r'queryId:"([^"]+)",operationName:"UserByScreenName"', js)
                if match:
                    QUERY_USER_BY_SCREEN_NAME = match.group(1)

                # Look for UserTweets
                match = re.search(r'queryId:"([^"]+)",operationName:"UserTweets"', js)
                if match:
                    QUERY_USER_TWEETS = match.group(1)

                # Look for TweetDetail
                match = re.search(r'queryId:"([^"]+)",operationName:"TweetDetail"', js)
                if match:
                    QUERY_TWEET_DETAIL = match.group(1)

                if QUERY_USER_BY_SCREEN_NAME and QUERY_USER_TWEETS and QUERY_TWEET_DETAIL:
                    break

            except Exception as e:
                print(f"[query] Error checking bundle: {e}")

        print(f"[query] Updated: UserByScreenName={QUERY_USER_BY_SCREEN_NAME}, UserTweets={QUERY_USER_TWEETS}")
        return True

    except Exception as e:
        print(f"[query] Error updating query IDs: {e}")
        return False


def scheduler_loop():
    """Background thread that periodically fetches all followed users."""
    global _scheduler_running
    _scheduler_running = True

    # Update query IDs on startup
    update_query_ids()

    while _scheduler_running:
        with db_conn() as conn:
            follows = conn.execute(
                "SELECT username, fetch_count FROM follow_list WHERE auto_fetch = 1"
            ).fetchall()

        for row in follows:
            if not _scheduler_running:
                break
            try:
                fetch_and_store(row["username"], count=row["fetch_count"], proxy=CONFIG["proxy"])
            except Exception as e:
                print(f"[scheduler] Error fetching @{row['username']}: {e}")

        # Update query IDs every cycle
        update_query_ids()

        # Wait for next interval
        for _ in range(CONFIG["fetch_interval"]):
            if not _scheduler_running:
                break
            time.sleep(1)


def start_scheduler():
    """Start the background fetch scheduler."""
    t = threading.Thread(target=scheduler_loop, daemon=True)
    t.start()


# ============================================================
# API Routes
# ============================================================

# --- Serve frontend ---
@app.route("/")
def index():
    return send_from_directory("static", "index.html")


# --- Timeline ---
@app.route("/api/timeline")
def api_timeline():
    """Get mixed timeline of all followed users, sorted by date."""
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 30, type=int)
    username = request.args.get("username", None)
    media_only = request.args.get("media_only", 0, type=int)

    conditions = []
    params = []
    if username:
        conditions.append("t.username = ?")
        params.append(username.lstrip("@"))
    if media_only:
        conditions.append("EXISTS (SELECT 1 FROM media m WHERE m.tweet_id = t.id)")
    where = (" WHERE " + " AND ".join(conditions)) if conditions else ""

    with db_conn() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) FROM tweets t{where}", params
        ).fetchone()[0]

        rows = conn.execute(f"""
            SELECT t.*, u.display_name, u.avatar_url
            FROM tweets t
            JOIN users u ON t.username = u.username
            {where}
            ORDER BY t.created_at_ts DESC LIMIT ? OFFSET ?
        """, params + [per_page, (page - 1) * per_page]).fetchall()
        tweets = [dict(r) for r in rows]

    tweet_ids = [t["id"] for t in tweets]
    media_map = get_tweets_media(tweet_ids)
    for t in tweets:
        t["media"] = media_map.get(t["id"], [])

    return jsonify({"tweets": tweets, "page": page, "per_page": per_page, "total": total})


def get_tweets_media(tweet_ids: list[str]) -> dict[str, list]:
    """Batch fetch media for multiple tweets. Returns {tweet_id: [media_list]}."""
    if not tweet_ids:
        return {}
    placeholders = ",".join("?" * len(tweet_ids))
    with db_conn() as conn:
        rows = conn.execute(
            f"SELECT * FROM media WHERE tweet_id IN ({placeholders}) ORDER BY tweet_id, sort_order",
            tweet_ids
        ).fetchall()
    result = {tid: [] for tid in tweet_ids}
    for r in rows:
        result[r["tweet_id"]].append(dict(r))
    return result


def insert_tweet(conn, tweet: dict, username: str) -> bool:
    """Insert a tweet and its media into DB. Returns True if new tweet was inserted."""
    tweet_id = str(tweet.get("id", ""))
    if not tweet_id:
        return False

    existing = conn.execute("SELECT id FROM tweets WHERE id = ?", (tweet_id,)).fetchone()
    if existing:
        return False

    # Skip tweets that were previously deleted by the user
    deleted = conn.execute("SELECT tweet_id FROM deleted_tweets WHERE tweet_id = ?", (tweet_id,)).fetchone()
    if deleted:
        return False

    metrics = tweet.get("metrics", tweet.get("publicMetrics", {}))

    created_at = tweet.get("createdAt", "")
    conn.execute("""
        INSERT OR IGNORE INTO tweets
        (id, username, text, created_at, created_at_ts, reply_count, retweet_count,
         like_count, view_count, bookmark_count, is_retweet, is_reply,
         conversation_id, in_reply_to_id, language, source)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        tweet_id,
        username,
        tweet.get("text", ""),
        created_at,
        parse_twitter_date(created_at),
        metrics.get("replyCount", 0) if isinstance(metrics, dict) else 0,
        metrics.get("retweetCount", 0) if isinstance(metrics, dict) else 0,
        metrics.get("likeCount", 0) if isinstance(metrics, dict) else 0,
        metrics.get("viewCount", 0) if isinstance(metrics, dict) else 0,
        metrics.get("bookmarkCount", 0) if isinstance(metrics, dict) else 0,
        1 if tweet.get("isRetweet") else 0,
        1 if tweet.get("isReply") else 0,
        tweet.get("conversationId", ""),
        tweet.get("inReplyToId", ""),
        tweet.get("language", ""),
        tweet.get("source", ""),
    ))

    for idx, media in enumerate(tweet.get("media", [])):
        media_type = media.get("type", "photo")
        url = media.get("url", "")
        if media_type == "video" and media.get("videoUrl"):
            url = media["videoUrl"]

        conn.execute("""
            INSERT OR IGNORE INTO media (tweet_id, media_type, url, sort_order,
                                         width, height, alt_text, duration_ms, preview_url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            tweet_id, media_type, url, idx,
            media.get("width", 0), media.get("height", 0),
            media.get("altText", ""), media.get("durationMs", 0),
            media.get("previewUrl", ""),
        ))

    return True


# --- User profile ---
@app.route("/api/user/<username>")
def api_user(username):
    """Get user info and stats."""
    with db_conn() as conn:
        user = conn.execute("SELECT * FROM users WHERE username = ?", (username.lstrip("@"),)).fetchone()
        if not user:
            return jsonify({"error": "User not found"}), 404

        user = dict(user)
        stats = conn.execute("""
            SELECT COUNT(*) as tweet_count,
                   SUM(CASE WHEN EXISTS (SELECT 1 FROM media m WHERE m.tweet_id = t.id) THEN 1 ELSE 0 END) as media_tweet_count
            FROM tweets t WHERE t.username = ?
        """, (username.lstrip("@"),)).fetchone()
        user["stats"] = dict(stats)
    return jsonify(user)


# --- User tweets ---
@app.route("/api/user/<username>/tweets")
def api_user_tweets(username):
    """Get tweets for a specific user."""
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 30, type=int)
    media_only = request.args.get("media_only", 0, type=int)
    uname = username.lstrip("@")

    with db_conn() as conn:
        base_where = "WHERE t.username = ?"
        params = [uname]
        if media_only:
            base_where += " AND EXISTS (SELECT 1 FROM media m WHERE m.tweet_id = t.id)"

        total = conn.execute(
            f"SELECT COUNT(*) FROM tweets t {base_where}", params
        ).fetchone()[0]

        query = f"""
            SELECT t.*, u.display_name, u.avatar_url
            FROM tweets t
            JOIN users u ON t.username = u.username
            {base_where}
            ORDER BY t.created_at_ts DESC LIMIT ? OFFSET ?
        """
        params.extend([per_page, (page - 1) * per_page])
        rows = conn.execute(query, params).fetchall()
        tweets = [dict(r) for r in rows]

    tweet_ids = [t["id"] for t in tweets]
    media_map = get_tweets_media(tweet_ids)
    for t in tweets:
        t["media"] = media_map.get(t["id"], [])

    return jsonify({"tweets": tweets, "page": page, "per_page": per_page, "total": total})


# --- Media serving ---
@app.route("/api/media/<path:filepath>")
def api_media(filepath):
    """Serve local media files."""
    media_base = Path(CONFIG["media_base"]).resolve()
    full_path = (media_base / filepath).resolve()
    if not str(full_path).startswith(str(media_base)):
        return jsonify({"error": "Access denied"}), 403
    if not full_path.exists():
        return jsonify({"error": "File not found"}), 404
    return send_from_directory(str(full_path.parent), full_path.name)


@app.route("/api/thumb/<path:filepath>")
def api_thumb(filepath):
    """Serve video thumbnail, generating it if missing."""
    media_base = Path(CONFIG["media_base"]).resolve()
    thumb_base = Path(CONFIG["media_base"]).parent / "thumbs"
    thumb_path = (thumb_base / (filepath + ".jpg")).resolve()
    video_path = (media_base / filepath).resolve()

    if not str(video_path).startswith(str(media_base)):
        return jsonify({"error": "Access denied"}), 403

    if not thumb_path.exists():
        if not video_path.exists():
            return jsonify({"error": "File not found"}), 404
        thumb_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            import subprocess
            subprocess.run(
                ["ffmpeg", "-y", "-i", str(video_path), "-ss", "00:00:01", "-vframes", "1",
                 "-vf", "scale=480:-1", "-q:v", "4", str(thumb_path)],
                capture_output=True, timeout=15
            )
        except Exception as e:
            print(f"[thumb] Error generating thumbnail for {filepath}: {e}", file=sys.stderr)
            return jsonify({"error": "Thumbnail generation failed"}), 500

    if not thumb_path.exists():
        return jsonify({"error": "Thumbnail not available"}), 404
    return send_from_directory(str(thumb_path.parent), thumb_path.name)


def generate_all_thumbnails():
    """Generate thumbnails for all videos missing them."""
    import subprocess
    thumb_base = Path(CONFIG["media_base"]).parent / "thumbs"
    media_base = Path(CONFIG["media_base"]).resolve()

    with db_conn() as conn:
        rows = conn.execute("SELECT local_path FROM media WHERE media_type='video' AND local_path IS NOT NULL AND local_path != ''").fetchall()

    count = 0
    for row in rows:
        rel = row["local_path"]
        video_path = media_base / rel
        thumb_path = thumb_base / (rel + ".jpg")
        if thumb_path.exists() or not video_path.exists():
            continue
        thumb_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-i", str(video_path), "-ss", "00:00:01", "-vframes", "1",
                 "-vf", "scale=480:-1", "-q:v", "4", str(thumb_path)],
                capture_output=True, timeout=15
            )
            if thumb_path.exists():
                count += 1
        except Exception as e:
            print(f"[thumb] Error: {e}", file=sys.stderr)

    print(f"[thumb] Generated {count} thumbnails")


# --- Follow list management ---
@app.route("/api/follows", methods=["GET"])
def api_get_follows():
    """Get list of followed users."""
    with db_conn() as conn:
        rows = conn.execute("""
            SELECT f.*, u.display_name, u.avatar_url, u.bio, u.followers_count,
                   (SELECT COUNT(*) FROM tweets t WHERE t.username = f.username) as tweet_count,
                   u.last_fetched
            FROM follow_list f
            LEFT JOIN users u ON f.username = u.username
            ORDER BY f.added_at DESC
        """).fetchall()
    return jsonify({"follows": [dict(r) for r in rows]})


@app.route("/api/follows", methods=["POST"])
def api_add_follow():
    """Add a user to follow list and fetch their tweets."""
    data = request.json or {}
    username = data.get("username", "").lstrip("@")
    count = data.get("count", CONFIG["default_count"])

    if not username:
        return jsonify({"error": "Username required"}), 400

    with db_conn() as conn:
        conn.execute("""
            INSERT INTO follow_list (username, fetch_count, auto_fetch)
            VALUES (?, ?, 1)
            ON CONFLICT(username) DO UPDATE SET fetch_count=excluded.fetch_count
        """, (username, count))

    def _fetch():
        try:
            fetch_and_store(username, count=count, proxy=CONFIG["proxy"])
        except Exception as e:
            print(f"[follow] Error fetching @{username}: {e}")

    threading.Thread(target=_fetch, daemon=True).start()
    return jsonify({"status": "ok", "username": username})


@app.route("/api/follows/<username>", methods=["DELETE"])
def api_remove_follow(username):
    """Remove a user from follow list."""
    with db_conn() as conn:
        conn.execute("DELETE FROM follow_list WHERE username = ?", (username.lstrip("@"),))
    return jsonify({"status": "ok"})


# --- Manual refresh ---
@app.route("/api/refresh/<username>", methods=["POST"])
def api_refresh(username):
    """Manually trigger a fetch for a specific user."""
    username = username.lstrip("@")
    with db_conn() as conn:
        follow = conn.execute("SELECT fetch_count FROM follow_list WHERE username = ?", (username,)).fetchone()
    count = follow["fetch_count"] if follow else CONFIG["default_count"]

    def _fetch():
        try:
            fetch_and_store(username, count=count, proxy=CONFIG["proxy"])
        except Exception as e:
            print(f"[refresh] Error fetching @{username}: {e}")

    t = threading.Thread(target=_fetch, daemon=True)
    t.start()

    return jsonify({"status": "fetching", "username": username})


@app.route("/api/refresh-all", methods=["POST"])
def api_refresh_all():
    """Manually trigger a fetch for all followed users."""
    def _fetch_all():
        with db_conn() as conn:
            follows = conn.execute("SELECT username, fetch_count FROM follow_list").fetchall()
        for row in follows:
            try:
                fetch_and_store(row["username"], count=row["fetch_count"], proxy=CONFIG["proxy"])
            except Exception as e:
                print(f"[refresh-all] Error: {e}")

    threading.Thread(target=_fetch_all, daemon=True).start()
    return jsonify({"status": "fetching_all"})


# --- Stats ---
@app.route("/api/stats")
def api_stats():
    """Get overall database stats."""
    with db_conn() as conn:
        stats = {
            "total_tweets": conn.execute("SELECT COUNT(*) FROM tweets").fetchone()[0],
            "total_media": conn.execute("SELECT COUNT(*) FROM media").fetchone()[0],
            "total_users": conn.execute("SELECT COUNT(*) FROM users").fetchone()[0],
            "followed_users": conn.execute("SELECT COUNT(*) FROM follow_list").fetchone()[0],
            "photo_count": conn.execute("SELECT COUNT(*) FROM media WHERE media_type='photo'").fetchone()[0],
            "video_count": conn.execute("SELECT COUNT(*) FROM media WHERE media_type='video'").fetchone()[0],
        }
    return jsonify(stats)


# --- Search ---
@app.route("/api/search")
def api_search():
    """Search tweets by text."""
    q = request.args.get("q", "")
    if not q:
        return jsonify({"tweets": []})

    with db_conn() as conn:
        rows = conn.execute("""
            SELECT t.*, u.display_name, u.avatar_url
            FROM tweets t
            JOIN users u ON t.username = u.username
            WHERE t.text LIKE ?
            ORDER BY t.created_at_ts DESC
            LIMIT 50
        """, (f"%{q}%",)).fetchall()
        tweets = [dict(r) for r in rows]

    tweet_ids = [t["id"] for t in tweets]
    media_map = get_tweets_media(tweet_ids)
    for t in tweets:
        t["media"] = media_map.get(t["id"], [])

    return jsonify({"tweets": tweets, "query": q})


# --- Delete tweet ---
@app.route("/api/tweets/<tweet_id>", methods=["DELETE"])
def api_delete_tweet(tweet_id):
    """Delete a tweet and its local media files. Records deletion to prevent re-download."""
    with db_conn() as conn:
        # Record deletion so it won't be re-downloaded
        conn.execute("INSERT OR IGNORE INTO deleted_tweets (tweet_id) VALUES (?)", (tweet_id,))

        media_rows = conn.execute(
            "SELECT local_path FROM media WHERE tweet_id = ?", (tweet_id,)
        ).fetchall()
        for row in media_rows:
            if row["local_path"]:
                full_path = Path(CONFIG["media_base"]) / row["local_path"]
                if full_path.exists():
                    full_path.unlink()
        conn.execute("DELETE FROM media WHERE tweet_id = ?", (tweet_id,))
        conn.execute("DELETE FROM tweets WHERE id = ?", (tweet_id,))
    return jsonify({"status": "ok"})


# --- Favorites ---
@app.route("/api/favorites", methods=["GET"])
def api_get_favorites():
    """Get all favorited tweets."""
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 30, type=int)

    with db_conn() as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM favorites"
        ).fetchone()[0]

        rows = conn.execute("""
            SELECT t.*, u.display_name, u.avatar_url, f.added_at as favorited_at
            FROM favorites f
            JOIN tweets t ON f.tweet_id = t.id
            JOIN users u ON t.username = u.username
            ORDER BY f.added_at DESC
            LIMIT ? OFFSET ?
        """, (per_page, (page - 1) * per_page)).fetchall()
        tweets = [dict(r) for r in rows]

    tweet_ids = [t["id"] for t in tweets]
    media_map = get_tweets_media(tweet_ids)
    for t in tweets:
        t["media"] = media_map.get(t["id"], [])

    return jsonify({"tweets": tweets, "page": page, "per_page": per_page, "total": total})


@app.route("/api/favorites/<tweet_id>", methods=["POST"])
def api_add_favorite(tweet_id):
    """Add a tweet to favorites."""
    with db_conn() as conn:
        # Check if tweet exists
        tweet = conn.execute("SELECT id FROM tweets WHERE id = ?", (tweet_id,)).fetchone()
        if not tweet:
            return jsonify({"error": "Tweet not found"}), 404

        conn.execute("INSERT OR IGNORE INTO favorites (tweet_id) VALUES (?)", (tweet_id,))
    return jsonify({"status": "ok", "tweet_id": tweet_id})


@app.route("/api/favorites/<tweet_id>", methods=["DELETE"])
def api_remove_favorite(tweet_id):
    """Remove a tweet from favorites."""
    with db_conn() as conn:
        conn.execute("DELETE FROM favorites WHERE tweet_id = ?", (tweet_id,))
    return jsonify({"status": "ok", "tweet_id": tweet_id})


@app.route("/api/favorites/check", methods=["GET"])
def api_check_favorites():
    """Check which tweets are favorited. Pass tweet_ids as comma-separated query param."""
    tweet_ids = request.args.get("tweet_ids", "")
    if not tweet_ids:
        return jsonify({"favorites": {}})

    ids = [tid.strip() for tid in tweet_ids.split(",") if tid.strip()]
    if not ids:
        return jsonify({"favorites": {}})

    with db_conn() as conn:
        placeholders = ",".join("?" * len(ids))
        rows = conn.execute(
            f"SELECT tweet_id FROM favorites WHERE tweet_id IN ({placeholders})", ids
        ).fetchall()
        favorited = {row["tweet_id"]: True for row in rows}

    return jsonify({"favorites": favorited})


# --- Cookie management ---
ENV_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")


def read_env() -> dict:
    """Read key-value pairs from .env file."""
    env = {}
    if not os.path.exists(ENV_FILE):
        return env
    with open(ENV_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                env[key.strip()] = value.strip()
    return env


def write_env(updates: dict):
    """Update .env file with new key-value pairs, preserving other entries."""
    existing = read_env()
    existing.update(updates)
    with open(ENV_FILE, "w", encoding="utf-8") as f:
        for key, value in existing.items():
            f.write(f"{key}={value}\n")
    # Update current process environment
    for key, value in updates.items():
        os.environ[key] = value


@app.route("/api/cookies", methods=["GET"])
def api_get_cookies():
    """Get current cookie status (masked)."""
    env = read_env()
    auth = env.get("AUTH_TOKEN", "")
    ct0 = env.get("CT0", "")
    return jsonify({
        "has_auth_token": bool(auth),
        "has_ct0": bool(ct0),
        "auth_token_preview": f"{auth[:8]}...{auth[-8:]}" if len(auth) > 16 else "***",
        "ct0_preview": f"{ct0[:8]}...{ct0[-8:]}" if len(ct0) > 16 else "***",
        "proxy": env.get("HTTP_PROXY", ""),
    })


@app.route("/api/cookies", methods=["POST"])
def api_set_cookies():
    """Update Twitter cookies."""
    data = request.json or {}
    updates = {}
    if "auth_token" in data and data["auth_token"].strip():
        updates["AUTH_TOKEN"] = data["auth_token"].strip()
    if "ct0" in data and data["ct0"].strip():
        updates["CT0"] = data["ct0"].strip()
    if "proxy" in data:
        proxy = data["proxy"].strip()
        updates["HTTP_PROXY"] = proxy
        updates["HTTPS_PROXY"] = proxy
    if not updates:
        return jsonify({"error": "No valid fields provided"}), 400
    write_env(updates)
    return jsonify({"status": "ok", "updated": list(updates.keys())})


# --- Global error handler ---
@app.errorhandler(Exception)
def handle_exception(e):
    """Catch-all error handler to return JSON instead of HTML 500 pages."""
    import traceback
    traceback.print_exc()
    return jsonify({"error": str(e)}), 500


# ============================================================
# Main
# ============================================================
def main():
    import argparse
    parser = argparse.ArgumentParser(description="Offline Twitter Web App")
    parser.add_argument("--port", type=int, default=CONFIG["port"], help="Port to run on")
    parser.add_argument("--no-scheduler", action="store_true", help="Disable auto-fetch scheduler")
    args = parser.parse_args()

    init_db()

    # Generate video thumbnails
    print("[init] Generating video thumbnails...")
    generate_all_thumbnails()

    # Import existing media from F:\V into database
    print("[init] Scanning existing media...")

    if not args.no_scheduler:
        start_scheduler()
        print(f"[init] Auto-fetch scheduler started (interval: {CONFIG['fetch_interval']}s)")

    print(f"[init] Starting server on http://{CONFIG['host']}:{args.port}")
    app.run(host=CONFIG["host"], port=args.port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
