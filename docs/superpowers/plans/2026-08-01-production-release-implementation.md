# Production Release Implementation Plan

1. Extend the Short finished-video audit contract with structured, scene-addressable blocking visual contradictions and validation helpers.
2. Add targeted clip reselection that preserves unaffected scenes, excludes rejected provider IDs and hashes, and records each repair attempt.
3. Add a bounded public-release repair loop in `main.py`: audit, repair affected scenes, rebuild thumbnail/video, rerun creative judge and audit, then fail closed before upload if unresolved.
4. Add focused unit tests for audit validation, public fail-closed behavior, retry limits, and exclusion-aware scene repair.
5. Switch Short and long-form configurations from paused private-test mode to automated scheduled-public mode while retaining YouTube's required private-at-upload status.
6. Update workflow labels and validation to reflect production behavior, then run unit, mock end-to-end, schedule, YAML, and syntax checks.
7. Push the feature branch, fast-forward `main`, push `main`, enable the Short, long-form, and weekly-strategy workflows, and verify GitHub state.
8. Change only YouTube video `wlDNsBmKG7M` to public and verify its status.
9. Dispatch controlled mock checks on `main` so the newly enabled workflows are exercised without producing duplicate live uploads.
