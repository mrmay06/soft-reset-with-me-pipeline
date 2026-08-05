# Delayed GitHub Schedule Gate Design

Date: 2026-08-05

## Problem

GitHub Actions scheduled jobs can start after their nominal cron minute. The current gate requires the runner's New York wall-clock hour to equal 06, so delayed jobs at 07:00 or later exit successfully before generation. The paired UTC cron entries also create two scheduled invocations per day for daylight-saving support.

## Design

Move the DST decision into a small, tested Python helper. For a scheduled event, the helper reads the exact cron expression that fired from `GITHUB_EVENT_SCHEDULE`, derives the expected UTC hour for 06:00 America/New_York from the runner's current offset, and permits only the matching cron entry. It does not require the current runner hour to remain 06:00. Therefore a delayed 10:00 UTC summer cron still runs at 07:54 ET, while the paired 11:00 UTC cron is skipped. In winter the 11:00 UTC entry becomes the active one.

Manual dispatches bypass the schedule-expression check and continue to run when explicitly requested. Disabled automation continues to block scheduled runs.

## Failure behavior

Missing or malformed schedule metadata fails closed for scheduled events and prints the expression, local time, and expected UTC hour. This makes an invalid event visible without silently creating duplicate content. The workflow remains green only for a deliberate skip; the log explicitly reports `should_run=false` and the reason.

## Verification

Unit tests cover summer and winter offsets, delayed starts, duplicate cron entries, manual dispatch, disabled automation, and malformed expressions. Both workflow YAML files pass the existing schedule validator. A manual mock dispatch confirms the updated gate can proceed through the pipeline without uploading a video.
