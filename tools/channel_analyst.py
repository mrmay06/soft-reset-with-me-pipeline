"""
Channel Analyst Agent
Pulls YouTube Shorts performance data, cross-references with topic_memory.json,
and uses Gemini to generate actionable improvement recommendations.

Usage:
    python tools/channel_analyst.py
    python tools/channel_analyst.py --days 14     # last 14 days
    python tools/channel_analyst.py --email       # send report via email
"""

import os
import sys
import json
import argparse
from datetime import datetime, timedelta
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
import google.generativeai as genai


# ── YouTube client ────────────────────────────────────────────────────────────

def _get_youtube_client():
    creds = Credentials(
        token=None,
        refresh_token=os.environ.get("YOUTUBE_REFRESH_TOKEN"),
        client_id=os.environ.get("YOUTUBE_CLIENT_ID"),
        client_secret=os.environ.get("YOUTUBE_CLIENT_SECRET"),
        token_uri="https://oauth2.googleapis.com/token",
        scopes=["https://www.googleapis.com/auth/youtube"],
    )
    creds.refresh(Request())
    return build("youtube", "v3", credentials=creds)


# ── Data fetch ────────────────────────────────────────────────────────────────

def fetch_channel_stats(yt) -> dict:
    resp = yt.channels().list(part="snippet,statistics", mine=True).execute()
    ch = resp["items"][0]
    return {
        "name":        ch["snippet"]["title"],
        "subscribers": int(ch["statistics"].get("subscriberCount", 0)),
        "total_views": int(ch["statistics"].get("viewCount", 0)),
        "total_videos": int(ch["statistics"].get("videoCount", 0)),
    }


def fetch_recent_videos(yt, days: int = 7) -> list[dict]:
    since = datetime.utcnow() - timedelta(days=days)

    # Get uploads playlist from channel
    ch_resp = yt.channels().list(part="contentDetails", mine=True).execute()
    uploads_playlist = ch_resp["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

    # Page through uploads playlist
    video_ids = []
    next_page = None
    while True:
        pl_resp = yt.playlistItems().list(
            part="snippet", playlistId=uploads_playlist,
            maxResults=50, pageToken=next_page,
        ).execute()
        for item in pl_resp.get("items", []):
            pub = item["snippet"]["publishedAt"][:10]
            pub_dt = datetime.strptime(pub, "%Y-%m-%d")
            if pub_dt >= since:
                video_ids.append(item["snippet"]["resourceId"]["videoId"])
            elif pub_dt < since - timedelta(days=1):
                next_page = None
                break
        next_page = pl_resp.get("nextPageToken")
        if not next_page or not video_ids or len(video_ids) >= 50:
            break

    if not video_ids:
        return []

    details_resp = yt.videos().list(
        part="snippet,statistics",
        id=",".join(video_ids[:50]),
    ).execute()

    videos = []
    for v in details_resp["items"]:
        s = v["statistics"]
        videos.append({
            "youtube_id":   v["id"],
            "title":        v["snippet"]["title"],
            "published_at": v["snippet"]["publishedAt"][:10],
            "views":        int(s.get("viewCount", 0)),
            "likes":        int(s.get("likeCount", 0)),
            "comments":     int(s.get("commentCount", 0)),
        })

    return sorted(videos, key=lambda x: x["views"], reverse=True)


# ── Cross-reference with topic_memory ────────────────────────────────────────

def load_topic_memory() -> dict:
    """Returns a dict keyed by youtube_video_id."""
    path = "topic_memory.json"
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        memory = json.load(f)
    return {entry["youtube_video_id"]: entry for entry in memory if "youtube_video_id" in entry}


def enrich_videos(videos: list[dict], memory: dict) -> list[dict]:
    for v in videos:
        meta = memory.get(v["youtube_id"], {})
        v["category"]     = meta.get("category", "unknown")
        v["topic"]        = meta.get("topic", v["title"])
        v["research_score"] = meta.get("total_score", None)
        v["source_name"]  = meta.get("source_name", "unknown")
        v["pipeline_video"] = bool(meta)
    return videos


# ── Analysis ──────────────────────────────────────────────────────────────────

def analyse_patterns(videos: list[dict]) -> dict:
    pipeline_videos = [v for v in videos if v["pipeline_video"]]

    # Views by category
    cat_views = defaultdict(list)
    for v in pipeline_videos:
        cat_views[v["category"]].append(v["views"])
    category_avg = {
        cat: {"avg": round(sum(views)/len(views), 1), "count": len(views), "total": sum(views)}
        for cat, views in cat_views.items()
    }

    # Title pattern analysis
    emoji_videos    = [v for v in videos if any(ord(c) > 127 for c in v["title"])]
    no_emoji_videos = [v for v in videos if not any(ord(c) > 127 for c in v["title"])]
    hashtag_videos  = [v for v in videos if "#" in v["title"]]

    def avg_views(lst): return round(sum(v["views"] for v in lst) / len(lst), 1) if lst else 0

    # Time slot analysis
    slot_views = defaultdict(list)
    for v in videos:
        try:
            hour = int(v["published_at"].split("T")[1][:2]) if "T" in v.get("published_at", "") else 0
            slot = f"{hour:02d}:00 UTC"
            slot_views[slot].append(v["views"])
        except Exception:
            pass

    # Research score vs views correlation (pipeline videos only)
    scored = [(v["research_score"], v["views"]) for v in pipeline_videos if v["research_score"]]

    return {
        "total_videos_analysed": len(videos),
        "pipeline_videos":       len(pipeline_videos),
        "avg_views":             avg_views(videos),
        "top_3":                 videos[:3],
        "bottom_3":              [v for v in reversed(videos[-3:]) if v["views"] < avg_views(videos)],
        "category_performance":  dict(sorted(category_avg.items(), key=lambda x: x[1]["avg"], reverse=True)),
        "emoji_avg_views":       avg_views(emoji_videos),
        "no_emoji_avg_views":    avg_views(no_emoji_videos),
        "hashtag_avg_views":     avg_views(hashtag_videos),
        "total_views":           sum(v["views"] for v in videos),
        "total_likes":           sum(v["likes"] for v in videos),
        "like_rate":             round(sum(v["likes"] for v in videos) / max(sum(v["views"] for v in videos), 1) * 100, 2),
        "zero_view_count":       sum(1 for v in videos if v["views"] == 0),
        "scored_pairs":          scored,
    }


# ── Gemini analysis ───────────────────────────────────────────────────────────

def generate_ai_report(channel: dict, videos: list[dict], patterns: dict) -> str:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return "GEMINI_API_KEY not set — skipping AI analysis"

    genai.configure(api_key=api_key)

    video_summary = "\n".join([
        f"- [{v['views']} views | {v['likes']} likes] \"{v['title']}\" | category: {v['category']} | research score: {v['research_score']} | date: {v['published_at']}"
        for v in videos[:25]
    ])

    cat_summary = "\n".join([
        f"- {cat}: avg {d['avg']} views across {d['count']} videos"
        for cat, d in patterns["category_performance"].items()
    ])

    prompt = f"""You are a YouTube Shorts growth analyst specialising in US personal finance channels.

CHANNEL: {channel['name']}
Subscribers: {channel['subscribers']}
Total views (all time): {channel['total_views']}
Total videos: {channel['total_videos']}

RECENT PERFORMANCE (last 7 days):
Total views: {patterns['total_views']}
Average views per video: {patterns['avg_views']}
Like rate: {patterns['like_rate']}%
Videos with 0 views: {patterns['zero_view_count']}
Emoji title avg views: {patterns['emoji_avg_views']}
No-emoji title avg views: {patterns['no_emoji_avg_views']}

CATEGORY PERFORMANCE:
{cat_summary}

RECENT VIDEOS (sorted by views):
{video_summary}

TOP 3 PERFORMERS:
{chr(10).join(f'- [{v["views"]} views] {v["title"]} | {v["category"]}' for v in patterns["top_3"])}

ANALYSE and give:
1. What's working — 3 specific patterns from the top performers
2. What's not working — 3 specific problems holding views back
3. Hook quality — are the titles creating strong enough curiosity/ego threat?
4. Category insight — which categories to double down on, which to avoid
5. Like rate is {patterns['like_rate']}% — why is engagement low and what to fix
6. 5 concrete, actionable improvements for the automated pipeline (script, research, title, visual, or posting time)

Be direct and specific. Reference actual video titles from the data. No fluff."""

    model = genai.GenerativeModel("gemini-2.5-flash")
    response = model.generate_content(prompt)
    return response.text


# ── Report formatting ─────────────────────────────────────────────────────────

def format_report(channel: dict, videos: list[dict], patterns: dict, ai_analysis: str, days: int) -> str:
    lines = []
    lines.append("=" * 65)
    lines.append(f"  CHANNEL ANALYSIS REPORT — {channel['name']}")
    lines.append(f"  Period: Last {days} days | Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append("=" * 65)

    lines.append(f"\n📊 CHANNEL OVERVIEW")
    lines.append(f"   Subscribers : {channel['subscribers']}")
    lines.append(f"   Total views : {channel['total_views']:,}")
    lines.append(f"   Total videos: {channel['total_videos']}")

    lines.append(f"\n📈 THIS WEEK")
    lines.append(f"   Videos posted  : {patterns['pipeline_videos']}")
    lines.append(f"   Total views    : {patterns['total_views']:,}")
    lines.append(f"   Avg views/video: {patterns['avg_views']}")
    lines.append(f"   Like rate      : {patterns['like_rate']}%")
    lines.append(f"   Zero-view vids : {patterns['zero_view_count']}")
    lines.append(f"   Emoji title avg: {patterns['emoji_avg_views']} views")
    lines.append(f"   No emoji avg   : {patterns['no_emoji_avg_views']} views")

    lines.append(f"\n🏆 TOP PERFORMERS")
    for i, v in enumerate(patterns["top_3"], 1):
        lines.append(f"   {i}. [{v['views']} views] {v['title'][:60]}")

    lines.append(f"\n📂 VIEWS BY CATEGORY")
    for cat, d in list(patterns["category_performance"].items())[:8]:
        bar = "█" * min(int(d["avg"] / 20), 20)
        lines.append(f"   {cat:<28} {bar} {d['avg']} avg ({d['count']} videos)")

    lines.append(f"\n🤖 AI ANALYSIS & RECOMMENDATIONS")
    lines.append("-" * 65)
    lines.append(ai_analysis)
    lines.append("=" * 65)

    return "\n".join(lines)


# ── Email ─────────────────────────────────────────────────────────────────────

def send_email_report(report: str):
    import smtplib
    from email.mime.text import MIMEText

    sender   = os.environ.get("ALERT_EMAIL_FROM")
    receiver = os.environ.get("ALERT_EMAIL_TO")
    password = os.environ.get("ALERT_EMAIL_PASSWORD")

    if not all([sender, receiver, password]):
        print("[analyst] Email creds not set — skipping email")
        return

    msg = MIMEText(report, "plain")
    msg["Subject"] = f"📊 Raccoon Economy — Weekly Channel Analysis"
    msg["From"]    = sender
    msg["To"]      = receiver

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(sender, password)
        smtp.sendmail(sender, receiver, msg.as_string())
    print("[analyst] Report emailed ✅")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days",  type=int, default=7, help="Lookback days (default: 7)")
    parser.add_argument("--email", action="store_true",  help="Send report via email")
    args = parser.parse_args()

    print("[analyst] Connecting to YouTube...")
    yt = _get_youtube_client()

    print("[analyst] Fetching channel stats...")
    channel = fetch_channel_stats(yt)

    print(f"[analyst] Fetching last {args.days} days of videos...")
    videos = fetch_recent_videos(yt, days=args.days)

    if not videos:
        print("[analyst] No videos found in this period.")
        return

    print(f"[analyst] Found {len(videos)} videos. Cross-referencing with topic_memory...")
    memory  = load_topic_memory()
    videos  = enrich_videos(videos, memory)
    patterns = analyse_patterns(videos)

    print("[analyst] Running Gemini analysis...")
    ai_analysis = generate_ai_report(channel, videos, patterns)

    report = format_report(channel, videos, patterns, ai_analysis, args.days)
    print("\n" + report)

    if args.email:
        send_email_report(report)


if __name__ == "__main__":
    main()
