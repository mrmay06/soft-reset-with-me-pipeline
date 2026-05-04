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

## Required Secrets

Copy `.env.example` to `.env` for local runs, or add these as GitHub Actions secrets:

- `GEMINI_API_KEY`
- `ANTHROPIC_API_KEY`
- `POLLINATIONS_API_KEY`
- `PEXELS_API_KEY`
- `YOUTUBE_CLIENT_ID`
- `YOUTUBE_CLIENT_SECRET`
- `YOUTUBE_REFRESH_TOKEN`
- `ALERT_EMAIL_FROM`
- `ALERT_EMAIL_TO`
- `ALERT_EMAIL_PASSWORD`

`COVERR_API_KEY` is optional for now because Coverr is disabled in Shorts config.

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

## GitHub Actions

The workflow at `.github/workflows/run_pipeline.yml` runs the pipeline on the configured posting schedule and can also be triggered manually from the Actions tab.

Scheduled GitHub Actions runs upload to YouTube by default. Manual runs render with `--skip-upload` unless the `upload` input is set to `true`. Rendered videos are saved as workflow artifacts for 7 days.

The workflow commits only `topic_memory_soft_reset.json` after successful runs so the channel avoids repeating recent topics.

## Important Files

- `config/pipeline_config.json` - brand, schedule, provider, rendering, and upload settings
- `prompts/script_prompt.txt` - script and hook rules
- `prompts/research_candidates_prompt.txt` - topic research direction
- `modules/image_gen.py` - Pexels/generated visual asset selection
- `modules/video_assembler.py` - final render, captions, music, film overlay, CTA card
- `topic_memory_soft_reset.json` - recent topic memory
