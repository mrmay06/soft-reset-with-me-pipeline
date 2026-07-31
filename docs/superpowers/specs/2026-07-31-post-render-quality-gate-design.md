# Post-Render Quality Gate Design

Date: 2026-07-31

## Goal

Repair the defects exposed by the private Short and long-form tests without running another full provider-backed generation. Music must continue through the final visual hold, script evaluation must inspect the content it claims to score, thumbnail copy must render exactly as approved, and automated publishing must use a validated rendered thumbnail rather than an upstream text-only guess.

This work does not resume schedules, make uploads public, change stock-footage providers, or replace the current voice and writing models.

## Confirmed defects

### Long-form audio tail

The long-form assembler mixes and fades music to the narration duration. The finalizer then pads that mixed track with silence while extending the last video frame for two seconds. The result is an abrupt transition from finished narration and music into a silent held frame.

The Short assembler already mixes against its complete planned visual duration and is not affected by this exact defect.

### Incomplete creative-judge context

The judge asks for a CTA score but receives only the hook, title, a description excerpt, high-level counts, and text descriptions of thumbnail concepts. It does not receive the script CTA fields. A low CTA score therefore cannot be trusted.

### Brittle hook validation

The deterministic Short validator treats a small keyword list as evidence of an effective hook. A concrete contradiction such as `You shrink yourself down so other people feel big enough` can be marked weak because it does not contain one of those literal terms.

### Silent thumbnail-copy mutation

The renderer clips thumbnail headlines to 18 characters before drawing them. `YOU'RE TOO COMFORTABLE` consequently becomes `YOU'RE TOO`, materially changing the approved concept. The metadata agent can also select a primary variant before any rendered thumbnail exists, so composition failures cannot affect the upload choice.

### One-sided Short framing

The generated Short protects the viewer by declaring the other person's capacity or `low ceiling` to be the problem. This is emotionally sharp but weakens nuance, credibility, and advertiser-safe brand trust. The writing system needs a guard against superiority framing, not merely a guard against overt blame.

## Approaches considered

### A. Minimal wiring repair

Extend the music mix, include CTA fields in the judge prompt, and default the primary thumbnail to B. This is inexpensive but leaves text mutation, visual mismatch, and blame-heavy scripts able to pass. Rejected as insufficient.

### B. Deterministic post-render gate

Fix final-duration audio mixing, verify exact rendered copy, provide the judge all relevant script fields, replace literal hook keywords with structural checks, and select only among rendered thumbnails that pass deterministic validation. This is reliable and inexpensive. Selected as the baseline.

### C. Unbounded multimodal creative selection

Ask a vision model to make every thumbnail and editorial decision. This can catch semantic composition problems but adds cost and model variance, and it cannot replace deterministic text integrity. Rejected as the sole gate. A bounded rendered-thumbnail visual ranking may be added later behind a fallback, but production correctness must not depend on it in this repair.

## Audio behavior

The long-form assembler calculates `final_duration = voice_duration + end_hold_sec` before mixing.

- The narration stream is padded and trimmed to the final duration.
- The music stream loops and is trimmed to the final duration.
- Music fades to zero over the final 1.5 seconds by default, ending on the final frame.
- The narration is not stretched or distorted.
- The finalizer receives an audio stream already matching the video and must not create a second unintended silence gap.
- Render metadata records voice duration, planned final duration, music fade duration, and audio duration so this can be asserted.

## Script and hook safeguards

The Short prompt and validation add an explicit fairness rule: do not make the viewer inherently deeper, wiser, or more capable while diagnosing the other person as shallow, avoidant, incapable, or beneath them. When responsibility is uncertain, frame the issue as fit, behavior, communication, capacity in context, or an unanswered possibility.

The hook validator becomes structural. A hook can pass when it presents at least one of:

- a concrete observable behavior;
- a specific lived situation;
- a clear contradiction between action and emotional purpose;
- a precise self-recognition statement with a consequence.

Known abstract, diagnostic, unsupported-guarantee, and generic-affirmation patterns remain failures. The validator must not require any single vocabulary list to pass a hook.

## Creative-judge contract

The judge receives the relevant complete narrative fields within bounded prompt limits:

- Short: hook, tension, insight, loopback, engagement question, and save/like CTA;
- long-form: chapter narration, counterpoint, engagement question, and subscribe CTA;
- metadata: title, description excerpt, all thumbnail concepts, and declared primary variant;
- render: duration and visual-asset summary.

The prompt tells the judge to score only supplied evidence and never report a missing CTA when a CTA field is populated. The judge remains advisory for creative quality; deterministic failures continue to control hard correctness gates.

## Thumbnail integrity and selection

The renderer does not truncate approved copy. It normalizes unsupported characters, respects word-count limits upstream, then fits and wraps the full line within the safe area. If full copy cannot fit above the configured minimum type size, the variant fails clearly instead of silently changing its meaning.

After A/B/C are rendered, each variant is validated for:

- exact normalized line-one and line-two copy;
- expected dimensions and upload size;
- non-empty safe-zone text bounds;
- source-frame availability and declared structure.

The primary selector runs after validation. For this deterministic repair, it prefers a valid B emotional/face-text variant, then a valid C, then A. It records the reason and never selects an invalid render. This removes the current C upload failure while retaining all three files for later human or multimodal review.

The uploader continues to consume `07_longform_thumbnail.png`, which is copied only from the post-render selected winner.

## Targeted testing

Automated tests cover:

- long-form music duration equals final video duration and the fade begins inside the ending hold;
- existing Short behavior remains unchanged;
- judge prompts contain each populated CTA field and long-form chapter text;
- concrete contradiction hooks pass without a keyword match;
- abstract or blame/superiority hooks fail or produce a repair signal;
- long thumbnail copy is preserved rather than clipped;
- invalid thumbnail variants cannot become primary;
- valid B is preferred by the deterministic post-render selector.

The existing provider-backed artifacts are then reused:

1. remux the existing long-form narration, music, captions, and concatenated video with the corrected ending;
2. regenerate only A/B/C thumbnails from existing footage and metadata;
3. run local probes and judges without uploading a new video;
4. keep all automations paused and all existing uploads private.

No new voice generation, stock search, script generation, or YouTube upload is required for this repair test.

## Success criteria

- Music remains audible after narration ends and reaches silence exactly at the final video frame.
- The final audio and video durations match within normal codec tolerance.
- The judge sees and correctly acknowledges CTA fields.
- The tested Short's hook is no longer rejected solely for missing listed keywords.
- Superiority/blame framing is detected for repair.
- Every thumbnail contains the full approved copy.
- The broken C thumbnail is not automatically selected.
- All targeted tests pass while schedules remain paused and uploads remain private.
