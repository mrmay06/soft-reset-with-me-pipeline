# Premium writing models and retrieval APIs — 2026-10-07

Live first-party documentation research only; no paid calls or product edits. USD list prices. Quality comparisons below are candidate-selection inferences, not benchmarks run on this pipeline.

## Anthropic writer / critic candidates

| Exact first-party API ID | Input/output per million tokens | Context / max output | Thinking |
|---|---|---|---|
| claude-opus-5-5 | $4 / $20 | 1M / 128K | Adaptive, always on; medium default effort |
| claude-sonnet-5-5 | $2 / $10 | 1M / 128K | Adaptive; high default effort |
| claude-sonnet-4-6 | $3 / $15 | 1M / 64K | Adaptive supported; legacy manual mode deprecated |
| claude-haiku-4-5-20251001 | $1 / $5 | 200K / 64K | Manual extended thinking; no effort control |

Sources: [Opus 5.5](https://platform.claude.com/docs/en/models/opus-5-5/overview), [Sonnet 5.5](https://platform.claude.com/docs/en/models/sonnet-5-5/overview), [Sonnet 4.6](https://platform.claude.com/docs/en/models/sonnet-4-6/overview), [Haiku 4.5](https://platform.claude.com/docs/en/models/haiku-4-5/overview).

Opus 5.5 released September 22, 2026; its earliest retirement commitment is September 22, 2027. Both Opus/Sonnet 5.5 support `low`, `medium`, `high`, `xhigh`, `max` effort. Opus cannot disable thinking. Sonnet can suppress up-front thinking with `thinking.type: between_tools` at low/medium/high, but not xhigh/max. Effort is not a hard token budget; thinking counts toward max output even when hidden. [Opus overview](https://platform.claude.com/docs/en/models/opus-5-5/overview), [Effort guide](https://platform.claude.com/docs/en/build-with-claude/effort).

Claude 4.6+ has no long-context surcharge across the full 1M window. Batch input/output is discounted 50%. Opus 5.5 Fast mode is separately priced at $8/$40, not the $4/$20 Standard rate. First-party US inference geography adds 10%; partner regional endpoints have distinct terms. Newer tokenizers can produce roughly 30% more tokens for identical text, so compare actual bills rather than nominal rates alone. [Official pricing](https://platform.claude.com/docs/en/about-claude/pricing).

Inference: compare Sonnet 5.5 as main writer, Opus 5.5 as a premium writer or selective critic, and Haiku as low-cost classification/deduplication. Opus costs 2× Sonnet per token and always reasons; choosing it for every short script is not automatically better. Measure factual accuracy, freshness, hook specificity, narrative flow, spoken delivery, repetition and acceptance rate on the same briefs.

## Google Gemini writer / grounded-research candidates

| Exact API ID | Paid Standard input/output per million text tokens | Status |
|---|---|---|
| gemini-3.1-pro-preview | $2/$12 up to 200K prompt; $4/$18 above 200K | Preview |
| gemini-3.8-flash | $0.75/$3.75 through Dec 2026; $1.50/$7.50 Jan 2027 | Stable |
| gemini-3.5-flash-lite | $0.30/$2.50 | Stable |
| gemini-3.1-flash-lite | $0.25/$1.50 | Stable, older |
| gemini-2.5-pro | $1.25/$10 up to 200K; $2.50/$15 above 200K | Legacy stable |

Output includes thinking. Batch/Flex input/output is half Standard for these models. Gemini 3.x search grounding shares 5,000 free queries/month, then $14/1,000 executed search queries; one request may generate multiple queries. [Official pricing](https://ai.google.dev/gemini-api/docs/pricing).

3.1 Pro Preview, 3.8 Flash and 3.5 Flash-Lite each allow 1,048,576 input and 65,536 output tokens, accept multimodal inputs and produce text. All support grounding and structured output. Pro remains preview; use its ordinary endpoint for script/research work, not the `-customtools` variant optimized for bash/custom-tool selection. [Pro specifications](https://ai.google.dev/gemini-api/docs/models/gemini-3.1-pro-preview), [Flash specifications](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash), [Lite specifications](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite).

Current Interactions thinking defaults/levels: Flash 3.8 defaults medium with low/medium/high (minimal errors); Lite 3.5 defaults minimal with minimal/low/medium/high; Pro 3.1 defaults high with low/medium/high. Lower thinking effort rather than using an artificially tiny output cap: hitting the cap during reasoning can return empty/truncated text while still billing the reasoning. Existing GenerateContent configuration is a distinct API surface and needs its own migration check. [Thinking guide](https://ai.google.dev/gemini-api/docs/thinking).

Existing 2.5 access is limited to prior active users. 3.1 Flash-Lite lists May 7, 2027 shutdown; 3.8 Flash and 3.5 Flash-Lite have no date announced. [Lifecycle schedule](https://ai.google.dev/gemini-api/docs/deprecations).

Inference: Pro is worth including in quality evaluation but introduces preview risk and a high-context surcharge. Stable Flash is a lower-cost writer/researcher candidate. Lite is best tested for ranking, extraction and deduplication before relying on it for premium storytelling.

## Retrieval APIs: search is not scriptwriting

| API | Price unit | Role |
|---|---|---|
| Perplexity Search | $5/1,000 successful POST requests | Raw web results |
| Perplexity Fast Search | $1/1,000 successful POST requests | Lower-latency raw results |
| Tavily basic search, pay-as-you-go | $0.008/request, 1 credit | Ranked search/extracted context |
| Tavily advanced search, pay-as-you-go | $0.016/request, 2 credits | Deeper retrieval |
| Brave Search | $5/1,000 requests | Search results / LLM context |
| Brave Answers | $4/1,000 requests + $5/M input/output tokens | Generated grounded answers |

Sources: [Perplexity pricing](https://docs.perplexity.ai/docs/getting-started/pricing), [Tavily credits](https://docs.tavily.com/documentation/api-credits), [Brave current plans](https://brave.com/search/api/).

Perplexity raw Search adds no model-token charges. Up to five queries in one successful POST count as one billing unit, but each query consumes a rate-limit unit. Invalid/rate-limited/upstream-failed calls are not billed; successful empty results are billed. Agent API tool search is different: standard web search $2.50/1,000 invocations, Fast $1/1,000, fetch URL $0.50/1,000; model tokens are extra. Fast Search is a search type, not the `fast` Agent preset. [Pricing](https://docs.perplexity.ai/docs/getting-started/pricing), [Multi-query semantics](https://docs.perplexity.ai/docs/search/quickstart), [Fast Search](https://docs.perplexity.ai/docs/search/fast-search).

**Do not propose a fresh Sonar integration from old price tables.** Official support for Sonar Chat Completions ended September 27, 2026. Synchronous/streaming requests can continue through gradually rolled-out Agent API reformulation; async Sonar is unsupported. Perplexity directs new projects to Agent API. Current Sonar pricing is consequently not reported as an independent supported-model rate card. [Official Sonar migration notice](https://docs.perplexity.ai/docs/agent-api/migrate-from-sonar/overview).

Tavily grants 1,000 free credits/month; paid plans reduce per-credit price to $0.0075–$0.005, with subscription commitments. Extraction separately costs one/two credits per five successful URLs. `auto_parameters` can select advanced search and double credit use. `include_answer` optionally adds an LLM-generated answer; raw retrieval and a finished script remain different products. [Credits](https://docs.tavily.com/documentation/api-credits), [Search parameters](https://docs.tavily.com/documentation/api-reference/endpoint/search).

Brave Search/Answers include $5 monthly free credits in current plans. Search preserves freedom to choose the writer; Answers includes answer synthesis and token billing. Avoid using historical Brave launch-plan prices. [Current plans](https://brave.com/search/api/).

## Pipeline tradeoffs and evaluation

Inference: collect a reusable evidence packet once per topic (source URL, publish date, retrieval time, supporting passage and verified claim), then feed the identical packet to multiple writers. This separates retrieval relevance/freshness from creative quality and avoids repeatedly paying for equivalent searches during writer comparison. Enforce source authority and deduplication before script generation; generated search summaries are not independent verification.

Candidate matrix: Perplexity Fast/Standard and Brave for discovery; Tavily for richer retrieved context; Sonnet/Opus/Gemini Pro/Flash for controlled writer comparison. Premium models can serve as selective fact/narrative critics, but critique should check the actual cited passages. None of these products independently establishes that a topic is trending—define that with timestamps, source frequency and platform-specific evidence.

Unverified: account availability, retrieval coverage for Indian audiences, freshness/authority precision, generated-script quality, real thinking volume, retries and acceptance rates. No performance claim here substitutes for a same-topic blinded evaluation. Bill components should separately track search requests, tool invocations, extraction credits, uncached/cached input, visible output, hidden reasoning and retries.
