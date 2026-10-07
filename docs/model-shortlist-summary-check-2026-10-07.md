# Shortlist price sanity check — 2026-10-07

Scope: fresh first-party rate-card check against `model-selection-deep-review-2026-10-07.md`. No inference calls, purchases or production changes.

| Item | Verified ordinary Standard price | Check |
|---|---|---|
| Claude Sonnet 5.5 | $2/M input; $10/M output | Matches. Full 1M context uses standard rates. [Claude pricing](https://platform.claude.com/docs/en/about-claude/pricing) |
| GPT-6.1 Sol | $2/M input; $10/M output for short context | Matches. Long context is $4/$15; do not treat $2/$10 as universal. [OpenAI pricing](https://developers.openai.com/api/docs/pricing) |
| Gemini 3.8 Flash | $0.75/M input; $3.75/M output through December 31, 2026 | Matches. Output includes thinking; January 1, 2027 rates are $1.50/$7.50. [Google pricing](https://ai.google.dev/gemini-api/docs/pricing) |
| Gemini 3.8 Flash TTS | $0.50/M text input; $9/M audio output through December 31, 2026 | Matches. At 25 audio tokens/second, one minute is 1,500 tokens: $0.0135/min output. January rates double to $1/$18 and $0.027/min output. [Google pricing](https://ai.google.dev/gemini-api/docs/pricing) |

No price disagreements found in the requested four checks. The 35-minute illustration correctly totals $0.4725 now and $0.945 from January, excluding text, retries and other pipeline costs.

Important comparison caveat: Anthropic says Claude 4.7+ uses a newer tokenizer producing approximately 30% more tokens for the same text, depending on workload. Sonnet 5.5's lower token rates therefore do not directly imply the same proportional savings versus Sonnet 4.6. [Claude pricing](https://platform.claude.com/docs/en/about-claude/pricing)

These checks establish listed prices, not creative quality, voice suitability, account quota or cost per accepted video.
