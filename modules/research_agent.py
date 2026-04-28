import os
import json
import time
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

from utils.helpers import load_json, save_json, now_iso
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


# ── Helpers ──────────────────────────────────────────────────────────────────

def _load_recent_topics(memory_file: str, lookback_days: int) -> list[str]:
    if not os.path.exists(memory_file):
        return []
    memory = load_json(memory_file)
    if not isinstance(memory, list):
        return []
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
    if not os.path.exists(memory_file):
        return []
    memory = load_json(memory_file)
    if not isinstance(memory, list):
        return []
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


def _is_duplicate(topic: str, recent_topics: list[str], threshold: float) -> bool:
    if fuzz is None or not recent_topics:
        return False
    for existing in recent_topics:
        ratio = fuzz.token_sort_ratio(topic.lower(), existing.lower()) / 100.0
        if ratio >= threshold:
            return True
    return False


def _load_evergreen_topics() -> list[dict]:
    path = "config/evergreen_topics.json"
    if not os.path.exists(path):
        return []
    return load_json(path)


def _configure_gemini() -> str:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set")
    if genai is None:
        raise RuntimeError("google-generativeai not installed")
    genai.configure(api_key=api_key)
    return api_key


# ── Step 1: Signal Harvest ────────────────────────────────────────────────────

def _harvest_pytrends(timeframe: str = "now 7-d") -> list[str]:
    if TrendReq is None:
        return []
    try:
        pytrends = TrendReq(hl="en-US", tz=300)
        pytrends.build_payload(
            kw_list=["personal finance", "money tips", "credit card", "investing", "debt"],
            cat=7,
            timeframe=timeframe,
            geo="US",
        )
        related = pytrends.related_queries()
        signals = []
        for kw_data in related.values():
            rising = kw_data.get("rising")
            if rising is not None and not rising.empty:
                signals.extend(rising["query"].tolist()[:5])
        # Also grab trending searches
        trending = pytrends.trending_searches(pn="united_states")
        signals.extend(trending[0].tolist()[:10])
        unique = list(dict.fromkeys(signals))  # dedupe, preserve order
        print(f"[research] pytrends ({timeframe}): {len(unique)} signals")
        return unique[:20]
    except Exception as e:
        print(f"[research] pytrends failed ({timeframe}): {e}")
        return []


def _harvest_youtube() -> list[str]:
    if _yt_build is None:
        return []
    try:
        refresh_token  = os.environ.get("YOUTUBE_REFRESH_TOKEN")
        client_id      = os.environ.get("YOUTUBE_CLIENT_ID")
        client_secret  = os.environ.get("YOUTUBE_CLIENT_SECRET")
        if not all([refresh_token, client_id, client_secret]):
            return []

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

        queries = ["personal finance tips", "money saving tips", "credit score tips"]
        titles = []
        for query in queries:
            resp = youtube.search().list(
                part="snippet",
                q=query,
                type="video",
                videoDuration="short",
                order="viewCount",
                publishedAfter=(datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                regionCode="US",
                relevanceLanguage="en",
                maxResults=10,
            ).execute()
            for item in resp.get("items", []):
                title = item["snippet"]["title"].strip()
                if len(title) > 10:
                    titles.append(title)

        print(f"[research] YouTube: {len(titles)} title signals")
        return titles[:20]
    except Exception as e:
        print(f"[research] YouTube signal harvest failed: {e}")
        return []


def _harvest_signals(timeframe: str = "now 7-d") -> dict:
    """Collect signals from pytrends and YouTube. Returns dict with both lists."""
    pytrends_signals = _harvest_pytrends(timeframe)
    youtube_titles   = _harvest_youtube()
    return {
        "pytrends": pytrends_signals,
        "youtube":  youtube_titles,
    }


# ── Step 2: Candidate Generation ─────────────────────────────────────────────

@retry(max_attempts=2, wait_seconds=10, exceptions=(Exception,))
def _generate_candidates(signals: dict, recent_topics: list[str],
                         recent_categories: list[str], model: str) -> list[dict]:
    _configure_gemini()

    # Format signals block
    all_signals = signals.get("pytrends", []) + signals.get("youtube", [])
    if all_signals:
        signals_str = "\n".join(f"- {s}" for s in all_signals[:30])
    else:
        signals_str = "- No trending data available — use your knowledge of current US personal finance topics"

    recent_str  = "\n".join(f"- {t}" for t in recent_topics)  if recent_topics  else "- None"
    cat_str     = "\n".join(f"- {c}" for c in recent_categories) if recent_categories else "- None"

    prompt_template = open("prompts/research_candidates_prompt.txt").read()
    prompt = prompt_template.format(
        signals=signals_str,
        recent_topics=recent_str,
        recent_categories=cat_str,
    )

    client = genai.GenerativeModel(model)
    response = client.generate_content(
        prompt,
        generation_config={"response_mime_type": "application/json"},
    )
    candidates = json.loads(response.text)
    if not isinstance(candidates, list):
        raise ValueError("Candidate generation returned non-list response")
    print(f"[research] Generated {len(candidates)} candidates (target: 5–7)")
    return candidates


# ── Step 3: Filter ────────────────────────────────────────────────────────────

def _filter_candidates(candidates: list[dict], recent_topics: list[str],
                       recent_categories: list[str], threshold: float) -> list[dict]:
    filtered = []
    for c in candidates:
        topic    = c.get("topic", "")
        category = c.get("category", "").lower()

        if _is_duplicate(topic, recent_topics, threshold):
            print(f"[research] Dropped (duplicate): {topic}")
            continue

        if any(category == rc.lower() for rc in recent_categories):
            print(f"[research] Dropped (category conflict — {category}): {topic}")
            continue

        filtered.append(c)

    print(f"[research] After filter: {len(filtered)} candidates remain")
    return filtered


# ── Step 4 + 5: Parallel Scoring + Fact Grounding ────────────────────────────

@retry(max_attempts=2, wait_seconds=5, exceptions=(Exception,))
def _score_one_candidate(candidate: dict, model: str, prompt_template: str) -> dict:
    _configure_gemini()

    prompt = prompt_template.format(
        topic     = candidate.get("topic", ""),
        category  = candidate.get("category", ""),
        angle_type= candidate.get("angle_type", ""),
        hook_seed = candidate.get("hook_seed", ""),
    )

    client = genai.GenerativeModel(model)
    response = client.generate_content(
        prompt,
        generation_config={"response_mime_type": "application/json"},
    )
    result = json.loads(response.text)

    # Enforce hard gate
    if result.get("reliability_score", 1) == 1:
        result["total_score"] = 0

    # Recalculate total_score from parts as a sanity check (only if reliability > 1)
    if result.get("reliability_score", 1) > 1:
        computed = (
            result.get("cpm_score", 0) +
            result.get("trending_score", 0) +
            result.get("scriptability_score", 0) +
            result.get("us_specificity_score", 0) +
            result.get("reliability_score", 0)
        )
        result["total_score"] = computed

    return result


def _score_candidates_parallel(candidates: list[dict], model: str) -> list[dict]:
    results = []
    prompt_template = open("prompts/research_score_prompt.txt").read()
    max_workers = min(len(candidates), 7)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_score_one_candidate, c, model, prompt_template): c
            for c in candidates
        }
        for future in as_completed(futures):
            candidate = futures[future]
            try:
                scored = future.result()
                results.append(scored)
                print(f"[research] Scored '{scored['topic'][:50]}' → {scored['total_score']}/20 (reliability: {scored['reliability_score']})")
            except Exception as e:
                print(f"[research] Scoring failed for '{candidate.get('topic', '?')}': {e} — skipped")
    return results


# ── Step 6: Winner Selection ──────────────────────────────────────────────────

def _pick_winner(scored: list[dict]) -> dict | None:
    valid = [c for c in scored if c.get("total_score", 0) > 0]
    if not valid:
        return None
    return sorted(valid, key=lambda x: x["total_score"], reverse=True)[0]


# ── Main Entry Points ─────────────────────────────────────────────────────────

def run_research(video_id: str, run_dir: str, config: dict) -> dict:
    print(f"[research] Starting topic research for {video_id}")

    memory_file       = "topic_memory.json"
    model             = config["research_model"]
    threshold         = config["duplicate_similarity_threshold"]
    recent_topics     = _load_recent_topics(memory_file, config["topic_memory_lookback_days"])
    recent_categories = _load_recent_categories(memory_file, last_n=4)

    # ── Step 1: Harvest signals (7-day) ──
    signals = _harvest_signals(timeframe="now 7-d")

    # ── Step 2: Generate candidates ──
    candidates = _generate_candidates(signals, recent_topics, recent_categories, model)

    # ── Step 3: Filter ──
    candidates = _filter_candidates(candidates, recent_topics, recent_categories, threshold)

    # ── Step 4: Expand to 30-day if too few ──
    if len(candidates) < 3:
        print(f"[research] Only {len(candidates)} candidates after filter — expanding to 30-day signals")
        signals_30d = _harvest_signals(timeframe="now 30-d")
        candidates_30d = _generate_candidates(signals_30d, recent_topics, recent_categories, model)
        candidates_30d = _filter_candidates(candidates_30d, recent_topics, recent_categories, threshold)
        # Merge, dedupe by topic string
        existing_topics = {c["topic"] for c in candidates}
        for c in candidates_30d:
            if c["topic"] not in existing_topics:
                candidates.append(c)
                existing_topics.add(c["topic"])
        print(f"[research] After 30-day expansion: {len(candidates)} candidates")

    # ── Step 5: Final fallback — top up from evergreen list ──
    if len(candidates) < 3:
        print(f"[research] Still <3 candidates — topping up from evergreen list")
        evergreen = _load_evergreen_topics()
        existing_topics = {c["topic"] for c in candidates}
        for e in evergreen:
            if e["topic"] not in existing_topics:
                if not _is_duplicate(e["topic"], recent_topics, threshold):
                    candidates.append(e)
                    existing_topics.add(e["topic"])
            if len(candidates) >= 6:
                break

    if not candidates:
        raise RuntimeError("[research] No candidates available — pipeline cannot continue")

    print(f"[research] Scoring {len(candidates)} candidates in parallel")

    # ── Step 6: Parallel scoring + fact grounding ──
    scored = _score_candidates_parallel(candidates, model)

    # ── Step 7: Pick winner — fallback to scored evergreen if all rejected ──
    winner = _pick_winner(scored)

    if winner is None:
        print("[research] All candidates rejected — scoring evergreen fallback topics")
        evergreen = _load_evergreen_topics()
        # Filter evergreen against recent topics too
        evergreen_filtered = [
            e for e in evergreen
            if not _is_duplicate(e["topic"], recent_topics, threshold)
        ]
        if evergreen_filtered:
            evergreen_scored = _score_candidates_parallel(evergreen_filtered[:6], model)
            winner = _pick_winner(evergreen_scored)

    if winner is None:
        raise RuntimeError("[research] No valid topic found after all fallbacks — check API connectivity")

    # ── Build final output ──
    result = {
        "video_id":            video_id,
        "topic":               winner.get("topic", ""),
        "category":            winner.get("category", ""),
        "angle_type":          winner.get("angle_type", ""),
        "hook_seed":           winner.get("hook_seed", ""),
        "source_fact":         winner.get("source_fact", ""),
        "source_name":         winner.get("source_name", ""),
        "source_url":          winner.get("source_url", ""),
        "fact_year":           winner.get("fact_year", ""),
        "scores": {
            "cpm_value":           winner.get("cpm_score", 0),
            "trending":            winner.get("trending_score", 0),
            "scriptability":       winner.get("scriptability_score", 0),
            "us_specificity":      winner.get("us_specificity_score", 0),
            "reliability":         winner.get("reliability_score", 0),
        },
        "total_score":         winner.get("total_score", 0),
        "reasoning":           winner.get("reasoning", ""),
        "candidates_evaluated": len(scored),
        "generated_at":        now_iso(),
    }

    output_path = os.path.join(run_dir, "01_research.json")
    save_json(result, output_path)
    print(f"[research] Done. Topic: {result['topic']} | Score: {result['total_score']}/20 | Reliability: {result['scores']['reliability']}")
    return result


def run_research_mock(video_id: str, run_dir: str, config: dict) -> dict:
    print(f"[research][MOCK] Generating mock research for {video_id}")
    result = {
        "video_id":    video_id,
        "topic":       "Most Americans are paying credit card interest they could legally avoid",
        "category":    "credit cards",
        "angle_type":  "mistake-reveal",
        "hook_seed":   "Your credit card company is charging you interest you don't have to pay",
        "source_fact": "The CFPB reports that 45% of credit card holders carry a balance month to month, paying an average of $1,000/year in avoidable interest.",
        "source_name": "CFPB",
        "source_url":  "https://www.consumerfinance.gov/data-research/consumer-credit-trends/",
        "fact_year":   2024,
        "scores": {
            "cpm_value":      4,
            "trending":       3,
            "scriptability":  4,
            "us_specificity": 4,
            "reliability":    4,
        },
        "total_score":          19,
        "reasoning":            "High CPM, clear ego-threat angle, single verifiable stat from CFPB",
        "candidates_evaluated": 10,
        "generated_at":         now_iso(),
    }
    output_path = os.path.join(run_dir, "01_research.json")
    save_json(result, output_path)
    print(f"[research][MOCK] Done. Topic: {result['topic']}")
    return result
