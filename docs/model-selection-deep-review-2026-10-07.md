# Cross-provider model selection review — 2026-10-07

Scope: read-only first-party documentation research for Soft Reset With Me's topic discovery, scriptwriting/review, visual direction, finished-video inspection and narration. No paid inference, account purchases, production model changes or publishing. Recommendations are hypotheses for controlled testing, not measured creative-quality winners.

## Decision principles

- Compare cost per **accepted, usable video**, not cost per token. Count reasoning, retries, rejected scripts, voice regenerations, search/extraction fees, subscriptions and operational maintenance.
- Distinguish model developers from hosts: Together/Fireworks/OpenRouter serve models; they are not interchangeable with a model's first-party endpoint.
- Do not infer English emotional storytelling quality from coding, math, agent or generic intelligence benchmarks. The relevant test is the same briefs, prompts and constraints, blind editorial comparison, then listener checks.
- Research breadth does not imply production provider breadth. A compact production stack with one deliberate fallback is preferable to a dozen APIs absent measured benefit.
- Discovery signals and evidence verification are different tasks. Everyday emotional observations do not need fabricated citations; empirical claims need inspected supporting sources.

## Current reference configuration

Local configuration uses Gemini 2.5 Flash for topics/metadata/Short visual direction/finished-video audit, Sonnet 4.6 for writing and argument review, Gemini 2.5 Flash-Lite for the creative gate, Gemini 2.5 Flash Preview TTS with Aoede (Shorts)/Puck (long), and local faster-whisper for captions. This is local repository evidence, not confirmation of GitHub's deployed configuration.

The current script adapter recognizes Claude IDs and routes other IDs to Google. OpenAI or OpenAI-compatible APIs require explicit integration. Claude parsers currently assume the first returned content block is text; adaptive thinking migration requires checking block parsing and output limits.

## OpenAI: text candidates and audio caveat

Standard short-context API prices per million tokens: **GPT-6 Luna $0.10 input/$0.50 output; GPT-6.1 Sol $2/$10; GPT-6 Astra $10/$50**. Long-context prices, cache writes, tools and reasoning have separate effects. [Official pricing](https://developers.openai.com/api/docs/pricing).

Luna supports structured outputs and search tools and is positioned for cost-efficient workloads; Sol is positioned as balanced capability. These support candidate roles in ranking/extraction and writing/review respectively, not an assertion of superior scripts. [Luna specification](https://developers.openai.com/api/docs/models/gpt-6-luna), [Sol specification](https://developers.openai.com/api/docs/models/gpt-6.1-sol).

Sol does not support `none` reasoning; use documented effort controls and parse actual usage. Context size is already far beyond this project's need and should not determine the winner. [Current model guide](https://developers.openai.com/api/docs/guides/latest-model).

The TTS guide still recommends GPT-4o Mini TTS and documents delivery instructions plus English-optimized voices. However, the model page marks it deprecated, and the retirement schedule lists January 6, 2027 removal of its snapshots, with GPT-Realtime-2.1-Mini as replacement. Do not start a fresh legacy TTS integration from the stale guide alone. A Realtime replacement needs exact-recitation and audio-capture testing, not an assumption that conversational audio equals narration TTS. [TTS guide](https://developers.openai.com/api/docs/guides/text-to-speech), [model page](https://developers.openai.com/api/docs/models/gpt-4o-mini-tts), [retirement notice](https://developers.openai.com/api/docs/deprecations).

## Additional developer/host options

### MiniMax

MiniMax-M3 Standard, up to 512K input, is **$0.30/M input, $1.20/M output**, cache reads $0.06/M. Above 512K prices double; Priority is 1.5 times Standard. The provider describes the 50% reduction as permanent. Its pricing separates pay-as-you-go API keys from subscription keys. [Official MiniMax pricing](https://platform.minimax.io/docs/guides/pricing-paygo).

MiniMax is a budget writer/reviewer challenger, not automatically the best English emotional narrator. Speech 2.8 Turbo/HD are **$60/$100 per million characters** respectively; async synthesis supports up to 1M characters. At an assumed 900 characters/minute these are $0.054/$0.09 per minute. This is a conversion assumption, not measured script speed or a quality claim. [Official pricing](https://platform.minimax.io/docs/guides/pricing-paygo).

### Z.ai GLM

GLM-5.3-Flash is **$0.15/M input, $0.50/M output**, versus flagship GLM-5.3 **$1.40/$4.40**. Web search separately costs $0.01/use. Cheap/free legacy variants exist but should not be chosen solely because their token price is zero. [Official pricing](https://docs.z.ai/guides/overview/pricing).

Inference: Flash is a candidate for extraction, topic ranking, query generation and structured checks; the flagship can challenge premium writers. English idiom, brevity and JSON acceptance remain untested here.

### Moonshot Kimi

Kimi K3 is a current flagship with strict structured output and always-on thinking; default effort is `max`, with `low` and `high` alternatives. Its documentation explicitly says its web search is being updated and is not recommended for near-term production use. This prevents treating it as a ready-made research replacement merely because it is a capable model. [Official K3 guide](https://platform.kimi.ai/docs/guide/kimi-k3-quickstart).

Together currently lists Kimi K3 at promotional **$2.70/M input, $13.50/M output**, cache reads $0.27/M. This is **Together's hosted price**, not a verified first-party Moonshot price. The Moonshot pricing page's text retrieval did not expose its numeric table. [Together pricing](https://www.together.ai/pricing), [Moonshot billing semantics](https://platform.kimi.ai/docs/pricing/chat).

### Inception Mercury

Mercury 2.5 currently advertises discounted **$0.04/M input, $0.15/M output**, against crossed-out $0.20/$0.75; 260K context, reasoning and structured output. Treat discount duration/account access as unverified. Speed is not an important differentiator for one scheduled video per day, but cheap structured processing may be worth testing. Do not interpret "Mercury Voice" branding as verified standalone narration TTS. [Official model catalog](https://www.inceptionlabs.ai/models).

### Cohere and WRITER

Cohere Command A+ documents reasoning, citations, tool use and structured outputs; numeric self-serve pricing was not established from the fetched official page. Older Command A lists $2.50/$10 but is not substituted as the latest model. Cohere's enterprise grounding strengths are plausible, but this project has not demonstrated a need for enterprise retrieval infrastructure. [Command A+](https://docs.cohere.com/docs/command-a-plus), [older Command A](https://docs.cohere.com/docs/command-a).

WRITER's current model page presents Palmyra X6 and platform-level agent benchmarks, but did not establish a complete self-serve input/output rate card. Do not reuse a price appearing in a marketing UI mockup as an API price. Defer pending transparent account pricing and evidence that it improves this use case. [Official model page](https://writer.com/models/).

## Serving platforms and operational cost

Together lists many current open-model endpoints with pay-per-token prices, including GLM, Qwen, DeepSeek, MiniMax and Kimi. Prices, versions and endpoint capabilities must be checked per host. Open weights do not make a hosted endpoint free; a local deployment also has compute and maintenance costs. [Together rate card](https://www.together.ai/pricing).

OpenRouter's current Standard plan lists a **5.5% platform fee** and Business 8%; provider policy/routing controls and paid/free limits differ. Its routing API supports constraining allowed providers, supported parameters, retention and prices. It can simplify evaluation, but pin the actual provider/version and cost ceiling; do not let automatic routing silently change a controlled comparison. [OpenRouter pricing](https://openrouter.ai/pricing), [routing controls](https://openrouter.ai/docs/guides/routing/provider-selection).

## Evaluation design — proposed, not executed

1. Use six topic briefs covering grief, boundaries, communication, self-worth, uncertainty and a non-breakup everyday scenario. Add two factual-claim traps to test calibration. Keep the retrieved evidence identical across writers.
2. Run current Sonnet 4.6 as the control. Initial writer challengers: Sonnet 5.5, Opus 5.5, GPT-6.1 Sol and one budget challenger selected from DeepSeek/Qwen/GLM/MiniMax. Broaden only if a candidate has a clear weakness.
3. Evaluate Shorts and long-form separately. Score recognition/specificity, hook honesty, progression, fresh insight, payoff, fairness, spoken naturalness, visual searchability and repetition. Record failures and costs separately; do not hide low quality behind a cheap blended score.
4. Blind labels and shuffle output order. Do not use the writer as the only judge. Human pairwise preference and quoted evidence matter more than a model's self-score.
5. Audition identical 30-second and two-minute passages on TTS finalists. Include a quiet hook, contrasting emotional turn, contractions, a quoted message and an ending. Check pronunciation, identity drift, prosody, text omissions/additions and regeneration frequency.
6. Only after winners emerge, make the smallest adapter/prompt change and run a short unpublished end-to-end test. No full render is required to compare text or voice initially.

These are proposed evaluation steps, not authorization or evidence that tests have been run. Real channel reach and monetization eligibility cannot be established by a model comparison alone.

## Research appendices

### Expanded rate-card shortlist

USD per million uncached input/output tokens; ordinary short-context Standard rates, no thinking-volume/retry/tool estimate. These are documented prices, not ranked output quality.

| Model | Input / output | Qualification |
|---|---:|---|
| Sonnet 5.5 | $2 / $10 | Current main-writer challenger |
| Opus 5.5 | $4 / $20 | Premium writer/selective critic; thinking always on |
| GPT-6.1 Sol | $2 / $10 | Cross-provider writer challenger |
| GPT-6 Luna | $0.10 / $0.50 | Cheap structured-processing challenger |
| Gemini 3.8 Flash | $0.75 / $3.75 | Stable; doubles Jan 1 |
| Gemini 3.1 Pro Preview | $2 / $12 | Up to 200K input; preview |
| DeepSeek V4.1 Flash | $0.30 / $1.20 | Direct peak rates; off-peak half |
| Qwen3.8 Flash | $0.15 / $0.47 | Singapore region baseline |
| Qwen3.8 Max | $2 / $6 | Singapore region baseline |
| Mistral Large 3 | $0.50 / $1.50 | GA, dated ID mistral-large-2512 |
| Mistral Large 4 | $1.36 / $4.18 | Public preview; two-week launch rate half |
| Grok 4.7 | $2 / $6 | Under 200K input; thinking cannot be disabled |
| GLM-5.3 Flash | $0.15 / $0.50 | Structured-processing challenger |
| MiniMax M3 | $0.30 / $1.20 | Under 512K input |
| Mercury 2.5 | $0.04 / $0.15 | Current discount; duration unverified |

Sources: [Claude pricing](https://platform.claude.com/docs/en/about-claude/pricing), [OpenAI pricing](https://developers.openai.com/api/docs/pricing), [Google pricing](https://ai.google.dev/gemini-api/docs/pricing), [DeepSeek pricing](https://api-docs.deepseek.com/quick_start/pricing/), [Alibaba pricing](https://www.alibabacloud.com/help/en/model-studio/model-pricing), [Mistral pricing](https://docs.mistral.ai/inference/pricing), [xAI pricing](https://docs.x.ai/developers/pricing), [GLM pricing](https://docs.z.ai/guides/overview/pricing), [MiniMax pricing](https://platform.minimax.io/docs/guides/pricing-paygo), [Mercury catalog](https://www.inceptionlabs.ai/models).

### Voice finalists and illustrative monthly volume

At 900 characters per minute where character billing applies, one successful take:

- Google 3.8 Flash TTS: $0.0135/audio minute output now, plus text; doubles Jan 1.
- Eleven v4: $0.072/min regular, $0.0198/min launch until Oct 12; v4 Turbo $0.036/min regular.
- Cartesia Sonic 3.6: roughly $0.045/min at full consumption of the $5/100K-credit Pro plan. Actual minimum invoice is $5, not that fractional cost.
- Polly Neural: $0.0144/min, excluding separately billed Speech Marks.
- Deepgram Aura 2: $0.027/min; 2K-character limit means chunking long narration.

Sources: [Google](https://ai.google.dev/gemini-api/docs/pricing), [ElevenAPI](https://elevenlabs.io/pricing/api), [Cartesia](https://www.cartesia.ai/pricing), [Polly](https://aws.amazon.com/polly/pricing/), [Deepgram](https://deepgram.com/pricing). Voice report below explains commercial rights, plan minima and endpoint differences.

Illustration only: 30 half-minute Shorts plus four five-minute videos = 35 audio minutes/month. Google's current Flash audio-output charge would be $0.4725; January's $0.945. Eleven v4 regular variable charge would be $2.52, before commercial-plan minimums. These are not whole-pipeline estimates; media audits, script/review calls, search, retakes, rendering and storage are excluded.

### Narrow production hypothesis

Evaluate broadly but ship narrowly: one economical discovery/structured model, one primary writer, one optional selective critic, one narration provider, and a capable multimodal finished-video reviewer. Do not replace Gemini's video input with a text-only cheap model. Preserve local captions unless provider timestamps demonstrably improve acceptance/maintenance.

Priority: compare Sonnet 5.5, GPT-6.1 Sol, Opus 5.5 and Mistral Large 3 against existing Sonnet 4.6; audition Google 3.8 Flash/Lite and Eleven v4, with Cartesia if native timestamps materially simplify the pipeline. This is a testing shortlist, not a final quality verdict.

- [Premium Claude/Gemini and search APIs](model-research-premium-and-search-2026-10-07.md)
- [DeepSeek, Qwen, Mistral and Grok](model-research-text-challengers-2026-10-07.md)
- [Voice platforms, pricing and delivery controls](model-research-voice-landscape-2026-10-07.md)

## Open questions

No account-specific quota, actual uptime, actual creative output, real voice quality or real cost per accepted video was tested. Temporary prices, release aliases, hidden reasoning, pricing-page conflicts and commercial-use terms need rechecking at purchase/migration time. This report avoids certifying any provider as "best" without those observations.
