from __future__ import annotations
import os
import time
from difflib import SequenceMatcher
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from utils.helpers import load_json, save_json, now_iso
from utils.retry import retry
from utils.gemini_client import generate_json
from utils.performance_insights import summarize_performance_for_prompt

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
    return [
        entry.get("topic", "")
        for entry in _load_recent_entries(memory_file, lookback_days)
        if entry.get("topic", "")
    ]


def _load_recent_entries(memory_file: str, lookback_days: int) -> list[dict]:
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
                recent.append(entry)
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


def _load_todays_categories(memory_file: str) -> list[str]:
    """Return all categories already published today (UTC). Hard-blocks same-day repeats."""
    if not os.path.exists(memory_file):
        return []
    memory = load_json(memory_file)
    if not isinstance(memory, list):
        return []
    today = datetime.utcnow().strftime("%Y-%m-%d")
    cats = []
    for entry in memory:
        if entry.get("published_date", "") == today:
            cat = entry.get("category", "").strip().lower()
            if cat and cat not in cats:
                cats.append(cat)
    return cats


def _load_recent_angles(memory_file: str, lookback_days: int = 3) -> list[str]:
    """Return distinct angle_types used in the last N days — for angle diversity tracking."""
    if not os.path.exists(memory_file):
        return []
    memory = load_json(memory_file)
    if not isinstance(memory, list):
        return []
    cutoff = datetime.utcnow() - timedelta(days=lookback_days)
    angles = []
    for entry in memory:
        try:
            pub_date = datetime.strptime(entry["published_date"], "%Y-%m-%d")
            if pub_date >= cutoff:
                angle = entry.get("angle_type", "").strip().lower()
                if angle and angle not in angles:
                    angles.append(angle)
        except (KeyError, ValueError):
            continue
    return angles


def _is_duplicate(topic: str, recent_topics: list[str], threshold: float) -> bool:
    if not recent_topics:
        return False
    for existing in recent_topics:
        if _fuzzy_match(topic, existing, threshold):
            return True
    return False


def _normalise_text(value: str) -> str:
    return " ".join(str(value or "").lower().split())


def _fuzzy_match(a: str, b: str, threshold: float) -> bool:
    if not a or not b:
        return False
    if fuzz is None:
        a_tokens = set(a.split())
        b_tokens = set(b.split())
        overlap = len(a_tokens & b_tokens) / max(1, min(len(a_tokens), len(b_tokens)))
        sequence = SequenceMatcher(None, a, b).ratio()
        return max(overlap, sequence) >= threshold
    token_sort = fuzz.token_sort_ratio(a, b) / 100.0
    token_set = fuzz.token_set_ratio(a, b) / 100.0
    return max(token_sort, token_set) >= threshold


def _candidate_fingerprint(candidate: dict) -> str:
    return _normalise_text(" ".join([
        candidate.get("topic", ""),
        candidate.get("hook_seed", ""),
        candidate.get("emotional_trigger", ""),
        candidate.get("psych_concept", ""),
    ]))


def _is_duplicate_candidate(candidate: dict, recent_entries: list[dict], threshold: float) -> bool:
    if not recent_entries:
        return False
    fingerprint_threshold = max(0.62, threshold - 0.15)
    topic = _normalise_text(candidate.get("topic", ""))
    hook = _normalise_text(candidate.get("hook_seed", ""))
    fingerprint = _candidate_fingerprint(candidate)

    for entry in recent_entries:
        if _fuzzy_match(topic, _normalise_text(entry.get("topic", "")), threshold):
            return True
        if _fuzzy_match(hook, _normalise_text(entry.get("hook", "")), threshold):
            return True
        if _fuzzy_match(fingerprint, _normalise_text(entry.get("content_fingerprint", "")), fingerprint_threshold):
            return True
    return False


def _load_evergreen_topics() -> list[dict]:
    path = "config/evergreen_topics.json"
    if not os.path.exists(path):
        return []
    return load_json(path)


def _normalise_categories(categories: list[str]) -> set[str]:
    return {str(c).strip().lower() for c in categories if str(c).strip()}


def _configure_gemini() -> str:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set")
    return api_key


def _clean_signal(value: str) -> str:
    return " ".join(str(value or "").replace("\n", " ").split()).strip()


# ── Step 1: Signal Harvest ────────────────────────────────────────────────────

def _harvest_pytrends(timeframe: str = "now 7-d") -> list[str]:
    if TrendReq is None:
        return []
    try:
        pytrends = TrendReq(hl="en-US", tz=300)
        pytrends.build_payload(
            kw_list=["relationship advice", "breakup advice", "situationship", "attachment style", "self worth"],
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

        queries = [
            "relationship advice",
            "dating advice",
            "breakup advice",
            "situationship advice",
            "self worth relationships",
        ]
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


def _harvest_reddit(subreddits: list[str], timeframe: str = "week") -> list[str]:
    titles = []
    headers = {"User-Agent": "SoftResetWithMeResearch/1.0"}
    for subreddit in subreddits:
        safe_sub = str(subreddit).strip().strip("/")
        if not safe_sub:
            continue
        url = f"https://www.reddit.com/r/{safe_sub}/top.json"
        try:
            resp = requests.get(
                url,
                headers=headers,
                params={"t": timeframe, "limit": 15},
                timeout=12,
            )
            if resp.status_code != 200:
                continue
            posts = resp.json().get("data", {}).get("children", [])
            for post in posts:
                title = _clean_signal(post.get("data", {}).get("title", ""))
                if 15 <= len(title) <= 180:
                    titles.append(title)
        except Exception as e:
            print(f"[research] Reddit r/{safe_sub} failed: {e}")
    unique = list(dict.fromkeys(titles))
    print(f"[research] Reddit: {len(unique)} title signals")
    return unique[:30]


def _harvest_signals(timeframe: str = "now 7-d", config: dict | None = None) -> dict:
    """Collect research signals. Returns dict keyed by source."""
    config = config or {}
    sources = set(config.get("research_signal_sources", ["pytrends", "youtube", "reddit"]))
    pytrends_signals = _harvest_pytrends(timeframe) if "pytrends" in sources else []
    youtube_titles   = _harvest_youtube() if "youtube" in sources else []
    reddit_titles    = (
        _harvest_reddit(
            config.get("reddit_signal_subreddits", ["relationship_advice", "dating_advice", "BreakUps", "ExNoContact", "self"]),
            "month" if "30" in timeframe else "week",
        )
        if "reddit" in sources else []
    )
    return {
        "pytrends": pytrends_signals,
        "youtube":  youtube_titles,
        "reddit": reddit_titles,
    }


# ── Step 2: Candidate Generation ─────────────────────────────────────────────

@retry(max_attempts=2, wait_seconds=10, exceptions=(Exception,))
def _generate_candidates(signals: dict, recent_topics: list[str],
                         recent_categories: list[str], blocked_categories: list[str],
                         config: dict, model: str,
                         recent_angles: list[str] | None = None) -> list[dict]:
    _configure_gemini()

    # Format signals block
    all_signals = signals.get("pytrends", []) + signals.get("youtube", []) + signals.get("reddit", [])
    if all_signals:
        signals_str = "\n".join(f"- {s}" for s in all_signals[:30])
    else:
        signals_str = "- No trending data available — use your knowledge of current US relationship self-improvement topics"

    recent_str  = "\n".join(f"- {t}" for t in recent_topics)  if recent_topics  else "- None"
    cat_str     = "\n".join(f"- {c}" for c in recent_categories) if recent_categories else "- None"
    blocked_str = "\n".join(f"- {c}" for c in blocked_categories) if blocked_categories else "- None"
    angle_str   = "\n".join(f"- {a}" for a in (recent_angles or [])) if recent_angles else "- None"
    performance_insights = summarize_performance_for_prompt(
        config.get("performance_memory_file", "performance_memory_soft_reset.json"),
        min_videos=int(config.get("performance_min_videos_for_prompt", 8)),
        pattern_min_videos=int(config.get("performance_pattern_min_videos", 25)),
        min_views=int(config.get("performance_min_views", 50)),
    )

    from utils.strategy import inject_strategy, get_strategy_context
    prompt_template = inject_strategy(open("prompts/research_candidates_prompt.txt").read(), "research")
    prompt = prompt_template.format(
        signals=signals_str,
        recent_topics=recent_str,
        recent_categories=cat_str,
        blocked_categories=blocked_str,
        recent_angles=angle_str,
        performance_insights=performance_insights,
        target_audience=config.get("target_audience", "US"),
        niche=config.get("niche", "relationship self-improvement"),
    )

    # A/B experiment slot: inject one active hypothesis variation into research prompt.
    # Baseline = no change. Experiment = vary content_format emphasis. Wildcard = vary angle_type.
    experiment_label = config.get("experiment_label", "baseline")
    if experiment_label == "experiment":
        experiment_id = config.get("experiment_id", "")
        from utils.strategy import load_strategy
        strategy = load_strategy()
        experiments = strategy.get("experiment_slots", {}).get("this_week", [])
        active_exp = next((e for e in experiments if e.get("id") == experiment_id), None)
        if active_exp and active_exp.get("prompt_injection"):
            prompt += f"\n\n[EXPERIMENT SLOT — {experiment_id}]\n{active_exp['prompt_injection']}"
            print(f"[research] A/B experiment slot active: {experiment_id}")
    elif experiment_label == "wildcard":
        prompt += (
            "\n\n[WILDCARD SLOT] Generate at least 2 candidates in content_format='hot_take' — "
            "controversial, polarizing, will generate comments and shares. "
            "One candidate must be a topic you would not normally pitch for this channel."
        )
        print("[research] Wildcard slot active: hot_take emphasis")

    candidates = generate_json(prompt, model)
    if not isinstance(candidates, list):
        raise ValueError("Candidate generation returned non-list response")
    for rank, candidate in enumerate(candidates):
        if isinstance(candidate, dict):
            candidate["_candidate_rank"] = rank
    print(f"[research] Generated {len(candidates)} candidates (target: 5–7)")
    return candidates


# ── Step 3: Filter ────────────────────────────────────────────────────────────

def _filter_candidates(candidates: list[dict], recent_topics: list[str], recent_entries: list[dict],
                       recent_categories: list[str], todays_categories: list[str],
                       blocked_categories: list[str], recent_angles: list[str],
                       threshold: float) -> list[dict]:
    blocked = _normalise_categories(blocked_categories)
    todays  = _normalise_categories(todays_categories)
    filtered = []
    for c in candidates:
        topic    = c.get("topic", "")
        category = c.get("category", "").lower()
        angle    = c.get("angle_type", "").strip().lower()

        if _is_duplicate_candidate(c, recent_entries, threshold) or _is_duplicate(topic, recent_topics, threshold):
            print(f"[research] Dropped (duplicate): {topic}")
            continue

        # Hard drop: same category already published TODAY
        if category in todays:
            print(f"[research] Dropped (same-day category — {category}): {topic[:60]}")
            continue

        # Soft warn: category appeared in last N videos
        if any(category == rc.lower() for rc in recent_categories):
            print(f"[research] ⚠ Recent category ({category}) — keeping, scoring will penalise")
            c["category_recent_warning"] = True

        if category in blocked:
            print(f"[research] Dropped (blocked category — {category}): {topic}")
            continue

        # Angle diversity soft warn
        if fuzz and angle and recent_angles:
            angle_match = max(
                (fuzz.partial_ratio(angle, ra) for ra in recent_angles), default=0
            )
            if angle_match > 80:
                print(f"[research] ⚠ Repeated angle ({angle}, {angle_match}% match) — keeping, scoring will decide")
                c["angle_warning"] = True

        filtered.append(c)

    print(f"[research] After filter: {len(filtered)} candidates remain")
    return filtered


# ── Step 3b: Concept-level deduplication ─────────────────────────────────────

def _check_concept_duplicates(candidates: list[dict], recent_topics: list[str],
                               model: str) -> list[dict]:
    """
    Ask Gemini to identify conceptually duplicate candidates vs recent published topics.
    Catches 'same story, different wording' that fuzzy text match misses.
    E.g. 'grieving someone who is still alive' vs 'mourning the future you imagined' = same concept.
    """
    if not recent_topics or not candidates:
        return candidates

    recent_str     = "\n".join(f"- {t}" for t in recent_topics[:40])
    candidates_str = "\n".join(f"{i+1}. {c['topic']}" for i, c in enumerate(candidates))

    prompt = f"""You are a YouTube content deduplication filter for a relationship self-improvement channel.

Recently published topics (last 30 days) — these are COVERED:
{recent_str}

New candidate topics to evaluate:
{candidates_str}

Task: Identify which candidates explore the SAME underlying emotional territory as any recent topic,
even if phrased differently. "Same territory" = same emotional trigger + same psychological concept + same viewer experience.

Examples of same concept:
- "You're not missing them, you're missing who you were with them" = "Grief after a breakup isn't about the person" → DUPLICATE
- "Why you keep checking their Instagram" = "You're not over them if you still need updates" → DUPLICATE
- "The difference between intuition and anxiety" ≠ "Why you attract unavailable people" → DIFFERENT

Return a JSON array of candidate NUMBERS to remove (1-based index). Return [] if none are duplicates.
Return ONLY the JSON array, no explanation, no markdown.
Example: [2, 4]"""

    try:
        result = generate_json(prompt, model)
        if isinstance(result, list) and result:
            to_remove = set()
            for i in result:
                try:
                    to_remove.add(int(i) - 1)
                except (ValueError, TypeError):
                    pass
            kept = [c for i, c in enumerate(candidates) if i not in to_remove]
            removed = len(candidates) - len(kept)
            if removed:
                removed_topics = [candidates[i]["topic"][:50] for i in to_remove if i < len(candidates)]
                for t in removed_topics:
                    print(f"[research] Dropped (concept duplicate): {t}")
            return kept
    except Exception as e:
        print(f"[research] Concept dedup failed ({e}) — skipping")
    return candidates


# ── Step 4 + 5: Parallel Scoring + Fact Grounding ────────────────────────────

@retry(max_attempts=2, wait_seconds=5, exceptions=(Exception,))
def _score_one_candidate(candidate: dict, model: str, prompt_template: str) -> dict:
    _configure_gemini()

    prompt = prompt_template.format(
        topic     = candidate.get("topic", ""),
        category  = candidate.get("category", ""),
        angle_type= candidate.get("angle_type", ""),
        hook_seed = candidate.get("hook_seed", ""),
        core_claim= candidate.get("core_claim", ""),
        editorial_seed= candidate.get("editorial_seed", ""),
        only_soft_reset_line= candidate.get("only_soft_reset_line", ""),
    )

    result = generate_json(prompt, model)
    result = _apply_scoring_penalties(result)

    # Enforce hard gate
    if result.get("reliability_score", 1) == 1:
        result["total_score"] = 0

    # Recalculate total_score from parts as a sanity check (only if reliability > 1).
    # Supports the relationship scoring schema, with legacy scoring keys as fallback.
    if result.get("reliability_score", 1) > 1:
        relationship_parts = [
            "audience_fit_score",
            "emotional_tension_score",
            "scriptability_score",
            "share_save_score",
            "reliability_score",
        ]
        legacy_parts = [
            "cpm_score",
            "trending_score",
            "scriptability_score",
            "us_specificity_score",
            "reliability_score",
        ]
        parts = relationship_parts if any(k in result for k in relationship_parts) else legacy_parts
        computed = sum(result.get(k, 0) for k in parts)
        result["total_score"] = computed

    result["_candidate_rank"] = candidate.get("_candidate_rank", 999)

    # Penalise repeated angle (-1)
    if candidate.get("angle_warning"):
        result["total_score"] = max(0, result.get("total_score", 0) - 1)
        result["angle_penalised"] = True

    # Penalise recently-used category (-1)
    if candidate.get("category_recent_warning"):
        result["total_score"] = max(0, result.get("total_score", 0) - 1)
        result["category_penalised"] = True

    return result


def _apply_scoring_penalties(result: dict) -> dict:
    """Make 20/20 genuinely rare by capping vague or weakly sourced candidates."""
    topic = _normalise_text(result.get("topic", ""))
    trigger = _normalise_text(result.get("emotional_trigger", ""))
    source_name = _normalise_text(result.get("source_name", ""))
    source_url = str(result.get("source_url", "") or "").strip()
    confidence_level = _normalise_text(result.get("confidence_level", ""))
    content_format = _normalise_text(result.get("content_format", ""))
    editorial_seed = _normalise_text(result.get("editorial_seed", ""))
    only_soft_reset_line = _normalise_text(result.get("only_soft_reset_line", ""))

    generic_source_names = (
        "psychological principles",
        "widely accepted psychology principles",
        "relationship psychology principle",
        "psychological concept",
    )
    if not source_url and any(name in source_name for name in generic_source_names):
        result["reliability_score"] = min(int(result.get("reliability_score", 1)), 3)
    if confidence_level == "observational" and not source_url:
        result["reliability_score"] = min(int(result.get("reliability_score", 1)), 3)
        result["share_save_score"] = min(int(result.get("share_save_score", 1)), 3)

    scene_markers = (
        "text", "dm", "message", "reply", "read", "story", "song", "2am", "phone",
        "date", "app", "ghost", "muting", "unfollow", "argument", "waiting",
        "rereading", "typing", "call", "bed", "night",
    )
    trigger_tokens = trigger.split()
    if len(trigger_tokens) < 6 or not any(marker in trigger for marker in scene_markers):
        result["emotional_tension_score"] = min(int(result.get("emotional_tension_score", 1)), 3)

    broad_terms = (
        "relationship advice", "dating advice", "self worth", "emotional growth",
        "communication", "boundaries", "moving on",
    )
    if any(topic == term or topic.startswith(term + " ") for term in broad_terms):
        result["audience_fit_score"] = min(int(result.get("audience_fit_score", 1)), 3)
        result["share_save_score"] = min(int(result.get("share_save_score", 1)), 3)

    if content_format in ("truth_drop", "reframe") and not any(marker in trigger for marker in scene_markers):
        result["share_save_score"] = min(int(result.get("share_save_score", 1)), 3)

    if len(editorial_seed.split()) < 10 or len(only_soft_reset_line.split()) < 6:
        result["audience_fit_score"] = min(int(result.get("audience_fit_score", 1)), 3)
        result["share_save_score"] = min(int(result.get("share_save_score", 1)), 3)
        result["scriptability_score"] = min(int(result.get("scriptability_score", 1)), 3)

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


def _fallback_score_candidate(candidate: dict, rank: int = 1) -> dict:
    emotional_trigger = candidate.get("emotional_trigger", "")
    core_claim = candidate.get("core_claim", "")
    topic = candidate.get("topic", "")
    editorial_seed = candidate.get("editorial_seed") or (
        f"This topic starts from a specific emotional moment: {emotional_trigger}. "
        f"The point is not generic advice; it is the claim that {core_claim.lower() if core_claim else topic.lower()}. "
        "Keep the voice gentle, direct, and emotionally precise."
    )
    only_line = candidate.get("only_soft_reset_line") or core_claim or candidate.get("hook_seed", topic)
    result = {
        **candidate,
        "audience_fit_score": int(candidate.get("audience_fit_score", 4)),
        "emotional_tension_score": int(candidate.get("emotional_tension_score", 4)),
        "scriptability_score": int(candidate.get("scriptability_score", 4)),
        "share_save_score": int(candidate.get("share_save_score", 4)),
        "reliability_score": int(candidate.get("reliability_score", 3)),
        "source_fact": candidate.get("source_fact", core_claim or topic),
        "source_basis": candidate.get("source_basis", candidate.get("psych_concept", "")),
        "source_name": candidate.get("source_name", "relationship psychology principle"),
        "source_url": candidate.get("source_url", ""),
        "fact_year": candidate.get("fact_year", 2026),
        "confidence_level": candidate.get("confidence_level", "observational"),
        "editorial_seed": editorial_seed,
        "only_soft_reset_line": only_line,
        "_candidate_rank": candidate.get("_candidate_rank", rank),
    }
    result["total_score"] = sum(
        result.get(key, 0)
        for key in (
            "audience_fit_score",
            "emotional_tension_score",
            "scriptability_score",
            "share_save_score",
            "reliability_score",
        )
    )
    return _apply_scoring_penalties(result)


def _score_candidates_fallback(candidates: list[dict]) -> list[dict]:
    return [_fallback_score_candidate(candidate, idx + 1) for idx, candidate in enumerate(candidates)]


# ── Step 6: Winner Selection ──────────────────────────────────────────────────

def _pick_winner(scored: list[dict], min_score: int = 10) -> dict | None:
    valid = [c for c in scored if c.get("total_score", 0) >= min_score]
    if not valid:
        rejected = [(c.get("topic", "?")[:50], c.get("total_score", 0)) for c in scored if c.get("total_score", 0) > 0]
        for t, s in rejected:
            print(f"[research] Rejected (score {s} < {min_score}): {t}")
        return None
    return sorted(
        valid,
        key=lambda x: (
            x.get("total_score", 0),
            x.get("emotional_tension_score", x.get("trending_score", 0)),
            x.get("share_save_score", x.get("us_specificity_score", 0)),
            x.get("scriptability_score", 0),
            x.get("audience_fit_score", x.get("cpm_score", 0)),
            -int(x.get("_candidate_rank", 999)),
        ),
        reverse=True,
    )[0]


# ── Main Entry Points ─────────────────────────────────────────────────────────

def run_research(video_id: str, run_dir: str, config: dict) -> dict:
    print(f"[research] Starting topic research for {video_id}")

    memory_file       = config.get("topic_memory_file", "topic_memory.json")
    model             = config["research_model"]
    threshold         = config["duplicate_similarity_threshold"]
    blocked_categories = config.get("blocked_categories", [])
    blocked_set       = _normalise_categories(blocked_categories)
    recent_entries    = _load_recent_entries(memory_file, config["topic_memory_lookback_days"])
    recent_topics     = [entry.get("topic", "") for entry in recent_entries if entry.get("topic", "")]
    recent_categories = _load_recent_categories(
        memory_file,
        last_n=int(config.get("recent_category_block_count", 6)),
    )
    todays_categories = _load_todays_categories(memory_file)
    angle_lookback    = int(config.get("angle_diversity_lookback_days", 3))
    recent_angles     = _load_recent_angles(memory_file, lookback_days=angle_lookback)

    if todays_categories:
        print(f"[research] Today's categories already used: {todays_categories}")
    if recent_angles:
        print(f"[research] Recent angles ({angle_lookback}d): {recent_angles[:5]}")

    # ── Step 1: Harvest signals (7-day) ──
    signals = _harvest_signals(timeframe="now 7-d", config=config)

    # ── Step 2: Generate candidates ──
    try:
        candidates = _generate_candidates(signals, recent_topics, recent_categories, blocked_categories, config, model, recent_angles)
    except Exception as exc:
        print(f"[research] Candidate generation failed ({exc}) — using evergreen fallback")
        candidates = _load_evergreen_topics()

    # ── Step 3: Filter ──
    candidates = _filter_candidates(candidates, recent_topics, recent_entries, recent_categories, todays_categories, blocked_categories, recent_angles, threshold)

    # ── Step 4: Expand to 30-day if too few ──
    if len(candidates) < 3:
        print(f"[research] Only {len(candidates)} candidates after filter — expanding to 30-day signals")
        signals_30d = _harvest_signals(timeframe="now 30-d", config=config)
        try:
            candidates_30d = _generate_candidates(signals_30d, recent_topics, recent_categories, blocked_categories, config, model, recent_angles)
        except Exception as exc:
            print(f"[research] 30-day candidate generation failed ({exc}) — using evergreen fallback")
            candidates_30d = _load_evergreen_topics()
        candidates_30d = _filter_candidates(candidates_30d, recent_topics, recent_entries, recent_categories, todays_categories, blocked_categories, recent_angles, threshold)
        # Merge, dedupe by topic string
        existing_topics = {c["topic"] for c in candidates}
        for c in candidates_30d:
            if c["topic"] not in existing_topics:
                candidates.append(c)
                existing_topics.add(c["topic"])
        print(f"[research] After 30-day expansion: {len(candidates)} candidates")

    # ── Step 4b: Concept-level dedup ──
    if len(candidates) > 1 and recent_topics:
        candidates = _check_concept_duplicates(candidates, recent_topics[:25], model)

    # ── Step 5: Final fallback — top up from evergreen list ──
    if len(candidates) < 3:
        print(f"[research] Still <3 candidates — topping up from evergreen list")
        evergreen = _load_evergreen_topics()
        existing_topics = {c["topic"] for c in candidates}
        for e in evergreen:
            if e["topic"] not in existing_topics:
                category = e.get("category", "").strip().lower()
                if category in blocked_set:
                    continue
                if not _is_duplicate_candidate(e, recent_entries, threshold) and not _is_duplicate(e["topic"], recent_topics, threshold):
                    candidates.append(e)
                    existing_topics.add(e["topic"])
            if len(candidates) >= 6:
                break

    if not candidates:
        raise RuntimeError("[research] No candidates available — pipeline cannot continue")

    print(f"[research] Scoring {len(candidates)} candidates in parallel")

    # ── Step 6: Parallel scoring + fact grounding ──
    scored = _score_candidates_parallel(candidates, model)
    if not scored:
        print("[research] Model scoring unavailable — using deterministic fallback scoring")
        scored = _score_candidates_fallback(candidates)

    min_score = int(config.get("min_score_threshold", 10))

    # ── Step 7: Pick winner — fallback to scored evergreen if all rejected ──
    winner = _pick_winner(scored, min_score)

    if winner is None:
        print("[research] All candidates rejected — scoring evergreen fallback topics")
        evergreen = _load_evergreen_topics()
        evergreen_filtered = [
            e for e in evergreen
            if not _is_duplicate_candidate(e, recent_entries, threshold)
            and not _is_duplicate(e["topic"], recent_topics, threshold)
            and e.get("category", "").strip().lower() not in blocked_set
        ]
        if evergreen_filtered:
            evergreen_scored = _score_candidates_parallel(evergreen_filtered[:6], model)
            if not evergreen_scored:
                evergreen_scored = _score_candidates_fallback(evergreen_filtered[:6])
            winner = _pick_winner(evergreen_scored, min_score)

    if winner is None:
        raise RuntimeError("[research] No valid topic found after all fallbacks — check API connectivity")

    # ── Build final output ──
    result = {
        "video_id":            video_id,
        "topic":               winner.get("topic", ""),
        "category":            winner.get("category", ""),
        "angle_type":          winner.get("angle_type", ""),
        "hook_seed":           winner.get("hook_seed", ""),
        "source_fact":         winner.get("source_fact", winner.get("source_basis", "")),
        "source_basis":        winner.get("source_basis", winner.get("source_fact", "")),
        "source_name":         winner.get("source_name", ""),
        "source_url":          winner.get("source_url", ""),
        "fact_year":           winner.get("fact_year", ""),
        "confidence_level":    winner.get("confidence_level", ""),
        "content_format":      winner.get("content_format", ""),
        "emotional_trigger":   winner.get("emotional_trigger", ""),
        "psych_concept":       winner.get("psych_concept", ""),
        "core_claim":          winner.get("core_claim", ""),
        "editorial_seed":      winner.get("editorial_seed", ""),
        "only_soft_reset_line": winner.get("only_soft_reset_line", ""),
        "scores": {
            "audience_fit":        winner.get("audience_fit_score", winner.get("cpm_score", 0)),
            "emotional_tension":   winner.get("emotional_tension_score", winner.get("trending_score", 0)),
            "scriptability":       winner.get("scriptability_score", 0),
            "share_save":          winner.get("share_save_score", winner.get("us_specificity_score", 0)),
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
        "topic":       "You did not lose them, you lost who you imagined they would be",
        "category":    "healing arcs",
        "angle_type":  "truth drop",
        "content_format": "truth_drop",
        "emotional_trigger": "grieving someone's potential",
        "psych_concept": "idealization and grief",
        "hook_seed":   "You did not lose them. You lost who you imagined.",
        "core_claim": "You are grieving the imagined future more than the person.",
        "editorial_seed": "Missing someone is not always proof they were right for you. Sometimes it proves how much hope you built around them.",
        "only_soft_reset_line": "You are allowed to grieve the version they never became.",
        "source_fact": "Emotional healing often requires grieving the imagined future, not only the person.",
        "source_basis": "Idealization, rumination, and grief after relationship loss.",
        "source_name": "relationship psychology principle",
        "source_url":  "",
        "fact_year":   2026,
        "scores": {
            "audience_fit":   4,
            "emotional_tension": 4,
            "scriptability":  4,
            "share_save": 4,
            "reliability":    4,
        },
        "total_score":          20,
        "reasoning":            "A direct breakup healing truth with strong save/share potential and clean brand fit.",
        "candidates_evaluated": 10,
        "generated_at":         now_iso(),
    }
    output_path = os.path.join(run_dir, "01_research.json")
    save_json(result, output_path)
    print(f"[research][MOCK] Done. Topic: {result['topic']}")
    return result
