# Clip-Only Pipeline Implementation Plan

Source design: `docs/superpowers/specs/2026-07-31-clip-only-pipeline-redesign.md`

## Release gate

All scheduled production work remains disabled and all uploads remain private until the mock, no-upload, and private-upload checks pass. Enabling public publishing is a separate explicit change after review.

## Phase 1 — Safety

- Add a shared automation kill switch and enforce it in both scheduled workflows.
- Change both tracks from `public_now`/`public` to scheduled-private behavior.
- Deduplicate YouTube authentication alerts across repeated schedule failures.
- Add stable publication job keys and refuse duplicate uploads.

## Phase 2 — Clip-only assets

- Replace the Shorts image/clip generator with a video-only asset selector.
- Remove Pollinations, Gemini image generation, and stock-image fallbacks.
- Remove thumbnail/static-frame scene fallbacks from both assemblers.
- Make missing video media an explicit bounded failure.

## Phase 3 — Global clip planning

- Add candidate metadata and preview collection for Pexels/Coverr.
- Add deterministic global assignment with provider-ID, URL, hash, recent-use, and semantic-diversity constraints.
- Add persistent clip-use memory.
- Add bounded alternate-query search.

## Phase 4 — Thumbnails

- Build Shorts poster artifacts from opening source footage only.
- Rebuild long-form A/B/C variants from source frames or local typography.
- Use aspect-preserving crops and actual rendered-result selection.
- Send the long-form package before upload/publication and retain optional manual prompts.

## Phase 5 — Direction, schedules, and learning

- Add optional weekly direction input and automatic fallback.
- Move weekly strategy to Monday 4:00 AM ET.
- Trigger daily Shorts generation at 6:00 AM ET and schedule publication at 8:00 PM ET.
- Trigger long-form generation Saturday at 6:00 AM ET and schedule Sunday noon publication.
- Store creative-decision fields with the existing performance memory for 48-hour/seven-day analysis.

## Verification

- Unit tests for safety gates, deduplication, assignment, crop behavior, and schedules.
- Mock end-to-end runs for both tracks.
- Real-provider/no-upload Short.
- Real-provider/no-upload long-form render and email package.
- One private upload for each track.
- Diff review confirming no automatic image-generation call remains.

