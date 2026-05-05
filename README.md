# Soft Reset With Me Pipeline

Automated YouTube Shorts pipeline for **Soft Reset With Me**.

The channel direction is relationship psychology, healing arcs, self-worth, and emotional growth for a US 18-35 audience. The pipeline researches topics, writes a short script, generates voiceover, selects Pexels video footage, generates fallback brand stills, adds captions, renders the final Short, creates metadata, and uploads/schedules through YouTube.

## Current Setup

- Channel: `Soft Reset With Me`
- Handle: `@SoftResetWithMe`
- Video source priority for Shorts: Pexels video -> generated AI image -> Pexels stock image fallback
- Coverr is disabled for Shorts and reserved for later long-form experiments
- Publishing schedule: 2 Shorts per day, New York time
- Upload mode: private/manual scheduling via pipeline config
- Captions: centered kinetic captions with Soft Cream fill and Deep Midnight border
- End screen: `assets/EndScreen.png`

## Run Locally

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python main.py --fresh --skip-upload
```

To run the full upload flow:

```bash
python main.py --fresh
```

To generate a separate long-form video package without uploading:

```bash
python main_long.py --mock
python main_long.py
```

Long-form uses separate memory and analytics files:

- `topic_memory_soft_reset_long.json`
- `performance_memory_soft_reset_long.json`

The long-form track renders a separate horizontal `06_longform_video.mp4` using chapter-based editorial visuals, long-form audio, and a music bed. It does not upload yet.

## Required Secrets

Copy `.env.example` to `.env` for local runs, or add these as GitHub Actions secrets:

- `GEMINI_API_KEY`
- `ANTHROPIC_API_KEY`
- `POLLINATIONS_API_KEY`
- `PEXELS_API_KEY`
- `COVERR_API_KEY`
- `YOUTUBE_CLIENT_ID`
- `YOUTUBE_CLIENT_SECRET`
- `YOUTUBE_REFRESH_TOKEN`
- `ALERT_EMAIL_FROM`
- `ALERT_EMAIL_TO`
- `ALERT_EMAIL_PASSWORD`

Coverr is used by the long-form stock-footage renderer. Shorts still keep Coverr disabled unless the Shorts config enables it.

## YouTube OAuth

Before enabling upload, generate a refresh token while signed into the Google/YouTube account that owns **Soft Reset With Me**:

```bash
python tools/get_youtube_token.py
```

Choose the `Soft Reset With Me` channel/account in the Google consent screen. Then update:

- local `.env`: `YOUTUBE_REFRESH_TOKEN=...`
- GitHub secret: `YOUTUBE_REFRESH_TOKEN`

Verify the token points to the right channel:

```bash
python tools/check_youtube_channel.py
```

Do not run GitHub Actions with `upload=true` until this prints `Soft Reset With Me`.

The OAuth token must include YouTube upload and YouTube Analytics scopes. If Analytics sync reports an insufficient-scope error, rerun `tools/get_youtube_token.py` and update the `YOUTUBE_REFRESH_TOKEN` secret again.

## Performance Feedback

The pipeline syncs YouTube Analytics before research. It stores recent video metrics in `performance_memory_soft_reset.json`, including views, engaged views, average view duration, average view percentage, likes, comments, shares, and subscribers gained when available.

Shorts and long-form analytics are intentionally separate. Long-form uses higher minimum view thresholds, a longer lookback window, and different sample-size gates because 5-7 minute videos should be judged by watch time, retention curve behavior, and chapter coherence rather than Shorts completion dynamics.

Research and script prompts use staged learning so the channel does not overfit the first few Shorts:

- 0-7 valid videos: collect data only; keep testing different pillars and formats.
- 8-24 valid videos: use individual winning/weak examples directionally, not category conclusions.
- 25+ valid videos: use pattern-level feedback by category, format, angle, hook quality, and research-score calibration.

Videos younger than 2 days are skipped for analytics, cached analytics are reused for 7 days, and pattern-level analysis ignores videos below the configured minimum view threshold. The `composite_score` weighs hook power, hold, emotional resonance, and reach rather than raw views alone:

- 35% hook score: `engagedViews / views`
- 35% hold score: `averageViewPercentage`
- 20% resonance score: weighted engagement divided by `engagedViews`
- 10% reach score: lightly weighted log-scaled views

`performance_score` is kept as a backward-compatible alias for `composite_score`.

## Editorial Layer

The pipeline is designed to avoid generic AI output. Topic research must now produce a `core_claim`, `editorial_seed`, and `only_soft_reset_line` before scripting. The script validator checks for an explicit point of view and a signature Soft Reset sentence, then retries weak scripts before rendering.

The script agent also runs an argument-coherence review. It checks whether the hook promise matches the payoff, every spoken section supports the `core_claim`, and no section drifts into neutral explainer mode. Failed reviews trigger a script rewrite with the review notes.

This keeps AI in the execution role while the channel direction remains opinionated, emotionally specific, and non-templated.

## GitHub Actions

The workflow at `.github/workflows/run_pipeline.yml` runs the pipeline on the configured posting schedule and can also be triggered manually from the Actions tab.

Scheduled GitHub Actions runs upload to YouTube by default. Manual runs render with `--skip-upload` unless the `upload` input is set to `true`. Rendered videos are saved as workflow artifacts for 7 days.

The workflow commits `topic_memory_soft_reset.json` and `performance_memory_soft_reset.json` after successful runs so the channel avoids repeating recent topics and can learn from uploaded video performance.

## Important Files

- `config/pipeline_config.json` - brand, schedule, provider, rendering, and upload settings
- `prompts/script_prompt.txt` - script and hook rules
- `prompts/research_candidates_prompt.txt` - topic research direction
- `modules/image_gen.py` - Pexels/generated visual asset selection
- `modules/video_assembler.py` - final render, captions, music, film overlay, CTA card
- `topic_memory_soft_reset.json` - recent topic memory
