# Voice landscape — checked 7 October 2026

## Decision

Shortlist **Gemini 3.8 Flash TTS** as the value-first expressive narrator, **Eleven v4** as the premium comparison, and **Cartesia Sonic 3.6** if built-in timing and a predictable paid voice workflow matter. This is a suitability inference from documented features/prices, not a listening-test verdict. No paid generations were made. Do not switch a working pipeline solely on marketing quality claims: test one intimate relationship script and one five-minute script with the same voice and script across shortlisted providers.

Gemini Flash-Lite is a useful cheaper comparison, but its savings against Flash are less than half a cent per minute at today's introductory rates; emotionally nuanced narration is worth evaluating on Flash first. Polly Neural is the economical mature fallback, not the leading expressive candidate. Deepgram Aura is aimed more at conversational/business speech and is not the first choice for acted relationship storytelling.

## Comparable cost assumptions

USD before tax; one successful take; no subscription under-utilization, transcription, music, mixing, storage, or retries. English at **150 words/minute × 6 characters/word including spaces = 900 characters/minute**. A 30-second Short therefore uses 450 characters and a five-minute video 4,500. Character-priced narration gets cheaper per *audio minute* when slower; audio-token pricing charges actual generated duration. Budget 2× for two full takes.

| Model | Published billing rate | Derived $/minute | 30 seconds | 5 minutes |
|---|---:|---:|---:|---:|
| Gemini 3.8 Flash TTS, through Dec 31 | $0.50/M input text tokens; $9/M output audio tokens | $0.0135 output | $0.00675 | $0.0675 |
| Gemini 3.8 Flash-Lite TTS, through Dec 31 | $0.50/M text; $6/M audio | $0.009 output | $0.0045 | $0.045 |
| Gemini Flash, Jan 1 2027 onward | $1/M text; $18/M audio | $0.027 output | $0.0135 | $0.135 |
| Gemini Lite, Jan 1 onward | $1/M text; $12/M audio | $0.018 output | $0.009 | $0.090 |
| Eleven v4, promo until Oct 12 / regular | $0.022 / $0.08 per 1K characters | $0.0198 / $0.072 | $0.0099 / $0.036 | $0.099 / $0.360 |
| Eleven v4 Turbo, promo / regular | $0.011 / $0.04 per 1K characters | $0.0099 / $0.036 | $0.00495 / $0.018 | $0.0495 / $0.180 |
| Eleven Flash v2.5 | $0.04 per 1K characters | $0.036 | $0.018 | $0.180 |
| Cartesia Pro, fully consumed allocation | $5/100K credits; approximately 1 credit/character | ~$0.045 | ~$0.0225 | ~$0.225 |
| Deepgram Aura-2 / Aura-1 PAYG | $0.030 / $0.015 per 1K characters | $0.027 / $0.0135 | $0.0135 / $0.00675 | $0.135 / $0.0675 |
| Polly Neural / Generative | $16 / $30 per million characters | $0.0144 / $0.027 | $0.0072 / $0.0135 | $0.072 / $0.135 |

Google uses 25 audio tokens/second: 1,500/minute. Estimated text input at 225 tokens/minute adds $0.0001125/minute today, plus direction metadata; actual tokenization/usage should govern billing. Google Batch rates are half Standard for both 3.8 TTS models. These are TTS models, not similarly named general Gemini or Live audio models. [Google pricing](https://ai.google.dev/gemini-api/docs/pricing)

ElevenLabs rates above come from the freshly opened live rate card; an earlier search cache returned obsolete $0.10/$0.05 rates and omitted v4. Do not budget with those. Promo expiry has no verified cutoff timezone. PAYG is advertised; Starter is $6/month, with a temporary first-month $1 offer. [ElevenAPI pricing](https://elevenlabs.io/pricing/api)

Cartesia Startup $49/1.25M credits gives ~$0.03528/minute at full utilization; Scale $299/8M gives ~$0.03364. These are allocation-equivalent rates, not advertised unconditional PAYG prices. Pro's actual invoice remains $5 even if only one Short is made. [Plans](https://www.cartesia.ai/pricing), [credit units](https://docs.cartesia.ai/pricing)

Deepgram also now lists Flux TTS at $0.045/1K characters; its free launch period ended September 12. Do not confuse voice-agent minute rates with pure TTS. [Deepgram pricing](https://deepgram.com/pricing)

Polly Long-Form costs $100/M characters (~$0.09/minute here), so is not a cost-saving alternative to Neural. Speech Marks are a separately billed text request: Neural audio plus Neural marks approximately doubles the text charge. Free-tier eligibility depends on account age; new AWS customers have the newer credit/free-plan scheme as well. [Polly pricing](https://aws.amazon.com/polly/pricing/)

## Expressive delivery, identity, timing, integration

### Gemini 3.8 Flash / Flash-Lite TTS

The current non-preview IDs are `gemini-3.8-flash-tts` and `gemini-3.8-flash-lite-tts`. Flash has 8,192 input and 16,384 output tokens: at 25 audio tokens/second the serving ceiling is approximately 10.9 minutes, comfortably above five minutes. Google describes long-form voice preservation but that is not independently verified here. Named prebuilt/library/designed/replicated voice IDs support repeatable identity. Crucial migration: move delivery directions into `speech_metadata.style`, not spoken transcript. Momentary events use angle-bracket tags such as `<sigh>` and `<short pause>`. Unary output is WAV by default; remove legacy raw-PCM WAV wrapping. [Flash specification and migration](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash-tts), [Lite specification](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash-lite-tts)

Integrate through GenerateContent or Interactions with the current Google SDK schema. No word-timestamp feature was found in the reviewed TTS guide; plan forced alignment separately, and verify current SDK support before copying old examples. [TTS guide](https://ai.google.dev/gemini-api/docs/speech-generation)

### ElevenLabs

`eleven_v4` is the current expressive flagship, not v3. Ten thousand characters fit a five-minute script; v3 has 5,000, Multilingual v2 10,000, Flash v2.5 40,000. Voice choice remains important; stable identity and long-form performance must be heard, not inferred from model naming. [Model inventory](https://elevenlabs.io/docs/overview/models)

V4 uses inline audio tags (`[whispers]`, `[sighs]`, `[pause]`); SSML `<break>` is disabled. Voice libraries, consent-based cloning, dictionaries, context stitching, REST/streaming, Python and TypeScript SDKs are documented. Older clones may need retraining for v4. Official model overview emphasizes Text-to-Dialogue while the v4 product page also demonstrates `textToSpeech.convert(... modelId: 'eleven_v4')`; verify the selected endpoint/model against the account's models list. [V4 guide](https://elevenlabs.io/v4)

The timing endpoint returns audio plus character start/end arrays and normalized alignment. It also supports prior/next text and request IDs for continuity, but model compatibility needs checking rather than assuming all older controls work with v4. A seed is best-effort, not guaranteed determinism. MP3 128kbps is the default; 44.1kHz PCM/WAV needs Pro, 192kbps MP3 Creator. [Timing API](https://elevenlabs.io/docs/api-reference/text-to-speech/convert-with-timestamps)

### Cartesia

Sonic 3.6 is GA. Pin `sonic-3.6-2026-08-27` for unchanging model behavior; `sonic-3.6` floats across stable snapshots and `sonic-preview` is beta. Persistent voice IDs provide a repeatable narrator. [Model/version guide](https://docs.cartesia.ai/build-with-cartesia/tts-models/latest)

Emotion guidance is **beta and English-only**; model interprets the script's emotion by default. Speed/volume are request-specific; professional clones do not support request-time speed adjustment. [Controls](https://docs.cartesia.ai/build-with-cartesia/capability-guides/volume-speed-emotion)

HTTP bytes returns audio only, SSE adds timestamps, and WebSocket adds timestamps plus context continuations for partial transcripts. For finished scripts, start with SSE if captions matter or bytes if external alignment already exists. Python/TypeScript SDKs are available. A definitive current maximum transcript length was not verified; test five-minute requests and retain paragraph chunking as a fallback. [Endpoint comparison](https://docs.cartesia.ai/use-the-api/compare-tts-endpoints), [SDKs](https://docs.cartesia.ai/tools/client-libraries)

### Deepgram and Polly

Aura-1/2 REST requests are limited to 2,000 characters, so five-minute narration requires at least three chunks here. `aura-2-thalia-en` is an example explicit voice/model. REST/streaming and multiple SDKs are documented; normal Aura responses provide audio and metadata, not the alignment arrays seen in ElevenLabs. [Aura quickstart and limits](https://developers.deepgram.com/docs/text-to-speech)

Aura-2 now supports speed 0.7–1.5 and pronunciation, but **not explicit pause control**. Deepgram's expressivity parameter belongs to Flux TTS and is beta, not an Aura-2 emotional-directing capability. [Voice controls](https://developers.deepgram.com/docs/tts-voice-controls), [expressivity](https://developers.deepgram.com/docs/tts-expressivity)

Polly's synchronous request limit is 3,000 billed characters/6,000 total and ten minutes output; five-minute scripts need splitting or an asynchronous task (100,000 billed characters). Select a fixed `VoiceId` and engine. SSML/lexicons and Speech Marks give mature control/timing, but tag support differs by engine and generative marks must not be assumed. Existing AWS SDK integration makes it a practical fallback. [Limits](https://docs.aws.amazon.com/polly/latest/dg/limits.html), [SSML support](https://docs.aws.amazon.com/polly/latest/dg/supportedtags.html)

## Commercial/account caveats

- **Google:** current terms permit professional/business building; Google does not claim generated-content ownership. Paid billing-connected services do not use prompts/output to improve products; unpaid service data may be human-reviewed and used for improvement. Operators must be 18+, use available regions, and comply with output/IP/safety rules. Public use of a finished video is not the same as exposing an API client to minors. No monthly TTS subscription is required by the rate card; quota and any prepaid billing requirement remain account-specific. [Current terms, effective March 23 2026](https://ai.google.dev/terms)
- **ElevenLabs:** free outputs are noncommercial with attribution; paid-plan outputs can be used commercially indefinitely, subject to rights and terms. Beta Services are excluded. Starter is the verified minimal subscription with commercial license; do not assume PAYG top-ups alone grant rights without checking the account agreement. Creator adds professional cloning. [Publishing rights](https://help.elevenlabs.io/hc/en-us/articles/13313564601361-Can-I-publish-the-content-I-generate-on-the-platform), [plans](https://elevenlabs.io/pricing)
- **Cartesia:** Pro ($5/month) explicitly includes a commercial-use license and instant cloning. Free is evaluation/personal-use, not the production commercial plan. Clone only consented voices. [Commercial plan policy](https://www.cartesia.ai/sonic)
- **Polly:** AWS states Polly recordings belong to the customer as between customer and AWS; inputs must be rights-cleared. This supports normal commercial publishing subject to the contract, not a guarantee that all third-party material is safe. No creator subscription is required. [Ownership FAQ](https://aws.amazon.com/polly/faqs/)
- **Deepgram:** PAYG is listed, but a specific output-commercial-rights clause was not verified in this pass. Confirm its agreement before publishing; do not infer legal rights just from API access.

## Azure disposition

The current official price page confirms 0.5M free Neural characters/month and character billing, but rendered paid rates as `$-` placeholders. Therefore **no exact current Azure paid price is asserted**. It also now lists Neural HD/HD Flash and MAI-Voice, so quoting an old universal $16/M rate would be insufficient. Existing Azure users can evaluate prebuilt neural styles/word boundaries, but there is no cost evidence here to add another account ahead of the shortlist. Custom/personal voice is limited-access. [Current Azure pricing](https://azure.microsoft.com/en-us/pricing/details/speech/), [TTS overview](https://learn.microsoft.com/en-gb/azure/ai-services/speech-service/text-to-speech)

## Suggested acceptance test (not performed)

Use 450-character and 4,500-character rights-cleared relationship scripts. Evaluate intimate, warm delivery without exaggerated sadness; punctuation/pauses; pronouncing names; same voice across three separate generations; regenerated middle paragraph continuity; full five-minute voice drift; caption alignment; total actual billed usage and failed/retake calls. Choose by usable-take cost and editorial quality, not first-byte latency, which matters little for offline video production.
