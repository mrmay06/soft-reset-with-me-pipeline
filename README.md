# Soft Reset With Me Pipeline

Automated YouTube pipeline for **Soft Reset With Me**, a relationship self-improvement channel focused on emotional growth, healing arcs, self-worth, attachment patterns, and intimate-but-direct advice for an English-speaking 18-35 audience.

The repo runs two tracks:

- **Shorts:** 1 Short per day.
- **Longform:** 1 longform video per week.

Both tracks generate in the morning and upload the video as **private with a scheduled `publishAt`**, so YouTube makes it public at the target time (`publish_mode: scheduled_public`).

## Current Setup

- Channel: `Soft Reset With Me`
- Handle: `@SoftResetWithMe`
- Shorts cadence: 7 Shorts/week, generated 6:00 AM ET, public at 8:00 PM ET the same day
- Longform cadence: 1 video/week, generated Saturday 6:00 AM ET, public Sunday 12:00 PM ET
- Upload mode: uploaded `private` with `publishAt` when `public_release_enabled` is true; stays private otherwise
- Timezone logic: DST-safe dual UTC cron entries plus an `America/New_York` gate (`utils/github_schedule.py`)
- Shorts visuals: Pexels stock video only (clip-only; generated and still images are disabled)
- Longform visuals: Pexels + Coverr stock video (65/35 weighting); static fallback cards are disabled
- Script and argument review: Claude Sonnet 5.5 (`claude-sonnet-5-5`)
- Research, metadata, visual direction, creative judge, video audit: Gemini 3.8 Flash (`gemini-3.8-flash`)
- TTS: Gemini `gemini-3.8-flash-tts`; `Aoede` voice for Shorts, `Puck` for longform
- Captions: word-level timing from local `faster-whisper`
- Weekly learning: Shorts-only analytics + creative judge traits -> Gemini draft -> Sonnet review -> human-approved promotion

See `docs/two-provider-production-stack.md` for the provider split and its safeguards.

## Publishing Schedule

| Track | Workflow | Generation (ET) | Public (ET) |
| --- | --- | --- | --- |
| Shorts | `run_pipeline.yml` | Daily 6:00 AM | Same day 8:00 PM |
| Longform | `run_longform.yml` | Saturday 6:00 AM | Sunday 12:00 PM |
| Weekly strategy | `weekly_strategy.yml` | Monday 4:00 AM | - |

Publish times come from `target_publish_time_et` in each config and are computed by `utils/publish_schedule.py`. If the target time has already passed when the upload happens, the next day (Shorts) or next Sunday (longform) is used.

## Shorts Flow

`main.py` runs the Shorts track. Each stage writes a numbered checkpoint into `workspace/run_<video_id>/`, and a stage is skipped when its checkpoint already exists.

1. **Performance Sync** - Fetches recent YouTube Analytics into `performance_memory_soft_reset.json`. Failures soft-fail.
2. **Research** - Harvests pytrends, YouTube, and Reddit signals (YouTube Shorts are ranked by their multiple over their own channel's median views, not raw views; see the `youtube_outlier_*` config keys), asks Gemini for topic candidates, scores them, and falls back to `config/evergreen_topics.json` when needed. Active experiment slots and `strategy/weekly_direction.json` are injected into the prompt.
3. **Script** - Claude Sonnet writes a 60-90 word script (hard limits 45-110). The keyword hook check is advisory; Sonnet's argument review decides whether the hook is concrete (`hook_is_concrete`). The script agent also checks calibrated psychology, a resolved opening promise, contextual CTAs, and safety limits, repairs once, then runs a Sonnet argument-coherence review.
4. **Script gate** - Blocks media generation if the script needs human review or the argument review is missing, failed, or stale (checked by a hash of the spoken text).
5. **TTS** - Gemini TTS with the `Aoede` voice at speed 1.0, instructed to keep moving without long pauses between sentences (`03_voice.mp3`).
6. **Visual Director** - Gemini builds a clip-only scene manifest synchronized to the narration (`03b_scene_manifest.json`).
7. **Clip Selection** - Picks unique Pexels stock-video clips, using `clip_memory_soft_reset.json` to hard-block reuse for 30 days and penalize it for 90.
8. **Captions** - Centered one-word-at-a-time kinetic ASS captions timed with `faster-whisper`. Captions and the render are rebuilt automatically if they no longer match the voice.
9. **Thumbnail** - Builds `05_thumbnail.png` (kept as an artifact; YouTube does not take custom thumbnails for Shorts).
10. **Video Assembly** - Renders `06_final_video.mp4` with captions, background music, the film overlay, and loudness normalization. The CTA end card is currently disabled (`cta_card_enabled: false`).
11. **Metadata** - Gemini generates title, description, and tags.
12. **Creative Judge** - Pre-upload gate. Blocks hard quality/safety failures and writes learning traits to `10_judge_report.json`.
13. **Video Audit** - Gemini watches the finished Short (`09_video_audit.json`). When public release is enabled, high-confidence narration/visual contradictions trigger up to 2 clip-repair rounds (re-render, re-judge, re-audit) before the upload is blocked.
14. **Upload** - Uploads as private with `publishAt`.
15. **Logger** - Appends topic, metadata, judge traits, video-audit signals, experiment slot, upload info, and a compact `spoken_timeline` (start second of each spoken line) to `topic_memory_soft_reset.json`.

`--skip-upload` generates everything without publishing. If `log_skip_upload_to_memory` is true, skip-upload runs still write memory.

## Longform Flow

`main_long.py` runs the longform track:

1. **Long Performance Sync** - Uses longform memory and analytics thresholds.
2. **Long Research** - Generates the longform topic and angle.
3. **Long Script** - Claude Sonnet writes a 700-950 word (hard limits 600-1100), 4.5-6.5 minute essay. A capacity check blocks padding; the review gate requires calibrated psychology, a genuine counterpoint, viewer agency, and a resolved opening promise.
4. **Long Metadata** - Creates packaging for the upload.
5. **Long Audio** - Generates the full Gemini TTS voiceover (`Puck`).
6. **Long Captions** - Generates phrase-level captions.
7. **Long Video** - Renders `06_longform_video.mp4` (1920x1080) from short visual beats, unique Pexels/Coverr footage, music, and the film overlay. Clip reuse is tracked in `clip_memory_soft_reset_long.json`.
8. **Long Thumbnail** - Creates `07_longform_thumbnail.png` plus A/B/C variants, then syncs packaging with the thumbnail copy.
9. **Chapters** - `utils/longform_chapters.py` aligns each script chapter to the caption word timings and inserts a YouTube chapter block (0:00 first, 3+ chapters, 10s minimum) into the description, using 3-5 word titles from packaging. Invalid lists are omitted. Toggle with `longform_chapters_enabled`. A confirmation email is sent before upload.
10. **Creative Judge** and **Video Audit** - Pre-upload gates using the shared modules.
11. **Long Upload** - Uploads as private with `publishAt` and sets the custom thumbnail.
12. **Long Logger** - Writes upload status, YouTube URL, thumbnail variant, judge traits, experiment metadata, and topic data to `topic_memory_soft_reset_long.json`.

Longform uses separate memory files:

- `topic_memory_soft_reset_long.json`
- `performance_memory_soft_reset_long.json`
- `clip_memory_soft_reset_long.json`

The 2-minute test mode (`--test-2min`) shortens the targets to about 260-390 words and must use:

- `topic_memory_soft_reset_long_test.json`
- `performance_memory_soft_reset_long_test.json`

## Editorial Layer

The Shorts track is designed to avoid generic relationship advice. Topic research must produce:

- `core_claim`
- `editorial_seed`
- `only_soft_reset_line`
- `source_basis`
- `confidence_level`
- `standout_line` in the finished script, mirrored to legacy `only_soft_reset_line` for validator compatibility

The script agent checks argument coherence so the hook promise, emotional mechanism, counterpoint, viewer agency, and final insight support the same core claim. Psychological mechanisms are hypotheses rather than diagnoses. Weak, padded, or drifting scripts are repaired once and blocked before media generation if hard failures remain.

The prompt layer favors emotionally precise, plain-language insight over therapy-speak, hype-coach phrasing, generic inspiration, or artificial retention lines. `psych_concept` is treated as a plausible internal lens and translated into lived moments. Shorts end by resolving the opening promise; the JSON still uses the legacy `loopback` key for downstream compatibility. Long-form scripts create meaningful narrative turns by adding events, consequences, contradictions, interpretations, or decisions rather than announcing delayed value.

Every Shorts script includes `script_version`, `prompt_version`, `validation`, and `validation_notes` so future analytics can trace performance shifts back to prompt rules. `cta` remains a legacy alias for `like_cta`; `utils/script_contract.py` normalizes it before downstream modules read the script.

## Models And Providers

Shorts defaults in `config/pipeline_config.json`:

| Purpose | Setting | Current value |
| --- | --- | --- |
| Research | `research_model` | `gemini-3.8-flash` |
| Script | `script_model` | `claude-sonnet-5-5` |
| Metadata | `metadata_model` | `gemini-3.8-flash` |
| Visual director | `visual_model` | `gemini-3.8-flash` |
| Creative judge | `creative_judge_model` | `gemini-3.8-flash` |
| Video audit | `video_audit_model` | `gemini-3.8-flash` |
| TTS | `tts_model` | `gemini-3.8-flash-tts` |
| TTS voice | `tts_voice` | `Aoede` |

Longform defaults in `config/longform_config.json`:

| Purpose | Setting | Current value |
| --- | --- | --- |
| Research | `research_model` | `gemini-3.8-flash` |
| Script | `script_model` | `claude-sonnet-5-5` |
| Metadata | `metadata_model` | `gemini-3.8-flash` |
| Creative judge | `creative_judge_model` | `gemini-3.8-flash` |
| Video audit | `video_audit_model` | `gemini-3.8-flash` |
| TTS | `tts_model` | `gemini-3.8-flash-tts` |
| TTS voice | `tts_voice` | `Puck` |

External services: Anthropic, Gemini, Pexels (both tracks), Coverr (longform only), YouTube Data and Analytics APIs, pytrends, Reddit, and SMTP email for alerts.

## Running Locally

### Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
brew install ffmpeg
```

On Linux:

```bash
sudo apt-get install ffmpeg
```

### Environment

Copy `.env.example` to `.env`, or add the same values as GitHub Actions secrets:

```bash
GEMINI_API_KEY=
ANTHROPIC_API_KEY=
PEXELS_API_KEY=
COVERR_API_KEY=
YOUTUBE_CLIENT_ID=
YOUTUBE_CLIENT_SECRET=
YOUTUBE_REFRESH_TOKEN=
ALERT_EMAIL_FROM=
ALERT_EMAIL_TO=
ALERT_EMAIL_PASSWORD=
```

`POLLINATIONS_API_KEY` is still listed in `.env.example` but no code uses it.

Generate a YouTube refresh token while signed into the Google account that owns **Soft Reset With Me**:

```bash
python3 tools/get_youtube_token.py
```

Verify the token points to the right channel:

```bash
python tools/check_youtube_channel.py
```

Do not run live uploads until that check prints the Soft Reset With Me channel. If the token expires, `python tools/start_youtube_reauth.py` repairs it.

### Checks

```bash
# Parse Python, validate JSON and memory files, confirm strategy is not auto-promoted
python tools/healthcheck.py

# Validate the GitHub Actions schedule and memory files (both run in CI)
python tools/validate_schedule.py
python tools/validate_memory_files.py

# Small paid smoke check of model access (no uploads)
python tools/check_model_access.py

# Offline regression tests
python -m unittest discover -s tests
```

### Shorts Commands

```bash
# Generate assets and metadata without publishing.
python main.py --fresh --skip-upload

# Live run. Auto-resumes an incomplete Shorts run if one exists.
python main.py

# Force a brand-new live Shorts run.
python main.py --fresh

# Mock run (no API calls).
python main.py --mock --fresh

# Resume a specific Shorts run.
python main.py --resume <video_id>

# Real generation with upload and email disabled and isolated memory copies.
python tools/run_unpublished_test.py
```

### Longform Commands

```bash
# Mock longform run.
python main_long.py --mock

# Live longform run. Auto-resumes incomplete longform runs.
python main_long.py

# Force a brand-new longform run.
python main_long.py --fresh

# 2-minute test mode.
python main_long.py --test-2min

# Resume a specific longform run.
python main_long.py --resume <long_video_id>
```

## GitHub Actions

`.github/workflows/run_pipeline.yml` (Shorts) and `.github/workflows/run_longform.yml` (longform) share the same shape:

- A Python gate step checks `automation_enabled` and the New York local hour, so only the cron entry matching the current DST offset runs.
- Scheduled runs call `python main.py --fresh` / `python main_long.py --fresh`; they do not resume earlier runs.
- Manual dispatch has a `mock` input (default `true`) that runs an offline mock render instead.
- Job timeouts: 100 minutes for Shorts, 180 for longform. Each track has a concurrency group so runs never overlap.
- `workspace/run_*/` (or `run_long_*/`) is uploaded as a 7-day artifact.
- On the default branch (and not a mock dispatch), the memory files are uploaded as a 30-day backup artifact, then `tools/persist_pipeline_memory.py` commits only changed memory through a temporary worktree so concurrent Shorts, longform, and strategy commits do not overwrite each other. Both steps run with `if: always()`.

Secrets used by the Shorts workflow:

```bash
GEMINI_API_KEY
ANTHROPIC_API_KEY
PEXELS_API_KEY
YOUTUBE_CLIENT_ID
YOUTUBE_CLIENT_SECRET
YOUTUBE_REFRESH_TOKEN
ALERT_EMAIL_FROM
ALERT_EMAIL_TO
ALERT_EMAIL_PASSWORD
```

The longform workflow uses the same secrets plus `COVERR_API_KEY`.

## Weekly Shorts Self-Improvement

`.github/workflows/weekly_strategy.yml` runs every Monday at 4:00 AM New York time (45-minute timeout).

The weekly loop (`tools/weekly_strategy.py`):

1. Fetches mature Shorts analytics (`tools/weekly_analytics_fetch.py`), including the audience-retention curve for videos above `performance_min_views`.
2. Preprocesses comparisons by creative traits and performance buckets (`tools/weekly_preprocess.py`). `utils/retention_analysis.py` turns each curve into hook leak (first 3 seconds), the steepest cliffs mapped to the spoken line from `spoken_timeline`, mid-video slide, and end retention; curves under 1,000 views are marked low confidence.
3. Optionally watches top/bottom videos with Gemini; scheduled runs skip video watching.
4. Uses Gemini to draft `strategy/strategy_memory_proposed.json`.
5. Uses Sonnet to review/refine into `strategy/strategy_memory_reviewed.json`.
6. Leaves the active strategy unchanged until `tools/promote_strategy.py --promote --confirm`.
7. Archives history under `strategy/analysis_history/` and commits the strategy files.

Longform performance is logged separately and is not used in the weekly Shorts strategy loop.

Learning is staged to avoid overfitting early uploads:

- 0-11 valid videos: collect data only; keep testing different pillars and formats.
- 12-24 valid videos: use individual winning and weak examples directionally.
- 25+ valid videos: use pattern-level feedback by category, format, angle, hook type, title type, thumbnail type, visual mix, and judge traits.

Videos younger than 2 days are skipped for Shorts analytics. Cached analytics are reused for 7 days where configured.

Experiment slots are selected in code, not by the model. `utils/strategy.py` targets a history-balanced **60% baseline / 20% experiment / 20% wildcard** allocation from recent judge reports, separately for Shorts and Longform. Active experiment or wildcard guidance is injected into the Shorts research prompt through `utils/experiment.py`.

## YouTube Analytics Data Flow

Soft Reset has two YouTube Analytics paths with different responsibilities:

1. **Every Shorts or Longform pipeline run** starts with Module 0, `modules/performance_agent.py`.
   - Trigger: `main.py` for Shorts and `main_long.py` for Longform.
   - Source lists: `topic_memory_soft_reset.json`, `topic_memory_soft_reset_long.json`, or the test memory file configured for a test run.
   - API: YouTube Analytics aggregate query for eligible uploaded videos.
   - Freshness rules: Shorts under 2 days old (longform under 3) are skipped; recently fetched videos are reused for 7 days.
   - Outputs: the configured performance memory file plus the run checkpoint `workspace/run_*/00_performance_sync.json` or `workspace/run_long_*/00_performance_sync.json`.
   - Product role: gives the daily production agent recent performance context. Analytics failures soft-fail so production can continue.

2. **The weekly Shorts strategy workflow** runs from `.github/workflows/weekly_strategy.yml`.
   - Trigger: Monday 4:00 AM New York time, or manual Actions dispatch.
   - Source list: Shorts topic memory only.
   - API: `tools/weekly_analytics_fetch.py` fetches a fresh mature-Short snapshot into `strategy/analytics_cache/`.
   - Processing: `tools/weekly_preprocess.py` converts the snapshot into creative-trait and performance comparisons.
   - Strategy output: Gemini drafts `strategy/strategy_memory_proposed.json`; Sonnet reviews it into `strategy/strategy_memory_reviewed.json`.
   - Product role: creates a reviewed Shorts strategy proposal. It never changes the active strategy until `tools/promote_strategy.py --promote --confirm`.

So the performance memory files are daily run feedback, while `strategy/analytics_cache/` is the weekly Shorts analysis snapshot. Longform currently gets performance memory but does not feed the weekly Shorts strategy loop.

Video-specific learning comes from `modules/video_audit_agent.py`. It runs after the Creative Judge passes and before upload, while the rendered video still exists. Gemini watches the finished video and writes `09_video_audit.json`; the logger copies the summary, drop-off causes, strengths, repeat/reduce recommendations, and tag suggestions into topic memory. Weekly strategy then receives both YT Analytics and these video-audit observations.

## Guardrails And Learning Memory

The current Shorts flow records enough context for weekly strategy to make meaningful comparisons:

- Script validation metadata: `script_version`, `prompt_version`, `script_validation`, and `script_validation_notes`.
- Creative/topic traits: `category`, `angle_type`, `content_format`, `emotional_trigger`, `psych_concept`, hook quality, word count, thumbnail text, judge scores, and experiment metadata.
- Weekly strategy metadata: `strategy_version`, active experiment IDs, active cooldowns, channel health, and recent strategy history.

Longform stays separate. It logs to `topic_memory_soft_reset_long.json` and `performance_memory_soft_reset_long.json`, while the current weekly strategy loop analyzes Shorts only.

## Important Files

| Path | Purpose |
| --- | --- |
| `main.py` | Shorts pipeline entry point |
| `main_long.py` | Longform pipeline entry point |
| `config/pipeline_config.json` | Shorts schedule, model, upload, render, and learning settings |
| `config/longform_config.json` | Longform settings |
| `config/evergreen_topics.json` | Research fallback topics |
| `prompts/research_candidates_prompt.txt` | Shorts topic research |
| `prompts/research_score_prompt.txt` | Shorts candidate scoring |
| `prompts/script_prompt.txt` | Shorts script rules |
| `prompts/metadata_prompt.txt` | Shorts metadata rules |
| `prompts/longform_research_prompt.txt` | Longform research rules |
| `prompts/longform_script_prompt.txt` | Longform script rules |
| `prompts/longform_packaging_prompt.txt` | Longform title/thumbnail/metadata packaging |
| `prompts/weekly_analysis_prompt.txt` | Weekly Shorts strategy analysis prompt |
| `modules/script_agent.py` | Shorts script generation, repair, guardrail validation, argument review |
| `modules/visual_director.py` | Shorts scene manifest |
| `modules/image_gen.py` | Shorts Pexels clip selection and repair |
| `modules/video_assembler.py` | Shorts final render |
| `modules/longform_video_assembler.py` | Longform render from Pexels/Coverr footage |
| `modules/creative_judge.py` | Shared creative judge and trait extraction |
| `modules/video_audit_agent.py` | Shared Gemini video audit and visual release gate |
| `modules/uploader.py` / `modules/longform_uploader.py` | Scheduled-public YouTube uploads |
| `modules/logger.py` | Shorts memory logger |
| `modules/longform_logger.py` | Longform memory logger |
| `utils/publish_schedule.py` | Computes YouTube `publishAt` |
| `utils/github_schedule.py` | DST gate used by the workflows |
| `utils/experiment.py` | Shorts research prompt experiment-slot injection |
| `utils/weekly_direction.py` | Optional editorial direction from `strategy/weekly_direction.json` |
| `utils/cooldowns.py` | Active strategy cooldown filtering |
| `utils/strategy.py` | Strategy context and experiment allocation |
| `tools/weekly_strategy.py` | Weekly Shorts self-improvement orchestrator |
| `tools/persist_pipeline_memory.py` | Commits changed memory from CI |
| `topic_memory_soft_reset.json` | Shorts topic and creative memory |
| `performance_memory_soft_reset.json` | Shorts analytics memory |
| `clip_memory_soft_reset.json` | Shorts clip reuse memory |
| `topic_memory_soft_reset_long.json` | Longform topic memory |
| `performance_memory_soft_reset_long.json` | Longform analytics memory |
| `strategy/strategy_memory.json` | Active Shorts strategy used by future runs |

## Manual Tools

```bash
# Fetch weekly Shorts analytics
python tools/weekly_analytics_fetch.py

# Preprocess weekly comparisons
python tools/weekly_preprocess.py

# Run weekly strategy cycle
python tools/weekly_strategy.py --skip-video-watch

# Run weekly strategy with Gemini video watching
python tools/weekly_strategy.py

# Compare and promote the reviewed strategy
python tools/promote_strategy.py --review
python tools/promote_strategy.py --promote --confirm

# Rotate longform thumbnail variants (48h -> B, 96h -> C)
python tools/ab_thumbnail_swap.py --dry-run

# Audit tags for topic mismatch
python tools/tag_audit.py

# Gemini channel performance report
python tools/channel_analyst.py --days 7

# Remove old workspace runs (dry-run unless --delete)
python tools/cleanup_workspace.py

# Verify YouTube OAuth channel
python tools/check_youtube_channel.py
```

## Notes

- Both tracks upload private with a scheduled `publishAt`; setting `public_release_enabled: false` keeps uploads private.
- `privacy_status` in the configs is only copied into metadata and mock upload records; the real uploaders always send `private` (plus `publishAt` when public release is enabled).
- Longform uploads log YouTube IDs/URLs after upload.
- Shorts and longform memories are separate because their analytics mature differently.
- Weekly strategy currently updates the Shorts strategy only.
- Use `--fresh` locally only when you intentionally want to ignore resumable workspace runs.
