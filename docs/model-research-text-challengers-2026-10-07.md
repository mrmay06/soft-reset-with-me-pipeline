# Text-model challengers: verified 2026-10-07

Scope: official hosted DeepSeek, Alibaba Cloud Qwen, Mistral and xAI APIs for English relationship scripts, topic ranking and JSON review. Primary documentation was opened, not merely search snippets. No paid model calls, account changes or application changes were performed. Prices are USD per million tokens, paid standard real-time usage, excluding tax; cache rates and promotions are separated. These are documentation findings, not measured creative-writing quality or availability/SLA tests.

## Paid prices and exact relevant model IDs

### DeepSeek direct

| API model | Current served version | Uncached input peak/off-peak | Cached input peak/off-peak | Output peak/off-peak |
| --- | --- | ---: | ---: | ---: |
| `deepseek-flash` | DeepSeek-V4.1-Flash | $0.30 / $0.15 | $0.006 / $0.003 | $1.20 / $0.60 |
| `deepseek-v4-pro` | DeepSeek-V4-Pro-0813 | $1.32 / $0.66 | $0.044 / $0.022 | $3.96 / $1.98 |

Both list 1M context and 384K maximum output. Peak: weekdays 01:00–04:00 and 06:00–10:00 UTC, excluding Chinese public holidays; all other hours are off-peak. In India that is 06:30–09:30 and 11:30–15:30 IST. Old `deepseek-v4-flash` and `deepseek-v4-flash-vision-exp` names route to V4.1-Flash. [Current pricing](https://api-docs.deepseek.com/quick_start/pricing/?helper=penn&method=individual).

V4.1-Flash officially released September 10; V4-Pro reached GA August 13. Crucial discrepancy: the September 10 launch article originally said Pro would route to Flash after September 14, but the current changelog explicitly retains V4-Pro service and billing. Treat the current pricing/changelog as authoritative, not that older retirement announcement. Legacy `deepseek-chat`/`deepseek-reasoner` were scheduled to retire July 24; do not use those historic IDs. [Changelog](https://api-docs.deepseek.com/updates/), [older conflicting announcement](https://api-docs.deepseek.com/news/news260910/).

### Alibaba Cloud hosted Qwen

For predictable comparison below, Singapore/International standard list rates are the baseline. Global-scope rates in other regions differ; those are not interchangeable with Singapore or local regional deployment prices.

| API model | Singapore input | Singapore output | Global-scope input/output | Input tier |
| --- | ---: | ---: | ---: | --- |
| `qwen3.8-max`, `qwen3.8-max-0902` | $2 | $6 | $1.65 / $4.951 | ≤1M |
| `qwen3.8-flash` | $0.15 | $0.47 | $0.113 / $0.382 | ≤1M |
| `qwen3.7-plus-2026-05-26` | $0.40 | $1.60 | $0.276 / $1.101 | ≤256K |
| `qwen3.7-plus-2026-05-26` | $1.20 | $4.80 | $0.826 / $3.301 | >256K–1M |
| `qwen3.7-flash-2026-07-15` | $0.030 | $0.130 | $0.028 / $0.110 | ≤32K |

Qwen3.8 is the newest listed Max/Flash family; Plus currently remains 3.7. Thinking output prices include reasoning plus answer. `qwen3.7-plus` is the moving alias for the dated Plus snapshot and carries temporary discounts; table uses undiscounted dated-model list prices. Higher tiers bill all tokens, not just the excess. Pricing page updated October 6. [Pricing](https://www.alibabacloud.com/help/en/model-studio/model-pricing).

Qwen3.8-Max/Flash and 3.7-Plus are currently documented hybrid thinking models, not preview-only IDs. The checked pages establish availability but do not establish exact release dates/GA labels for every Qwen3.8 ID; do not infer the release date merely from `0902`. [Thinking model list](https://www.alibabacloud.com/help/en/model-studio/deep-thinking).

Caching caution: Qwen3.8-Max/Flash are exceptions to the generic explicit-hit 10% and implicit-hit 20% rules; their exact cache-hit rates are deferred to the console and were not verified publicly. Do not calculate them from generic percentages. For normal eligible older models, explicit creation is typically 125%, explicit hit 10%, implicit creation 100%, implicit hit 20%; minimum 1,024 tokens. Batch and cache discounts do not stack. [Cache pricing rules](https://www.alibabacloud.com/help/en/model-studio/context-cache).

### Mistral direct

| API model | Status | List input | List cached input | List output | Current launch input/cached/output |
| --- | --- | ---: | ---: | ---: | ---: |
| `mistral-large-4` | Public Preview, Oct 6 | $1.36 | $0.14 | $4.18 | $0.68 / $0.07 / $2.09 |
| `mistral-large-2512` | Large 3 GA | $0.50 | $0.05 | $1.50 | — |
| `mistral-small-2603` | Small 4 GA | $0.15 | $0.015 | $0.60 | — |
| `mistral-medium-3-5` | Medium 3.5 | $1.50 | $0.15 | $7.50 | — |

Standard USD pricing is selected, not batch/priority/regional premium. Large 4 launch prices are 50% off for two weeks and should not be the durable budget baseline. [Pricing](https://docs.mistral.ai/inference/pricing), [Oct 6 release and promotion](https://docs.mistral.ai/resources/changelogs).

Large 4 has 1M context and is public preview, not production GA. Its model card/changelog ID is `mistral-large-4`; a reasoning guide uses `mistral-large-4-0`, so use the card ID and verify accepted model IDs before integration. Large 3 is GA from December 2, 2025, with 256K context; Small 4 is GA March 16 with 256K context. [Large 4 card](https://docs.mistral.ai/models/mistral-large-4-0), [Large 3 card](https://docs.mistral.ai/models/mistral-large-3-25-12), [Small 4 card](https://docs.mistral.ai/models/mistral-small-4-0-26-03).

Medium 3.5 is an agentic/coding-oriented alternative, not evidence of superior relationship prose; its output is substantially more expensive than Large 3. Historic `labs-mistral-small-creative` and Magistral models appear in deprecated listings, so do not select them on older creative-writing recommendations. [Medium card](https://docs.mistral.ai/models/mistral-medium-3-5-26-04), [current model/deprecation listing](https://docs.mistral.ai/models).

### xAI direct

| API model | Input | Cached input | Output | Prompt/context condition |
| --- | ---: | ---: | ---: | --- |
| `grok-4.7` | $2 | $0.50 | $6 | <200K prompt; 500K context |
| `grok-4.7` | $4 | $1 | $12 | ≥200K prompt; all tokens use long-context rate |
| `grok-4.3` | $1.25 | $0.20 | $2.50 | <200K prompt; 1M context |
| `grok-4.20-0309-non-reasoning` | $1.25 | $0.20 | $2.50 | <200K prompt; 1M context |

US regional inference adds 10%; priority is 2× standard. Grok4.7 has no listed batch discount; older listed 4.3/4.20 models have 20%. “Grok4.7 Fast” is not a public API model—it is faster infrastructure available only through Cursor/Grok Build. Paid tools add cost; Web Search is $5/1,000 calls. [Pricing](https://docs.x.ai/developers/pricing).

Grok4.7 released September 21 and is the newest general text model recommended in the catalog; it is not labeled preview there. Generic aliases can update; dated IDs are immutable where offered. Do not invent a dated Grok4.7 snapshot. [Release notes](https://docs.x.ai/developers/release-notes), [catalog/alias policy](https://docs.x.ai/developers/models).

## Reasoning, structured output and integration cautions

- DeepSeek supports OpenAI-compatible Chat Completions/Responses. Current Chat API supports `reasoning_effort: none|low|high|max`, default `high`, or `thinking.type: disabled`. Reasoning tokens appear in completion usage, so budget generated tokens rather than visible words. Set explicit output caps: documented defaults are 8K without thinking and 64K with thinking. [Chat reference](https://api-docs.deepseek.com/api/create-chat-completion/).
- DeepSeek JSON mode is `response_format.type=json_object`; prompt must explicitly ask for JSON. It is not the same as schema enforcement. The guide acknowledges occasional empty content; truncation can also invalidate JSON. Validate the pipeline schema and apply bounded repairs/retries. [JSON guide](https://api-docs.deepseek.com/guides/json_mode/).
- Qwen Responses API recommends `reasoning.effort` over the soon-to-be-deprecated `enable_thinking`. Qwen3.8 default is `xhigh`; supported levels `none|low|medium|xhigh` with mappings for other levels. These models do not support `thinking_budget` according to the current reference, despite stale examples elsewhere showing it. Endpoint is workspace- and region-specific, e.g. `https://{WorkspaceId}.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1`; keys are region-specific. [Responses reference](https://www.alibabacloud.com/help/en/model-studio/qwen-api-via-openai-responses).
- Qwen JSON Schema is supported for 3.7 Plus/Flash/Max and 3.8 Max/Flash. JSON object mode alone does not stabilize key names/types. Prefer schema for ranking/review, and independently validate semantics. [Structured outputs](https://www.alibabacloud.com/help/en/model-studio/qwen-structured-output).
- Mistral reasoning `high` adds thinking chunks/token usage; `none` minimizes thinking and returns a plain string. With high effort, `message.content` is a chunk list, so a provider adapter must extract final text rather than blindly treating content as a string. Replay full assistant messages in multi-turn reasoning contexts. [Reasoning guide](https://docs.mistral.ai/studio/conversations/reasoning).
- Mistral offers custom-schema and JSON modes; its docs recommend custom schemas where possible. JSON mode requires explicit JSON instructions. [Structured outputs](https://docs.mistral.ai/studio/conversations/structured-output).
- Grok4.7 reasoning cannot be disabled; low/medium/high are documented, high is default. Release notes additionally mention xhigh while the effort table lists three levels; low is the conservative cheap-trial setting. Reasoning incurs token cost. `stop`, presence/frequency penalties are unsupported for reasoning requests. Responses always includes encrypted reasoning; preserve it for manually managed multi-turn history. [Reasoning](https://docs.x.ai/developers/model-capabilities/text/reasoning), [release notes](https://docs.x.ai/developers/release-notes).
- Grok structured outputs guarantees apply only to its supported JSON Schema subset. Some advanced constraints are best-effort; use application validation. The docs show OpenAI clients targeting `https://api.x.ai/v1`. [Structured-output reference](https://docs.x.ai/developers/model-capabilities/text/structured-outputs).

No comparative uptime claim is established by these pages. Recommended engineering inference: preserve raw completion/usage, reject empty/truncated output, classify 429/5xx separately from validation failures, cap retries and cost, and use a second-provider fallback. Model name migrations and reasoning defaults are more immediately material here than headline context sizes.

## Data handling material to relationship content

- DeepSeek's privacy policy says personal data is processed/stored in China, allows technology/model improvement, and says sensitive personal data should not be provided. The platform terms point to that policy; the checked sources do not establish a blanket paid-API no-training or ZDR guarantee. Do not infer that every API payload is trained on, but do not claim an API exemption either. Use fictional/de-identified stories, not private viewer submissions. [Privacy policy](https://cdn.deepseek.com/policies/en-US/deepseek-privacy-policy.html), [platform terms](https://cdn.deepseek.com/policies/en-US/deepseek-open-platform-terms-of-service.html).
- Alibaba standard prompts/responses retained ≤30 days with law/security exceptions; stateful features retained until deletion. Enterprise ZDR requires account-manager approval, eligible models/workspaces and non-mainland regions; an encrypted transient cache may still persist ≤24h. No model training without separate consent. ZDR does not automatically block unsupported-model calls. [Retention policy](https://www.alibabacloud.com/help/en/model-studio/data-retention-policy). Broader customer-business-data no-improvement-without-consent claim is separately documented. [Data disclosure](https://www.alibabacloud.com/help/en/model-studio/qwen-and-wan-training-data-disclosure).
- Mistral: do not assume paying equals no training. Current help says customers control API training via Admin → Privacy → Anonymous improvement data; Chat/Vibe controls are separate. Check/disable the API toggle before sending confidential scripts. [API training opt-out](https://help.mistral.ai/en/articles/455207-can-i-opt-out-of-my-input-or-output-data-being-used-for-training). ZDR is pay-as-you-go, stateless endpoints only, approval-based; not files/batch/agents/conversations. [ZDR](https://help.mistral.ai/en/articles/347612-can-i-activate-zero-data-retention-zdr). Default hosting EU, optional US endpoint; some features can transfer outside EU. [Storage locations](https://help.mistral.ai/en/articles/347629-where-do-you-store-my-data-or-my-organization-s-data).
- xAI API: no training on inputs/outputs without explicit permission; default encrypted request/response retention 30 days for abuse auditing, automatic deletion afterward. ZDR exists for stricter teams; do not equate it with ordinary default retention. [API security/privacy FAQ](https://docs.x.ai/developers/faq/security).

## Shortlist judgment (inference, not measured writing superiority)

1. **Cheap structured ranking/review trial:** Qwen3.8-Flash, Qwen3.7-Flash dated snapshot, and Mistral Small 4. Compare schema fidelity, false-confidence penalties, latency and cost per accepted result. Older Qwen3.7-Flash is dramatically cheaper for ≤32K requests; newest is not automatically best value.
2. **Economical prose challenger:** Mistral Large 3 is a stable 256K-context option with $1.50/M output. DeepSeek-Flash off-peak is another low-cost candidate, but privacy/moving-version and JSON-empty-output handling merit explicit acceptance gates.
3. **Exploratory newest models:** Mistral Large 4 preview, Qwen3.8-Max and Grok4.7. Large4's sale should not drive durable economics; Max/Grok's $6/M output and reasoning defaults make a blind preference test necessary before adopting for scripts.
4. **Not a writing-quality conclusion:** developer claims about coding, math, agent benchmarks, parameter counts or general intelligence do not demonstrate emotional nuance, conversational English, originality, hook strength or retention. Test identical short and long relationship briefs, score outputs blind, include clichés/manipulative advice/unsupported psychology checks, and compare total billed tokens plus edits/retries per accepted script.

For a reference job with 2,000 uncached input + 1,000 generated output tokens, excluding reasoning expansion, repairs and tools: DeepSeek-Flash $0.00090 off-peak/$0.00180 peak; Mistral Small4 $0.00090; Large3 $0.00250; Large4 $0.00690 list/$0.00345 launch; Singapore Qwen3.8-Flash $0.00077, Qwen3.7-Flash ≤32K $0.00019, Qwen3.7-Plus ≤256K $0.00240, Qwen3.8-Max $0.01000; Grok4.7 short-context $0.01000. These are arithmetic illustrations, not script-cost predictions.
