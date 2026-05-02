#!/usr/bin/env python3
r"""
Import existing media from F:\V into the database.
Scans the directory structure and also fetches tweet metadata via Twitter GraphQL API.
"""

import os
import re
import sys
from pathlib import Path

# Add parent dir to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app import init_db, db_conn, insert_tweet, CONFIG, fetch_user_tweets

def scan_media_dir(base_dir: str) -> list[dict]:
    r"""Scan F:\V for existing media files and build records."""
    base = Path(base_dir)
    results = []

    if not base.exists():
        print(f"Directory not found: {base_dir}")
        return results

    # Pattern: base / "昵称(@用户名)" / "日期" / "推文ID_序号.ext"
    for user_dir in sorted(base.iterdir()):
        if not user_dir.is_dir():
            continue

        # Parse username from folder name like "海象(@feng916749)"
        m = re.match(r'(.+)\(@(\w+)\)$', user_dir.name)
        if not m:
            print(f"  SKIP (can't parse): {user_dir.name}")
            continue

        display_name = m.group(1)
        username = m.group(2)
        print(f"Scanning: {display_name} (@{username})")

        for date_dir in sorted(user_dir.iterdir()):
            if not date_dir.is_dir():
                continue
            date_str = date_dir.name

            for media_file in sorted(date_dir.iterdir()):
                if media_file.is_dir():
                    continue

                # Parse filename: "tweetID_index.ext"
                fm = re.match(r'(\d+)_(\d+)\.(.+)$', media_file.name)
                if not fm:
                    continue

                tweet_id = fm.group(1)
                idx = int(fm.group(2))
                ext = fm.group(3)

                media_type = "video" if ext in ("mp4", "mov", "avi") else "photo"

                local_path = f"{user_dir.name}/{date_str}/{media_file.name}"
                file_size = media_file.stat().st_size

                results.append({
                    "username": username,
                    "display_name": display_name,
                    "tweet_id": tweet_id,
                    "media_type": media_type,
                    "local_path": local_path,
                    "sort_order": idx - 1,
                    "file_size": file_size,
                })

    return results


def import_tweets_from_api(username: str, count: int = 200, proxy: str = None):
    """Fetch tweet data via Twitter GraphQL API and store in DB."""
    proxy = proxy or CONFIG["proxy"]
    print(f"Fetching tweets for @{username} via Twitter API...")

    tweets, display_name = fetch_user_tweets(username, count, proxy=proxy)
    if not tweets:
        print(f"  No tweets found")
        return {}

    tweet_map = {}
    with db_conn() as conn:
        conn.execute("""
            INSERT INTO users (username, display_name, last_fetched)
            VALUES (?, ?, datetime('now'))
            ON CONFLICT(username) DO UPDATE SET
                display_name=COALESCE(excluded.display_name, users.display_name),
                last_fetched=datetime('now')
        """, (username, display_name or username))

        for tweet in tweets:
            insert_tweet(conn, tweet, username)
            tweet_id = str(tweet.get("id", ""))
            if tweet_id:
                tweet_map[tweet_id] = tweet

    print(f"  Imported {len(tweet_map)} tweets for @{username}")
    return tweet_map


def link_local_media(scanned: list[dict]):
    """Link scanned local files to DB media records."""
    linked = 0

    with db_conn() as conn:
        for item in scanned:
            tweet_id = item["tweet_id"]

            conn.execute("""
                INSERT OR IGNORE INTO users (username, display_name)
                VALUES (?, ?)
            """, (item["username"], item["display_name"]))

            tweet = conn.execute("SELECT id FROM tweets WHERE id = ?", (tweet_id,)).fetchone()
            if not tweet:
                conn.execute("""
                    INSERT OR IGNORE INTO tweets (id, username, text, created_at)
                    VALUES (?, ?, ?, ?)
                """, (tweet_id, item["username"], "", ""))

            existing = conn.execute(
                "SELECT id FROM media WHERE tweet_id = ? AND sort_order = ?",
                (tweet_id, item["sort_order"])
            ).fetchone()

            if existing:
                conn.execute("UPDATE media SET local_path = ? WHERE id = ?",
                            (item["local_path"], existing[0]))
            else:
                conn.execute("""
                    INSERT INTO media (tweet_id, media_type, local_path, sort_order)
                    VALUES (?, ?, ?, ?)
                """, (tweet_id, item["media_type"], item["local_path"], item["sort_order"]))

            linked += 1

    print(f"Linked {linked} media files")


def main():
    init_db()

    # Step 1: Scan existing media
    print("=== Step 1: Scanning local media files ===")
    scanned = scan_media_dir(CONFIG["media_base"])
    print(f"Found {len(scanned)} media files\n")

    # Get unique usernames from scanned data
    usernames = list(set(item["username"] for item in scanned))

    # Step 2: Fetch tweet data from Twitter API for each user
    print("\n=== Step 2: Fetching tweet metadata via Twitter API ===")
    for username in usernames:
        try:
            import_tweets_from_api(username, count=300, proxy=CONFIG["proxy"])
        except Exception as e:
            print(f"  Error fetching @{username}: {e}")

    # Step 3: Link local media to DB
    print("\n=== Step 3: Linking local media to database ===")
    link_local_media(scanned)

    # Step 4: Add to follow list
    print("\n=== Step 4: Adding users to follow list ===")
    with db_conn() as conn:
        for username in usernames:
            conn.execute("""
                INSERT OR IGNORE INTO follow_list (username, fetch_count, auto_fetch)
                VALUES (?, 200, 1)
            """, (username,))

    print(f"\n=== Import complete! ===")
    print(f"Users: {usernames}")
    print(f"Media files: {len(scanned)}")

    with db_conn() as conn:
        stats = {
            "tweets": conn.execute("SELECT COUNT(*) FROM tweets").fetchone()[0],
            "media": conn.execute("SELECT COUNT(*) FROM media").fetchone()[0],
            "media_with_local": conn.execute("SELECT COUNT(*) FROM media WHERE local_path IS NOT NULL").fetchone()[0],
        }
    print(f"DB tweets: {stats['tweets']}")
    print(f"DB media: {stats['media']} (with local file: {stats['media_with_local']})")


if __name__ == "__main__":
    main()
