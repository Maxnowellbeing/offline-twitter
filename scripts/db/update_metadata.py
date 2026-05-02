#!/usr/bin/env python3
"""Quick script to update tweet metadata from Twitter GraphQL API."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app import init_db, db_conn, insert_tweet, parse_twitter_date, CONFIG, fetch_user_tweets

def update_user_data(username: str, count: int = 300, proxy: str = None):
    """Fetch tweets via Twitter API and update DB with full metadata."""
    proxy = proxy or CONFIG["proxy"]
    print(f"Fetching @{username} ({count} tweets)...")

    tweets, display_name = fetch_user_tweets(username, count, proxy=proxy)
    if not tweets:
        print(f"  No tweets found for @{username}")
        return 0

    updated = 0
    inserted = 0

    with db_conn() as conn:
        if display_name:
            conn.execute("""
                INSERT INTO users (username, display_name, last_fetched)
                VALUES (?, ?, datetime('now'))
                ON CONFLICT(username) DO UPDATE SET
                    display_name=COALESCE(excluded.display_name, users.display_name),
                    last_fetched=datetime('now')
            """, (username, display_name))

        for tweet in tweets:
            tweet_id = str(tweet.get("id", ""))
            if not tweet_id:
                continue

            author = tweet.get("author", {})
            text = tweet.get("text", "")
            created_at = tweet.get("createdAt", "")
            metrics = tweet.get("metrics", tweet.get("publicMetrics", {}))
            tweet_username = author.get("username", username)

            existing = conn.execute("SELECT id FROM tweets WHERE id = ?", (tweet_id,)).fetchone()

            if existing:
                conn.execute("""
                    UPDATE tweets SET
                        text = CASE WHEN text = '' OR text IS NULL THEN ? ELSE text END,
                        created_at = CASE WHEN created_at = '' OR created_at IS NULL THEN ? ELSE created_at END,
                        created_at_ts = CASE WHEN created_at_ts = 0 THEN ? ELSE created_at_ts END,
                        reply_count = ?, retweet_count = ?, like_count = ?,
                        view_count = ?, bookmark_count = ?, is_retweet = ?, is_reply = ?,
                        conversation_id = ?, in_reply_to_id = ?, language = ?, source = ?
                    WHERE id = ?
                """, (
                    text, created_at, parse_twitter_date(created_at),
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
                    tweet_id,
                ))
                updated += 1
            else:
                conn.execute("""
                    INSERT OR IGNORE INTO users (username, display_name)
                    VALUES (?, ?)
                """, (tweet_username, author.get("name", tweet_username)))
                insert_tweet(conn, tweet, tweet_username)
                inserted += 1

            # Update media URLs
            for idx, media in enumerate(tweet.get("media", [])):
                media_type = media.get("type", "photo")
                url = media.get("videoUrl", "") if media_type == "video" else media.get("url", "")
                existing_media = conn.execute(
                    "SELECT id FROM media WHERE tweet_id = ? AND sort_order = ?",
                    (tweet_id, idx)
                ).fetchone()

                if existing_media:
                    conn.execute("""
                        UPDATE media SET url = ?, width = ?, height = ?,
                                        alt_text = ?, duration_ms = ?, preview_url = ?, media_type = ?
                        WHERE id = ?
                    """, (
                        url, media.get("width", 0), media.get("height", 0),
                        media.get("altText", ""), media.get("durationMs", 0),
                        media.get("previewUrl", ""), media_type, existing_media[0],
                    ))

    print(f"  Updated: {updated}, Inserted: {inserted}")
    return updated + inserted


def main():
    init_db()

    with db_conn() as conn:
        follows = conn.execute("SELECT username, fetch_count FROM follow_list").fetchall()

    if not follows:
        print("No followed users found. Use the web UI to add users.")
        return

    for row in follows:
        try:
            update_user_data(row["username"], count=row["fetch_count"], proxy=CONFIG["proxy"])
        except Exception as e:
            print(f"  Error: {e}")

    with db_conn() as conn:
        total = conn.execute("SELECT COUNT(*) FROM tweets").fetchone()[0]
        with_text = conn.execute("SELECT COUNT(*) FROM tweets WHERE text != '' AND text IS NOT NULL").fetchone()[0]
        with_date = conn.execute("SELECT COUNT(*) FROM tweets WHERE created_at != '' AND created_at IS NOT NULL").fetchone()[0]
        media_count = conn.execute("SELECT COUNT(*) FROM media WHERE local_path IS NOT NULL").fetchone()[0]
    print(f"\nDone! Total tweets: {total}, with text: {with_text}, with date: {with_date}, media: {media_count}")


if __name__ == "__main__":
    main()
