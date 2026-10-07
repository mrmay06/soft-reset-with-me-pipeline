# Anthropic + Gemini: selected implementation

Updated 2026-10-07. Local implementation only; not a deployment or a creative-quality verdict.

## Model ownership

| Stage | Model |
| --- | --- |
| Short/long script and argument review | claude-sonnet-5-5 |
| Topic research, ranking, metadata, clip direction, creative gate, video audit | gemini-3.8-flash |
| Narration | gemini-3.8-flash-tts; Aoede (Short), Puck (long) |
| Weekly analysis / channel analysis | gemini-3.8-flash |
| Weekly strategy editorial review | claude-sonnet-5-5 |

No GPT, Opus, external TTS provider, or untested Lite downgrade is enabled. Stock footage remains clip-only. Local captions and rendering remain unchanged. Creative gates inspect packaging/safety; Claude reviews narrative arguments, so their responsibilities remain distinct.

## Compatibility and safeguards

- Claude text extraction ignores thinking blocks and rejects truncated/empty responses. Sonnet 5.5 requests medium effort with `between_tools` to suppress up-front thinking. Output allowances are 2,048 tokens for Shorts and 8,192 for long scripts; these are ceilings, not fixed usage.
- Gemini 3.8 narration uses GenerateContent REST with per-part `speech_metadata.style`, keeping direction outside the spoken transcript. This works without requiring a local legacy Google SDK to understand the new metadata field.
- Returned WAV bytes are preserved, not manually wrapped again. Legacy PCM output remains supported for explicit rollback. No automatic model fallback conceals paid failures.
- Existing script prompts, lengths, clip flow, review gates, schedules, upload visibility and OAuth credentials are not redesigned by this model migration.

## Backup and rollback

Pre-update source copies of affected existing files, including prior uncommitted edits, are in `.audit-backups/two-provider-2026-10-07/`. This folder is gitignored; retain locally. Restore only selected affected files from these copies after checking later edits. Git HEAD is not the rollback baseline because it omits existing work.

## Verification boundary

All 135 offline regression tests passed, including six new migration tests. Coverage includes provider settings, Claude block parsing/truncation, transcript/style separation, new WAV output, legacy PCM output, usage extraction, and private error handling. Existing unclosed-file warnings in prompt readers remain non-failing. No paid inference, upload, workflow dispatch, push, or merge is part of this update. Before deployment, verify account access and listen to a short narration test, then run an unpublished Short and two-minute long-form end-to-end test. Publishing authentication remains a separate readiness check.

Remaining improvements from the research summary: provenance logging, pipeline outcome reporting, prompt-by-prompt editorial evaluation, clip relevance/variety improvements, and cost-per-accepted-video measurement. These are not marked complete by changing models.

Official references: [Sonnet 5.5](https://platform.claude.com/docs/en/models/sonnet-5-5/overview), [Gemini 3.8 TTS migration](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash-tts), [speech generation](https://ai.google.dev/gemini-api/docs/speech-generation).
