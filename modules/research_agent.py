import os
import json
import random
from datetime import datetime, timedelta

from utils.helpers import load_json, save_json, now_iso, load_config
from utils.retry import retry

try:
    import google.generativeai as genai
except ImportError:
    genai = None

try:
    from pytrends.request import TrendReq
except ImportError:
    TrendReq = None

try:
    from googleapiclient.discovery import build as _yt_build
    from google.oauth2.credentials import Credentials as _YTCreds
    from google.auth.transport.requests import Request as _YTRequest
except ImportError:
    _yt_build = None

try:
    from thefuzz import fuzz
except ImportError:
    fuzz = None


FINANCE_CATEGORIES = {
    "credit cards": ["credit card interest", "credit score", "credit card rewards", "APR", "credit utilization"],
    "investing": ["index funds", "401k", "Roth IRA", "stock market", "ETF", "compound interest"],
    "budgeting": ["50/30/20 rule", "emergency fund", "savings rate", "spending habits"],
    "debt": ["student loans", "debt payoff", "snowball method", "avalanche method", "minimum payments"],
    "mortgage": ["home buying", "mortgage rates", "down payment", "refinance", "PMI"],
    "insurance": ["health insurance", "life insurance", "deductible", "HSA"],
    "taxes": ["tax deductions", "W4", "tax refund", "capital gains", "tax brackets"],
    "banking": ["high yield savings", "HYSA rates", "FDIC insurance", "CD rates", "money market"],
}


def _get_trending_topics() -> list[str]:
    """
    Pull trending finance topics from three sources (in priority order):
    1. YouTube Data API — search recent top-performing Shorts in finance category
    2. pytrends — US trending searches filtered for finance keywords
    3. Static fallback — predefined high-CPM finance categories
    """
    topics = []

    # ── Source 1: YouTube Data API ──────────────────────────────────────────
    try:
        topics = _get_youtube_trending_topics()
        if topics:
            print(f"[research] YouTube API: {len(topics)} trending finance topics found")
            return topics
    except Exception as e:
        print(f"[research] YouTube trending failed: {e} — trying pytrends")

    # ── Source 2: pytrends ──────────────────────────────────────────────────
    if TrendReq is not None:
        try:
            pytrends = TrendReq(hl="en-US", tz=300)
            trending = pytrends.trending_searches(pn="united_states")
            finance_keywords = [kw for cat_kws in FINANCE_CATEGORIES.values() for kw in cat_kws]
            results = []
            for term in trending[0].tolist():
                if any(kw.lower() in term.lower() for kw in finance_keywords):
                    results.append(term)
            if results:
                print(f"[research] pytrends: {len(results)} finance topics found")
                return results[:10]
        except Exception as e:
            print(f"[research] pytrends failed: {e} — using fallback categories")

    # ── Source 3: Static fallback ───────────────────────────────────────────
    print("[research] Using static finance category fallback")
    return list(FINANCE_CATEGORIES.keys())[:5]


def _get_youtube_trending_topics() -> list[str]:
    """
    Search YouTube for recent high-performing Shorts in the US finance space.
    Returns a list of topic strings extracted from video titles.
    """
    if _yt_build is None:
        raise RuntimeError("google-api-python-client not installed")

    api_key = os.environ.get("GEMINI_API_KEY")  # reuse Gemini key won't work for YT Data API
    yt_key = None  # YouTube Data API needs its own key OR OAuth

    # Try OAuth (reuse YouTube credentials)
    refresh_token = os.environ.get("YOUTUBE_REFRESH_TOKEN")
    client_id = os.environ.get("YOUTUBE_CLIENT_ID")
    client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET")

    if not all([refresh_token, client_id, client_secret]):
        raise RuntimeError("YouTube OAuth credentials not set")

    creds = _YTCreds(
        token=None,
        refresh_token=refresh_token,
        client_id=client_id,
        client_secret=client_secret,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=["https://www.googleapis.com/auth/youtube"],
    )
    creds.refresh(_YTRequest())
    youtube = _yt_build("youtube", "v3", credentials=creds)

    # Search for recent popular Shorts in finance (category 27 = Education, also try 25 = News)
    finance_queries = [
        "personal finance tips 2025",
        "money saving tips",
        "credit card tips",
        "investing for beginners",
        "debt payoff strategy",
    ]

    titles = []
    for query in finance_queries[:3]:  # 3 queries to stay within quota
        resp = youtube.search().list(
            part="snippet",
            q=query,
            type="video",
            videoDuration="short",
            order="viewCount",
            publishedAfter=(datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            regionCode="US",
            relevanceLanguage="en",
            maxResults=10,
        ).execute()
        for item in resp.get("items", []):
            title = item["snippet"]["title"]
            if len(title) > 10:
                titles.append(title)

    if not titles:
        raise RuntimeError("YouTube search returned no results")

    # Use Gemini to distill raw titles into clean topic signals
    if genai is None:
        # Fallback: just return raw titles as topics
        return titles[:10]

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return titles[:10]

    genai.configure(api_key=api_key)
    client = genai.GenerativeModel("gemini-2.5-flash")
    prompt = (
        "Below are titles of recent popular US personal finance YouTube Shorts. "
        "Extract 8-10 distinct finance topic signals (not full titles — just the core topic). "
        "Return a JSON array of strings only.\n\n"
        + "\n".join(f"- {t}" for t in titles[:20])
    )
    response = client.generate_content(
        prompt,
        generation_config={"response_mime_type": "application/json"}
    )
    topics = json.loads(response.text)
    if isinstance(topics, list):
        return [str(t) for t in topics[:10]]
    raise RuntimeError("Unexpected Gemini response format")


def _load_recent_topics(memory_file: str, lookback_days: int) -> list[str]:
    if not os.path.exists(memory_file):
        return []
    memory = load_json(memory_file) if os.path.exists(memory_file) else []
    cutoff = datetime.utcnow() - timedelta(days=lookback_days)
    recent = []
    for entry in memory:
        try:
            pub_date = datetime.strptime(entry["published_date"], "%Y-%m-%d")
            if pub_date >= cutoff:
                recent.append(entry["topic"])
        except (KeyError, ValueError):
            continue
    return recent


def _load_recent_categories(memory_file: str, last_n: int = 4) -> list[str]:
    """Return the categories used in the last N videos (conflict radius)."""
    if not os.path.exists(memory_file):
        return []
    memory = load_json(memory_file) if os.path.exists(memory_file) else []
    # Sort by published_date descending, take last_n
    dated = []
    for entry in memory:
        try:
            pub_date = datetime.strptime(entry["published_date"], "%Y-%m-%d")
            dated.append((pub_date, entry.get("category", "")))
        except (KeyError, ValueError):
            continue
    dated.sort(key=lambda x: x[0], reverse=True)
    seen = []
    for _, cat in dated[:last_n]:
        if cat and cat not in seen:
            seen.append(cat)
    return seen


def _is_duplicate(new_topic: str, recent_topics: list[str], threshold: float) -> bool:
    if fuzz is None:
        return False
    for existing in recent_topics:
        ratio = fuzz.token_sort_ratio(new_topic.lower(), existing.lower()) / 100.0
        if ratio >= threshold:
            return True
    return False


@retry(max_attempts=2, wait_seconds=10, exceptions=(Exception,))
def _call_gemini_research(prompt: str, model: str) -> dict:
    if genai is None:
        raise RuntimeError("google-generativeai not installed")
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set")
    genai.configure(api_key=api_key)
    client = genai.GenerativeModel(model)
    response = client.generate_content(
        prompt,
        generation_config={"response_mime_type": "application/json"}
    )
    return json.loads(response.text)


def run_research(video_id: str, run_dir: str, config: dict) -> dict:
    print(f"[research] Starting topic research for {video_id}")

    memory_file = "topic_memory.json"
    recent_topics = _load_recent_topics(memory_file, config["topic_memory_lookback_days"])
    recent_categories = _load_recent_categories(memory_file, last_n=4)
    blocked = config.get("blocked_categories", [])

    trending = _get_trending_topics()
    trending_str = "\n".join(f"- {t}" for t in trending) if trending else "- No trending data"
    recent_str = "\n".join(f"- {t}" for t in recent_topics) if recent_topics else "- None"
    recent_cat_str = "\n".join(f"- {c}" for c in recent_categories) if recent_categories else "- None"
    blocked_str = "\n".join(f"- {c}" for c in blocked) if blocked else "- None"

    prompt_template = open("prompts/research_prompt.txt").read()
    prompt = prompt_template.format(
        trending_topics=trending_str,
        recent_topics=recent_str,
        recent_categories=recent_cat_str,
        blocked_categories=blocked_str,
        video_id=video_id,
        generated_at=now_iso(),
    )

    result = _call_gemini_research(prompt, config["research_model"])

    if _is_duplicate(result["topic"], recent_topics, config["duplicate_similarity_threshold"]):
        raise ValueError(f"[research] Topic too similar to a recent one: {result['topic']}")

    if result.get("total_score", 0) == 0:
        raise ValueError(f"[research] Topic rejected — no valid source found: {result['topic']}")

    output_path = os.path.join(run_dir, "01_research.json")
    save_json(result, output_path)
    print(f"[research] Done. Topic: {result['topic']} (score: {result['total_score']})")
    return result


def run_research_mock(video_id: str, run_dir: str, config: dict) -> dict:
    print(f"[research][MOCK] Generating mock research for {video_id}")
    result = {
        "video_id": video_id,
        "topic": "Pay your credit card twice a month to avoid interest",
        "category": "credit cards",
        "angle": "Most people overpay because they misunderstand statement cycles",
        "source_fact": "The CFPB says most Americans don't know their billing cycle affects how much interest they pay.",
        "source_name": "CFPB",
        "source_url": "https://www.consumerfinance.gov/consumer-tools/credit-cards/",
        "scores": {
            "cpm_value": 4,
            "trending": 3,
            "scriptability": 4,
            "us_specificity": 4,
            "reliability": 4,
        },
        "total_score": 19,
        "generated_at": now_iso(),
    }
    output_path = os.path.join(run_dir, "01_research.json")
    save_json(result, output_path)
    print(f"[research][MOCK] Done.")
    return result
