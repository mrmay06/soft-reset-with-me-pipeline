# Clip-Only YouTube Pipeline Redesign

**Date:** 2026-07-31  
**Status:** Approved design, pending implementation plan  
**Channel:** Soft Reset With Me

## 1. Outcome

Rebuild the channel as an automation-first publishing system that produces one Short per day and one original long-form video per week using stock video clips only. The system must remain useful without weekly human input, avoid repetitive or weak footage, preserve an optional thumbnail-prompt email workflow, and build a body of work that is compatible with YouTube monetization review.

The immediate objective is not to claim that monetization is imminent. The channel's current six-month baseline is 66 uploads, 5,702 views, 6 current subscribers, 1,550 engaged views, 37.8% average percentage viewed, and about 10.1 watch hours. The redesign must first demonstrate a meaningful improvement in viewer response and production quality over a controlled 12-16 Short pilot.

## 2. Product principles

1. **Original substance over output volume.** The story, interpretation, narration, sequencing, and resolution must make each video materially different.
2. **Automation may continue without human input.** Weekly direction improves the slate when present but is never a dependency.
3. **Search creates choices; it does not choose.** Clip selection happens only after a candidate pool is evaluated in the context of the complete story.
4. **The whole sequence matters.** Clips are assigned globally so individually acceptable choices do not produce a repetitive or incoherent video.
5. **No silent quality degradation.** When suitable footage cannot be found, the system rewrites the visual plan or skips the video.
6. **Attention must be earned and resolved.** Heightened expressions and situations are allowed, but titles, hooks, thumbnails, and conclusions must remain emotionally honest.
7. **Real audience behavior outranks model opinions.** Automated audits protect quality; they do not decide strategy without performance evidence.

## 3. Scope

### Included

- Clip-only scene generation for Shorts and long-form videos.
- Removal of Pollinations and all automatic replacement image-generation services.
- Optional weekly editorial direction with automatic fallback.
- Weekly slate creation, script selection, and originality checks.
- Global clip search, inspection, assignment, and recent-use memory.
- Footage-derived Shorts poster frames and long-form A/B/C thumbnails.
- Pre-publication thumbnail prompt email for long-form videos.
- Decoupled generation, upload, and scheduled publication.
- Authentication preflight, idempotency, failure deduplication, and a kill switch.
- 48-hour and seven-day analytics feedback.

### Excluded from the first implementation

- Paid stock-footage subscriptions.
- A new automatic image-generation vendor.
- Actor or character identity matching across stock clips.
- Fully unattended public publishing before the pilot passes its quality review.
- Heavy permanent computer-vision indexing of the full stock-video catalog.

## 4. Publishing and generation schedule

The audience timezone remains `America/New_York`; workflows must handle daylight-saving changes without changing the intended local time.

| Event | Schedule |
|---|---|
| Shorts generation starts | Daily at 6:00 AM ET |
| Shorts scheduled publication | Daily at 8:00 PM ET |
| Weekly strategy refresh | Monday at 4:00 AM ET |
| Long-form generation starts | Saturday at 6:00 AM ET |
| Long-form thumbnail package email | As soon as Saturday generation and QA complete |
| Long-form final preflight | Sunday at 9:00 AM ET |
| Long-form scheduled publication | Sunday at 12:00 PM ET |

Generation and publication are separate operations. Successful generation uploads a private video with `publishAt` set to the intended publication time. A generation failure never moves the publishing time by uploading a weaker fallback.

The Sunday Short still publishes at 8:00 PM ET, eight hours after the long-form video.

## 5. Optional weekly direction

Weekly direction is an optional editorial override. When a fresh direction exists, it may provide a central observation, situations, a stance, a resolution, and excluded subjects.

Topic selection follows this precedence:

1. Fresh weekly direction, when present.
2. Unused directions from the topic memory that still pass recency and similarity checks.
3. Performance-supported content pillars and unresolved viewer questions.
4. A new slate generated from the brand bible and recent-topic exclusions.

Missing, malformed, or stale weekly direction is logged but does not alert, fail, or delay the pipeline. The generated slate must pass the same originality and quality gates regardless of its source.

The weekly slate contains seven distinct Short briefs and one separate long-form brief. The long-form video is not a compilation of the seven Shorts.

## 6. Topic and script system

### 6.1 Weekly slate

One weekly model call proposes a broad candidate set. A deterministic filter first removes candidates that are too similar to recent hooks, claims, examples, titles, and endings. A single ranking pass then selects the slate using:

- specificity of the situation;
- originality of the perspective;
- emotional tension;
- strength and usefulness of the resolution;
- visual feasibility with stock footage;
- material difference from recent videos;
- channel and advertiser fit.

The seven Shorts must not all use the same narrative formula. The slate should distribute hidden-pattern reveals, specific-situation reframes, mistakes and consequences, and practical boundaries or actions.

### 6.2 Short structure

Shorts should normally last 30-45 seconds. Duration follows the idea rather than a fixed word target.

1. **0-2 seconds:** recognizable tension or contradiction.
2. **2-10 seconds:** one concrete situation.
3. **10-23 seconds:** escalation or cost.
4. **23-35 seconds:** reframe.
5. **35-45 seconds:** resolution or action.

Every hook creates a clear promise that the ending must satisfy. Exaggeration may intensify the expression of a real emotional experience, but the script cannot fabricate facts, certainty, urgency, or outcomes.

### 6.3 Originality gate

The system stores normalized fingerprints for the hook, central claim, example, resolution, title, and thumbnail copy. A new script is rejected or regenerated when its substantive similarity to recent work exceeds configured limits. Word substitution alone does not establish originality.

## 7. Visual beat plan

The visual director converts the approved script into 8-14 beats for a Short and a proportionate number for long-form. Every beat contains:

```json
{
  "id": 1,
  "dialogue": "exact covered narration",
  "narrative_role": "recognition|situation|tension|reframe|resolution",
  "treatment": "literal|metaphorical",
  "emotion": "specific observable emotional signal",
  "action": "visible action or motion",
  "shot_scale": "wide|medium|close|detail",
  "movement": "desired camera or subject movement",
  "setting": "useful search context",
  "primary_query": "concrete stock query",
  "alternate_queries": ["query two", "query three"],
  "exclude": ["visual contradiction", "unwanted composition"]
}
```

The intended overall mix is approximately 70% metaphorical and 30% literal, but coherence takes priority over enforcing the ratio mechanically.

## 8. Clip-selection architecture

### 8.1 Candidate retrieval

Each beat retrieves 12-20 candidates from approved stock providers. Provider search order is deterministic. Search results are not selected by scene index or random top-N rotation.

Before full downloads, the system stores provider ID, creator, source URL, duration, dimensions, preview image, query, and license/source metadata. Obviously unsuitable aspect ratios, durations, and resolutions are removed locally.

### 8.2 Candidate inspection

One contact sheet per video presents the remaining previews to a multimodal evaluator. It returns structured observations and scores for:

- narration and action alignment;
- emotional accuracy;
- narrative-role fit;
- visible movement;
- composition and crop suitability;
- technical quality;
- safety concerns;
- similarity to other candidates.

The initial weighted score is:

| Dimension | Weight |
|---|---:|
| Narration alignment | 35% |
| Narrative-role fit | 20% |
| Movement and composition | 15% |
| Novelty within the video | 15% |
| Technical quality | 10% |
| Safety and source confidence | 5% |

These weights are configuration, not permanent truth. Performance evidence may change them later.

### 8.3 Global assignment

A deterministic sequence planner assigns clips across the complete story. It applies hard constraints first and diversity penalties second.

Hard constraints:

- no repeated provider video ID;
- no repeated source URL;
- no exact file hash duplicate;
- no perceptually near-identical footage after download;
- no clip that contradicts narration;
- no clip that fails the target crop or resolution;
- no clip used within the configured recent hard-exclusion window.

Soft penalties cover repeated shot scale, setting, composition, emotional pose, creator, color treatment, and semantic cluster. Randomness is allowed only as a reproducible seeded tie-breaker between closely scored candidates.

The first implementation uses greedy assignment plus a bounded repair pass. It does not require a heavy optimization service.

### 8.4 Cross-video clip memory

Every accepted clip is added to a registry containing provider ID, hashes, semantic labels, query, video ID, scene role, and use date. Exact reuse is blocked for 30 days and strongly penalized for 90 days. Both windows are configurable.

### 8.5 Search failure

When no candidate passes:

1. rewrite the query as a concrete action;
2. search the emotional consequence;
3. switch between literal and metaphorical treatment;
4. replan the beat around available strong footage;
5. fail the draft after three bounded search rounds.

There is no generated-image, stock-image, thumbnail-hold, or unrelated-clip fallback.

## 9. Editing

- Narration timing defines the edit.
- Most Short clips last 1.5-3.5 seconds; emotionally important beats may hold longer.
- The opening clip must contain immediate visible motion and remain comprehensible when frozen.
- Captions normally show 2-6 words per phrase and emphasize meaning rather than every syllable.
- Music follows the tension-to-resolution curve and remains below narration.
- Sound effects and transitions are selective.
- Speed changes, zooms, and reframing require a narrative purpose.
- Missing scene media is a render failure, not permission to repeat a thumbnail or hold frame.

## 10. Thumbnail system

### 10.1 Shorts

The Shorts pipeline no longer requests or generates a thumbnail background. It extracts a clean frame from the opening source clip and can locally add the approved opening copy for an internal poster artifact. The first video moment must itself be thumbnail-safe: clear focal point, strong contrast, completed caption state, and no transition frame.

Because normal custom thumbnail upload is not supported for Shorts in the same manner as long-form, publication does not depend on setting `05_thumbnail.png` through the API.

### 10.2 Long-form packaging

The packaging model receives the full script summary, key moments, selected clip metadata, and clean frame candidates. It returns three hypotheses. Each contains:

```json
{
  "id": "A",
  "promise": "what clicking promises",
  "title": "paired title",
  "line1": "2-4 word headline",
  "line2": "optional 2-5 word support",
  "visual_evidence": "specific script moment represented",
  "candidate_scene_ids": [2, 6],
  "composition": "one_frame|two_frame|typography",
  "text_zone": "left|right|center",
  "avoid": ["misleading expression", "visual clutter"],
  "manual_prompt": "optional external image prompt using the concept and reference"
}
```

Copy angle and visual layout are not permanently tied to A, B, or C. The system may choose any appropriate composition, and A is eligible to become primary.

### 10.3 Footage-derived variants

The thumbnail builder samples clean frames from the original assigned clips, not the captioned final render. It checks sharpness, emotional relevance, focal placement, crop quality, and available text space. Cropping preserves aspect ratio and focal content; it never stretches a frame.

Supported automatic constructions are:

- one strong frame with local color and text treatment;
- two related footage frames in a purposeful split;
- local typography on a branded background, without generative imagery.

The renderer uses generated `line1` and `line2` exactly. It must not substitute hardcoded `BEFORE` or `AFTER` labels unless those labels are part of the approved concept.

### 10.4 Primary selection and QA

The primary is selected only after all variants are rendered. A contact sheet is evaluated at full size and simulated mobile size for:

- immediate comprehension;
- title-thumbnail complementarity;
- emotional and visual specificity;
- readability and contrast;
- promise-to-content integrity;
- absence of misleading or unsafe imagery;
- visual difference from recent thumbnails.

If evaluation is unavailable, the fallback is the highest-scoring frame-based variant, not an unconditional B or C.

### 10.5 Email package

After Saturday generation and before Sunday publication, email:

- A/B/C title and thumbnail hypotheses;
- rendered footage-derived PNG variants;
- selected reference-frame contact sheet;
- exact optional manual prompt for each concept;
- a link to the private/scheduled video when available.

No response is required. If the user does nothing, the selected footage-derived primary remains in place and publication continues.

## 11. Monetization safeguards

Licensed footage alone does not make the output original. Each video must demonstrate transformation through original writing, narration, interpretation, story structure, purposeful sequencing, editing, captions, and a distinct resolution.

Channel-level safeguards:

- materially varied stories rather than interchangeable templates;
- no reading or paraphrasing third-party articles as the core value;
- no collection of unrelated clips;
- no deceptive emotional premise or unresolved hook;
- no repetitive distress scenarios without a coherent narrative and useful resolution;
- source and license metadata retained for every clip;
- channel description and video descriptions clearly represent the original editorial format.

## 12. Reliability and operational controls

### 12.1 Kill switch

A repository-level configuration flag disables all scheduled generation and upload jobs. Manual diagnostic workflows remain available. The flag defaults to disabled during implementation and pilot preparation.

### 12.2 Authentication preflight

YouTube credentials are refreshed and verified before expensive generation begins. Auth failure:

- prevents generation and upload;
- sends one alert for the failure episode;
- records the alert state so scheduled retries do not send repeated emails;
- clears the state only after successful authentication.

### 12.3 Idempotency

Every job has a stable key derived from publication date and track. Checkpoints may resume generation, but the uploader checks the job key and stored YouTube ID before creating a video. Re-running a workflow cannot create a duplicate upload.

### 12.4 Bounded retries

Network and model calls use bounded retries with exponential backoff. Content repair receives at most one script repair and three clip-query rounds. Exhaustion saves diagnostics and ends the job cleanly.

## 13. Cost controls

- No automatic image-generation calls.
- Weekly topic proposals and ranking are batched.
- Candidate previews are evaluated in one contact-sheet call per video rather than one model call per candidate.
- Model retries are bounded.
- Full clips are downloaded only after preview filtering.
- Every run logs model, token, TTS, stock API, and processing usage where available.
- A configurable per-video API budget stops optional audit calls before it compromises core generation.

## 14. Learning loop

At 48 hours and seven days, store available metrics.

For Shorts:

- viewed versus swiped away;
- average percentage viewed;
- average view duration;
- engaged views;
- likes, comments, shares, and subscribers per 1,000 views.

For long-form:

- impressions and click-through rate;
- average view duration and percentage viewed;
- watch time per impression where derivable;
- likes, comments, shares, and subscribers per 1,000 views.

The system joins performance to hook type, narrative structure, duration, clip-plan characteristics, thumbnail hypothesis, and publication date. Model audit labels remain diagnostic fields.

No strategy rule is promoted from one outlier. The first strategic review occurs after 12-16 new Shorts and at least two long-form videos. The review compares medians, distributions, and obvious outliers against the previous baseline; it does not promise causal attribution from this small sample.

## 15. Testing

### Unit tests

- weekly-direction precedence and no-input bypass;
- topic/script similarity rejection;
- clip ID, URL, exact-hash, and perceptual-hash deduplication;
- global assignment constraints and deterministic tie-breaking;
- query-rewrite exhaustion;
- aspect-preserving thumbnail crop;
- generated copy rendered without hardcoded substitution;
- auth-alert deduplication and idempotent upload keys;
- DST schedule validation.

### Fixture integration tests

- complete Short run with mocked provider, model, TTS, and YouTube APIs;
- complete long-form run producing A/B/C footage-derived thumbnails and a pre-publication email package;
- no-candidate run that fails without images or unrelated footage;
- expired-auth run that performs no expensive generation and sends one alert;
- retry of a completed job that does not upload twice.

### Visual checks

Golden contact sheets verify 9:16 and 16:9 crops, text safe zones, mobile readability, and split composition. The pilot retains final human review before public publication.

## 16. Rollout

### Phase 1: Safety and removal

- Add the kill switch and authentication preflight.
- Remove automatic image-generation calls and image fallbacks.
- Make missing clips fail explicitly.

### Phase 2: Clip planner

- Add structured visual beats, candidate pools, contact-sheet evaluation, global assignment, and clip memory.
- Produce two private Short drafts.

### Phase 3: Thumbnail rebuild

- Replace arbitrary frame extraction with frame candidates and aspect-preserving crops.
- Render and evaluate long-form A/B/C variants.
- Move the email package before publication.

### Phase 4: Cadence and editorial fallback

- Add optional weekly direction precedence.
- Separate daily generation from scheduled publication.
- Configure daily Shorts and Sunday long-form schedules.

### Phase 5: Controlled pilot and learning

- Publish up to one reviewed Short per day and one reviewed long-form video per week.
- Review after 12-16 Shorts and at least two long-form videos.
- Enable unattended public publishing only if quality, reliability, originality, and viewer-response checks pass.

## 17. Acceptance criteria

The redesign is complete when:

1. No scheduled path calls Pollinations, Gemini image generation, or another image-generation provider.
2. Every video scene uses an approved video clip; no image or thumbnail hold is used as a scene fallback.
3. A repeated provider ID, exact file, or perceptually near-identical clip cannot appear in one video.
4. Recent cross-video clip reuse is blocked or penalized according to configuration.
5. Weekly direction can be absent without failure, alert, or delay.
6. Shorts generation is triggered daily at 6:00 AM ET and schedules publication for 8:00 PM ET; publication time does not depend on GitHub Actions starting the generation job exactly on time.
7. One independently written long-form video is generated Saturday and scheduled for Sunday at 12:00 PM ET.
8. Long-form A/B/C thumbnails use footage or local typography and are selected only after render-time QA.
9. The thumbnail package email is sent before publication and requires no response.
10. Expired YouTube authentication prevents expensive work and produces only one alert per failure episode.
11. Re-running a completed job cannot create a duplicate upload.
12. The 48-hour and seven-day analytics jobs store performance against creative decisions.
13. Automated public publishing remains disabled until the controlled pilot is reviewed.
