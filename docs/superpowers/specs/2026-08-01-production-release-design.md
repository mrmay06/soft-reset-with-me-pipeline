# Production Release Design

Date: 2026-08-01

## Objective

Move the clip-only relationship-video pipeline into unattended production while protecting the public channel from narration/visual contradictions. Merge the completed redesign into `main`, schedule future uploads for public release, publish the approved test Short, and enable only the GitHub Actions required for the operating cadence.

## Release cadence

- Generate one Short every day at 6:00 AM America/New_York.
- Publish the Short at 8:00 PM America/New_York.
- Generate one long-form video every Saturday at 6:00 AM America/New_York.
- Publish the long-form video every Sunday at 12:00 PM America/New_York.
- Run weekly direction generation on Monday, but never block production when no human direction is supplied.

YouTube scheduled publishing will use `privacyStatus=private` together with `publishAt`, as required by the YouTube API. This represents a scheduled public release, not a permanently private upload.

## Visual contradiction repair gate

The finished-video audit becomes a release gate for public production. Its structured output must identify blocking contradictions and associate each contradiction with the affected scene.

A blocking contradiction is a high-confidence mismatch that reverses or materially undermines the narration, such as cheerful celebration during narration about withholding good news. A merely generic but emotionally compatible clip is scored lower but does not automatically block release.

When blocking scenes are reported:

1. Preserve the current clip identifier in the scene exclusion list.
2. Reselect only the affected scene clips from remaining candidates.
3. Reassemble the video and rerun the finished-video audit.
4. Retry at most twice.
5. If the contradiction remains, stop before upload and fail the workflow with a clear diagnostic.

The repair loop is bounded to control API usage and runtime. Private test mode may retain advisory behavior, but scheduled public production fails closed when the audit cannot run or cannot produce valid structured results.

## Workflow and configuration state

Production configuration will enable automation and public scheduling for both formats. The Short, long-form, and weekly-direction workflows will be enabled after `main` contains their workflow definitions. Workflow timezone guards remain responsible for preventing duplicate runs from the paired daylight-saving cron entries.

The optional weekly direction input must continue to fall back to the automated topic and strategy system. It must not become a prerequisite for either content pipeline.

## Existing test asset

The existing successful test Short, YouTube ID `wlDNsBmKG7M`, will be changed from private to public as explicitly approved. No other historical private test assets are included in this release.

## Verification and rollout

Before merging:

- Run focused tests for structured audit parsing, contradiction gating, scene exclusion, bounded repair, and fail-closed public behavior.
- Run the existing relevant test suite.
- Validate workflow YAML and production configuration.

After merging:

- Push `main` to the existing `mrmay06/soft-reset-with-me-pipeline` repository.
- Enable the three required workflows.
- Confirm their enabled state and next-schedule configuration.
- Make the approved test Short public and verify its YouTube status.
- Run controlled GitHub production checks without creating duplicate immediate releases.

## Rollback

The pre-release feature branch and Git history preserve the original implementation. Operational rollback consists of disabling the three workflows and setting both `automation_enabled` and `public_release_enabled` back to `false`. Public videos already released are not automatically made private during rollback.
