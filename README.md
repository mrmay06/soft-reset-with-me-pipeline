# Soft Reset With Me Pipeline

Automated YouTube pipeline for **Soft Reset With Me**, a relationship self-improvement channel focused on emotional growth, healing arcs, self-worth, attachment patterns, and intimate-but-direct advice for an English-speaking 18-35 audience.

The repo runs two tracks:

- **Shorts:** 2 public Shorts per day.
- **Longform:** 1 public longform video per week.

All active publishing is **public-now**. The pipeline does not schedule future YouTube publish times.

## Current Setup

- Channel: `Soft Reset With Me`
- Handle: `@SoftResetWithMe`
- Shorts cadence: 14 Shorts/week
- Longform cadence: 1 video/week
- Upload mode: `publish_mode: public_now`, `privacy_status: public`
- Action timing: GitHub Actions starts 25 minutes before the intended ET publish window
- Timezone logic: DST-safe dual UTC cron entries plus an `America/New_York` gate
- Shorts visual priority: Pexels video -> generated AI image -> Pexels image fallback
- Shorts Coverr setting: disabled by default
- Longform stock footage: Pexels + Coverr
- Shorts TTS: Gemini `gemini-2.5-flash-preview-tts`, `Aoede` voice
- Longform TTS: Gemini `gemini-2.5-flash-preview-tts`, `Puck` voice
- Script model: Claude Sonnet
- Creative judge model: `gemini-2.5-flash-lite`
- Weekly learning: Shorts-only analytics + creative judge traits -> Gemini draft -> Sonnet review -> human-approved promotion

## Publishing Schedule

Target public upload windows in New York time:

| Day | Shorts upload windows ET | Longform upload window ET |
| --- | --- | --- |
| Monday | 12:00 PM, 7:00 PM | - |
| Tuesday | 12:00 PM, 8:00 PM | - |
| Wednesday | 11:00 AM, 7:00 PM | - |
| Thursday | 12:00 PM, 8:00 PM | - |
| Friday | 3:00 PM, 7:00 PM | - |
| Saturday | 10:00 AM, 6:00 PM | - |
| Sunday | 11:00 AM, 7:00 PM | 9:00 PM |

The workflow starts each run at `:35` in the matching local hour, roughly 25 minutes before the target public upload window. Longform starts Sunday at 8:35 PM ET for the intended 9:00 PM ET public upload window.

## Shorts Flow

`main.py` runs the Shorts track:

1. **Performance Sync** - Fetches recent YouTube Analytics into `performance_memory_soft_reset.json`.
2. **Research** - Uses pytrends, YouTube, and Reddit signals, then asks Gemini for topic candidates.
3. **Script** - Uses Claude Sonnet to write a 45-75 word script with the Soft Reset editorial layer. The script agent enforces banned therapy-speak checks, landing-line quality, argument coherence, prompt/script version fields, and validation notes.
4. **TTS** - Uses Gemini TTS with the `Aoede` voice.
5. **Visual Director** - Builds a scene manifest with `visual_type` and `image_style`.
6. **Image/Video Assets** - Uses Pexels video, generated images, and Pexels image fallback.
7. **Captions** - Generates centered kinetic ASS captions.
8. **Thumbnail** - Builds `05_thumbnail.png`.
9. **Video Assembly** - Renders `06_final_video.mp4` with captions, music, film overlay, and CTA card.
10. **Metadata** - Generates title, description, and tags.
11. **Upload** - Uploads directly to YouTube as public.
12. **Creative Judge** - Scores the uploaded run and extracts learning traits into `10_judge_report.json`.
13. **Logger** - Appends topic, metadata, judge traits, experiment slot, and upload info to `topic_memory_soft_reset.json`.

Shorts can run with `--skip-upload` for local generation without publishing. If `log_skip_upload_to_memory` is true, skip-upload runs can still write memory for testing.

## Longform Flow

`main_long.py` runs the longform track:

1. **Long Performance Sync** - Uses longform memory and analytics thresholds.
2. **Long Research** - Generates the longform topic and angle.
3. **Long Script** - Uses Claude Sonnet to write a 750-1050 word essay script.
4. **Long Metadata** - Creates packaging for the longform upload.
5. **Long Audio** - Generates the full Gemini TTS voiceover.
6. **Long Captions** - Generates phrase-level captions.
7. **Long Video** - Renders `06_longform_video.mp4` from short visual beats, Pexels/Coverr footage, fallback cards, music, and film overlay.
8. **Long Thumbnail** - Creates `07_longform_thumbnail.png` and A/B/C thumbnail variants.
9. **Long Upload** - Uploads directly to YouTube as public.
10. **Creative Judge** - Scores the longform run with the shared judge module.
11. **Long Logger** - Writes upload status, YouTube URL, thumbnail variant, judge traits, experiment metadata, and topic data to `topic_memory_soft_reset_long.json`.

Longform uses separate memory files:

- `topic_memory_soft_reset_long.json`
- `performance_memory_soft_reset_long.json`

The temporary 2-minute test mode uses:

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

The script agent checks argument coherence so the hook promise, emotional mechanism, and final insight all support the same core claim. Weak or drifting scripts are retried before rendering.

The prompt layer favors emotionally precise, plain-language insight over therapy-speak, hype-coach phrasing, or generic inspirational advice. `psych_concept` is treated as an internal lens only; it should be translated into lived moments instead of spoken as clinical jargon. Shorts end on a landing sentence rather than a forced callback; the JSON still uses the legacy `loopback` key for downstream compatibility.

Every Shorts script includes `script_version`, `prompt_version`, `validation`, and `validation_notes` so future analytics can trace performance shifts back to prompt rules. `cta` remains a legacy alias for `like_cta`; `utils/script_contract.py` normalizes it before downstream modules read the script.

## Models And Providers

Shorts defaults in `config/pipeline_config.json`:

| Purpose | Setting | Current value |
| --- | --- | --- |
| Research | `research_model` | `gemini-2.5-flash` |
| Script | `script_model` | `claude-sonnet-4-6` |
| Metadata | `metadata_model` | `gemini-2.5-flash` |
| Creative judge | `creative_judge_model` | `gemini-2.5-flash-lite` |
| Visual director | `visual_model` | `gemini-2.5-flash` |
| TTS | `tts_model` | `gemini-2.5-flash-preview-tts` |
| TTS voice | `tts_voice` | `Aoede` |
| Image model | `image_model` | `zimage` |

Longform defaults in `config/longform_config.json`:

| Purpose | Setting | Current value |
| --- | --- | --- |
| Research | `research_model` | `gemini-2.5-flash` |
| Script | `script_model` | `claude-sonnet-4-6` |
| Metadata | `metadata_model` | `gemini-2.5-flash` |
| Creative judge | `creative_judge_model` | `gemini-2.5-flash-lite` |
| TTS | `tts_model` | `gemini-2.5-flash-preview-tts` |
| TTS voice | `tts_voice` | `Puck` |

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
POLLINATIONS_API_KEY=
PEXELS_API_KEY=
COVERR_API_KEY=
YOUTUBE_CLIENT_ID=
YOUTUBE_CLIENT_SECRET=
YOUTUBE_REFRESH_TOKEN=
ALERT_EMAIL_FROM=
ALERT_EMAIL_TO=
ALERT_EMAIL_PASSWORD=
```

Generate a YouTube refresh token while signed into the Google account that owns **Soft Reset With Me**:

```bash
python tools/get_youtube_token.py
```

Verify the token points to the right channel:

```bash
python tools/check_youtube_channel.py
```

Do not run live uploads until that check prints the Soft Reset With Me channel.

### Healthcheck

```bash
python tools/healthcheck.py
```

The healthcheck parses Python files, validates JSON files, checks configured Shorts/longform memory files, and confirms weekly strategy does not directly promote the active strategy.

### Shorts Commands

```bash
# Generate assets and metadata without publishing.
python main.py --fresh --skip-upload

# Live run. Auto-resumes an incomplete Shorts run if one exists.
python main.py

# Force a brand-new live Shorts run.
python main.py --fresh

# Mock run.
python main.py --mock --fresh

# Resume a specific Shorts run.
python main.py --resume <video_id>
```

### Longform Commands

```bash
# Mock longform run.
python main_long.py --mock

# Live longform run. Auto-resumes incomplete longform runs.
python main_long.py

# Force a brand-new longform run.
python main_long.py --fresh

# Temporary 2-minute test mode.
python main_long.py --test-2min

# Resume a specific longform run.
python main_long.py --resume <long_video_id>
```

## GitHub Actions

`.github/workflows/run_pipeline.yml` runs both publishing tracks.

Important behavior:

- Schedule gate chooses `shorts` or `longform` based on New York local time.
- Manual dispatch can choose `shorts` or `longform`.
- The retry wrapper runs `python main.py` or `python main_long.py`, not `--fresh`, so retries can resume checkpoints.
- Job timeout is 175 minutes to allow one retry of the longform path.
- Rendered videos, metadata, scripts, render metadata, thumbnails, and judge reports are uploaded as 7-day artifacts.
- Memory commits run with `if: always()` so late-stage failures do not automatically lose updated memory.
- The workflow pulls with `--rebase --autostash` before committing memory to reduce push races.

Required GitHub Actions secrets:

```bash
GEMINI_API_KEY
ANTHROPIC_API_KEY
POLLINATIONS_API_KEY
PEXELS_API_KEY
COVERR_API_KEY
YOUTUBE_CLIENT_ID
YOUTUBE_CLIENT_SECRET
YOUTUBE_REFRESH_TOKEN
ALERT_EMAIL_FROM
ALERT_EMAIL_TO
ALERT_EMAIL_PASSWORD
```

## Weekly Shorts Self-Improvement

`.github/workflows/weekly_strategy.yml` runs every Monday at 6:00 AM New York time.

The weekly loop:

1. Fetches mature Shorts analytics.
2. Preprocesses comparisons by creative traits and performance buckets.
3. Optionally watches top/bottom videos with Gemini; scheduled runs skip video watching by default.
4. Uses Gemini to draft `strategy/strategy_memory_proposed.json`.
5. Uses Sonnet to review/refine into `strategy/strategy_memory_reviewed.json`.
6. Leaves the active strategy unchanged until `tools/promote_strategy.py --promote --confirm`.
7. Archives history under `strategy/analysis_history/`.

Longform performance is logged separately and is not used in the weekly Shorts strategy loop.

Learning is staged to avoid overfitting early uploads:

- 0-11 valid videos: collect data only; keep testing different pillars and formats.
- 12-24 valid videos: use individual winning and weak examples directionally.
- 25+ valid videos: use pattern-level feedback by category, format, angle, hook type, title type, thumbnail type, visual mix, and judge traits.

Videos younger than 2 days are skipped for Shorts analytics. Cached analytics are reused for 7 days where configured.

Experiment slots are selected in code, not by the model. `utils/strategy.py` targets a history-balanced **60% baseline / 20% experiment / 20% wildcard** allocation from recent judge reports, separately for Shorts and Longform. Active experiment or wildcard guidance is injected into the Shorts research prompt through `utils/experiment.py`.

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
| `prompts/research_candidates_prompt.txt` | Shorts topic research |
| `prompts/research_score_prompt.txt` | Shorts candidate scoring |
| `prompts/script_prompt.txt` | Shorts script rules |
| `prompts/metadata_prompt.txt` | Shorts metadata rules |
| `prompts/longform_research_prompt.txt` | Longform research rules |
| `prompts/longform_script_prompt.txt` | Longform script rules |
| `prompts/longform_packaging_prompt.txt` | Longform title/thumbnail/metadata packaging |
| `prompts/weekly_analysis_prompt.txt` | Weekly Shorts strategy analysis prompt |
| `modules/image_gen.py` | Shorts Pexels/generated visual asset selection |
| `modules/video_assembler.py` | Shorts final render |
| `modules/longform_video_assembler.py` | Longform render from stock footage and fallback cards |
| `modules/creative_judge.py` | Shared creative judge and trait extraction |
| `modules/script_agent.py` | Shorts script generation, retries, and guardrail validation |
| `modules/logger.py` | Shorts memory logger |
| `modules/longform_logger.py` | Longform memory logger |
| `utils/experiment.py` | Shorts research prompt experiment-slot injection |
| `utils/cooldowns.py` | Active strategy cooldown filtering |
| `utils/strategy.py` | Strategy context and experiment allocation |
| `tools/weekly_strategy.py` | Weekly Shorts self-improvement orchestrator |
| `tools/validate_schedule.py` | Schedule validator |
| `topic_memory_soft_reset.json` | Shorts topic and creative memory |
| `performance_memory_soft_reset.json` | Shorts analytics memory |
| `topic_memory_soft_reset_long.json` | Longform topic memory |
| `performance_memory_soft_reset_long.json` | Longform analytics memory |
| `strategy/strategy_memory.json` | Active Shorts strategy used by future runs |

## Manual Tools

```bash
# Validate the GitHub Actions schedule
python tools/validate_schedule.py

# Fetch weekly Shorts analytics
python tools/weekly_analytics_fetch.py

# Preprocess weekly comparisons
python tools/weekly_preprocess.py

# Run weekly strategy cycle
python tools/weekly_strategy.py --skip-video-watch

# Run weekly strategy with Gemini video watching
python tools/weekly_strategy.py

# Swap eligible thumbnails where configured
python tools/ab_thumbnail_swap.py

# Audit tags for topic mismatch
python tools/tag_audit.py

# Verify YouTube OAuth channel
python tools/check_youtube_channel.py
```

## Notes

- Public immediate upload is intentional for both active tracks.
- Longform uploads directly and logs YouTube IDs/URLs after upload.
- Shorts and longform memories are separate because their analytics mature differently.
- Weekly strategy currently updates the Shorts strategy only.
- Scheduled Actions avoid `--fresh` so retries can use checkpoints.
- Use `--fresh` locally only when you intentionally want to ignore resumable workspace runs.
