# Official model and pricing research — 2026-10-07

Read-only research against live first-party documentation. No paid inference or product changes. USD list prices; taxes, retries, account eligibility and negotiated discounts are not estimated. This records the actual live docs, including September 2026 releases, rather than extrapolating from older model knowledge.

## Google Gemini

### Relevant paid Standard prices

Per million tokens; TTS input is text and output is audio. [Official Gemini Developer API pricing](https://ai.google.dev/gemini-api/docs/pricing).

| Model ID | Input | Output |
|---|---:|---:|
| gemini-2.5-flash | $0.30 | $2.50 |
| gemini-3.5-flash-lite | $0.30 | $2.50 |
| gemini-3.8-flash | $0.75 | $3.75 |
| gemini-2.5-flash-preview-tts | $0.50 | $10 |
| gemini-2.5-pro-preview-tts | $1 | $20 |
| gemini-3.1-flash-tts-preview | $1 | $20 |
| gemini-3.8-flash-tts | $0.50 | $9 |
| gemini-3.8-flash-lite-tts | $0.50 | $6 |

3.8 prices double January 1, 2027. Text output includes thinking. For 3.8 TTS, 25 audio tokens/second gives output-only costs of $0.0135/minute (Flash) and $0.009/minute (Lite). Batch/Flex is half Standard on these 3.8 models; Priority is 1.8×. [Pricing](https://ai.google.dev/gemini-api/docs/pricing).

Search grounding: 2.5 Flash allows 1,500 paid-tier grounded prompts/day free, shared with Flash-Lite, then $35/1,000 grounded prompts. Gemini 3.x shares 5,000 free search requests/month, then $14/1,000; each executed query is billed, so one user request can incur multiple charges. Free model tokens do not imply free paid-tier grounding. [Pricing](https://ai.google.dev/gemini-api/docs/pricing).

### Lifecycle and integration implications

- Gemini 3.8 Flash, 3.8 Flash TTS and 3.8 Flash-Lite TTS are explicitly listed as **stable**, not preview. Gemini 3.5 Flash-Lite is also stable. [Model catalog](https://ai.google.dev/gemini-api/docs/models).
- 3.8 Flash released September 2, 2026; both 3.8 TTS models released September 22. No shutdown dates are announced. [Deprecation schedule](https://ai.google.dev/gemini-api/docs/deprecations).
- Existing `gemini-2.5-flash` remains served with no shutdown date announced, but access is restricted to users who have actively used 2.5 previously. Google directs new projects to 3.5 Flash-Lite or 3.8 Flash. [Deprecation schedule](https://ai.google.dev/gemini-api/docs/deprecations).
- **Existing `gemini-2.5-flash-preview-tts` has a listed shutdown date of November 17, 2026**, as do 2.5 Pro Preview TTS and 3.1 Flash TTS Preview. Recommended replacements are the two stable 3.8 TTS models. The schedule explains that table dates are earliest possible retirement dates and exact shutdown is communicated in advance. [Deprecation schedule](https://ai.google.dev/gemini-api/docs/deprecations).
- Migrating TTS is not just a model-name swap: 3.8 treats transcript text verbatim. Sustained delivery instructions belong in `speech_metadata.style`, speaker identity in metadata, and short vocal events in angle-bracket tags. Old inline directions may be spoken aloud. Both 3.8 models share the new schema. [Flash TTS migration guide](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash-tts), [Flash-Lite TTS migration guide](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash-lite-tts).
- Google positions Flash TTS for maximum fidelity, acting and regional dialects; Lite for high-throughput, low-latency everyday speech. This is vendor positioning, not a measured quality result for this project's scripts. [TTS comparison](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash-tts).
- Aoede (breezy) and Puck (upbeat) remain listed prebuilt voices. Current TTS docs require recent SDKs or REST, and distinguish exact-recitation TTS from interactive Live API audio. [Speech generation guide](https://ai.google.dev/gemini-api/docs/speech-generation).

Paid **usage tiers** govern quotas/eligibility, not the Standard/Batch/Flex/Priority price categories. Tier 1 requires linked active billing; Tier 2 requires $100 paid plus three days after first successful payment; Tier 3 requires $1,000 plus 30 days. Exact limits are account/model-dependent and shown in AI Studio. [Rate limits](https://ai.google.dev/gemini-api/docs/rate-limits).

For Gemini thinking models, capture actual usage instead of inferring it from visible response length. Thinking configuration and thought signatures differ between Interactions and GenerateContent. [Thinking guide](https://ai.google.dev/gemini-api/docs/thinking).

## Anthropic script models

| Model | First-party API ID | Standard input/output per 1M tokens | Lifecycle |
|---|---|---|---|
| Sonnet 4.6 (existing) | claude-sonnet-4-6 | $3 / $15 | Active legacy; retirement not sooner than Feb 17, 2027 |
| Sonnet 5.5 | claude-sonnet-5-5 | $2 / $10 | Latest active; released Sep 28, 2026; retirement not sooner than Sep 28, 2027 |
| Haiku 4.5 | claude-haiku-4-5-20251001 | $1 / $5 | Current fast/cost-oriented model |

Sources: [Sonnet 4.6 overview](https://platform.claude.com/docs/en/models/sonnet-4-6/overview), [Sonnet 5.5 overview](https://platform.claude.com/docs/en/models/sonnet-5-5/overview), [Haiku 4.5 overview](https://platform.claude.com/docs/en/models/haiku-4-5/overview).

Batch processing discounts input/output 50%. First-party global pricing is the baseline; `inference_geo: "us"` adds 10% for Claude 4.6+. Partner Bedrock/Google Cloud regional or multi-region endpoints have distinct pricing. Claude 4.6+ includes 1M context at Standard token rates. Newer tokenizer models can produce approximately 30% more tokens for identical text, so dollar-per-token savings need workload measurement. [Pricing](https://platform.claude.com/docs/en/about-claude/pricing).

Sonnet 5.5 defaults to adaptive thinking and high effort; non-default temperature/top-p/top-k returns 400. Test migration before switching an existing script generator, especially if it controls temperature. Lower nominal rates do not establish script quality. [Sonnet 5.5 overview](https://platform.claude.com/docs/en/models/sonnet-5-5/overview).

Thinking contributes to billed output tokens. Manual `thinking.type: enabled` with `budget_tokens` is deprecated but still accepted on 4.6; 4.7+ rejects it. Adaptive thinking uses effort controls instead. The response usage breakdown exposes internal reasoning token counts; hidden/summarized thinking should not be treated as free. [Extended thinking](https://platform.claude.com/docs/en/build-with-claude/extended-thinking).

Sonnet 4.5 is already deprecated and lists retirement November 30, 2026; Sonnet 4 is retired. Neither is a sensible fresh migration target. [Model deprecations](https://platform.claude.com/docs/en/about-claude/model-deprecations).

## ElevenLabs comparison

Current ElevenAPI pricing lists **Flash/Turbo $0.04 per 1,000 characters** and **v2 Multilingual $0.08 per 1,000 characters**. Its API FAQ says billing is USD, not credits. Character pricing is not word or token pricing; compare using actual script character count and produced audio duration. Plan allowances, minimum commitment, commercial rights and overage rules need verification against the intended account/plan before purchase. Older help pages discuss credits, so do not silently mix the Creative subscription credit model with the current ElevenAPI offering. [Current ElevenAPI pricing and FAQ](https://elevenlabs.io/pricing/api), [older credits help article](https://help.elevenlabs.io/hc/en-us/articles/27562020846481-What-are-credits).

## OpenAI comparison

Current Standard short-context list prices are GPT-6 Luna **$0.10/M input, $0.50/M output** and GPT-6.1 Sol **$2/M input, $10/M output**. Long-context prices differ; hidden reasoning, tools, retries and cache writes can add cost. [Official pricing](https://developers.openai.com/api/docs/pricing).

OpenAI positions Luna as its fastest and most cost-effective GPT-6 option, and Sol as balanced speed/cost/intelligence. These are candidate roles, not proof of relationship-script quality. [Current model guide](https://developers.openai.com/api/docs/guides/latest-model).

The repository currently routes Claude IDs to Anthropic and other script IDs to Google. An OpenAI model requires a real provider integration, not just a configuration edit. No OpenAI inference or migration was performed.

## Decision-ready interpretation and remaining uncertainty

The urgent lifecycle issue is existing preview Gemini TTS, not stable 2.5 Flash text or Sonnet 4.6. Candidate evaluation: stable 3.8 Flash TTS versus Lite for sound quality/latency, and Sonnet 5.5 versus Haiku 4.5 for script quality/cost. This is an inference from lifecycle, integration and list-price evidence—not authorization to change production.

No model calls were made. Account availability, provider rate limits, successful SDK migration, voice consistency, real reasoning usage, Hindi/English delivery, retries and quality are unverified. Use logged actual input/output/thinking/audio usage and per-stage retry counts for a realistic pipeline cost estimate. Audio cost estimates above exclude text input, voice design/replication and retries. Recheck temporary 3.8 prices before January 2027.
