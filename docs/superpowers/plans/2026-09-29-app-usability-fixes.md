# TensorFold Manager App repair plan

> **For agentic workers:** Use superpowers:subagent-driven-development or superpowers:executing-plans. Track checked steps with fresh evidence.

**Goal:** Resolve the user's enumerated usability and functional defects and all evidence-confirmed defects found in the affected flows.

**Architecture:** Keep the existing native WKWebView, local Python manager, pinned TensorFold adapter and OS resource lease. Simplify existing pages and move controls to their correct scope. Two child agents handle independent investigation/review and Web implementation; the coordinator owns backend integration, native checks, packaging and acceptance.

**Tech Stack:** Swift/AppKit/WKWebView; Python stdlib; browser ES modules; unittest and Node tests.

**Spec:** User's 2026-09-29 explicit repair brief in this thread, reflected below. Existing approved lifecycle, privacy and memory constraints apply.

## Global constraints

- Preserve Chinese/English switching.
- Do not stop or replace the user's GLM service on loopback 8089. No second model or quantization job while its OS lease is held.
- Do not read credentials, alter external model weights, or delete user data.
- Publish only to alickfine/TensorFold-Manager; release new immutable DMG/SHA256 only after applicable CI and App acceptance.
- Distinguish real functionality from unavailable telemetry, queued install from activated upgrade, and mocked regression from real model acceptance.

## Review focus

- Unsupported or incomplete checkpoints must not become start candidates via a family/name match or stale CLI evidence.
- Polling must update measurements without resetting active forms, open configuration dialogs or chat generation.
- Scan cancellation/permission errors/links must not read arbitrary sensitive files or falsely report a complete scan.
- Updates must expose job failures, preserve active engine and recover if candidate validation fails.
- Simplification must preserve API authentication, external-service safety and generation cancellation.

## Acceptance checklist and ownership

### Web implementation agent

- [x] Remove the decorative three-light titlebar row; retain actual macOS controls.
- [x] Correct supported local-model candidates using backend evidence.
- [x] Format statistics to at most two decimal places without changing stored precision.
- [x] Refresh live cache telemetry and distinguish process allocator cache from owned snapshots.
- [x] Standardize local model action buttons.
- [x] Download tested catalog models from the verified Hugging Face or domestic mirror source with minimal inputs.
- [x] Open model configuration in a model-library dialog; remove its sidebar entry.
- [x] Remove quantization/upload, reference-answer test and capability-table navigation.
- [x] Separate engine-wide controls from model generation controls.
- [x] Integrate discovery job in server/directories page.
- [x] Combine API endpoint/port settings and API credentials/key controls.
- [x] Expose update job progress/errors and explicit activation state.
- [x] Compact log controls and maximize readable log area.
- [x] Simplify benchmark presets and retain measured results/errors.
- [x] Rebuild chat layout with readable messages, bottom composer, collapsed parameters and working stream/stop.

### Coordinator backend/native

- [x] Add cancellable bounded accessible-disk model discovery with automatic directory registration.
- [x] Reproduce and repair supported-model evidence and update/caching defects identified by the investigator.
- [x] Run targeted failing regressions before behavior fixes, then Python/Web/native gates.
- [x] Review with the investigator and resolve every confirmed blocking issue.
- [x] Actual CI App passed native restart, sealed runtime reuse, long-history composer/expanded parameters, bilingual and scan recovery/registration checks using existing data. No credentials or weights changed.
- [ ] Package and verify the public DMG, complete CI/release workflow, and report unperformed heavy-model tests accurately.

## Execution evidence

Initial isolated branch: codex/app-usability-fixes at 1c202a41dc4a13f6f582c8f29049d70e96f1bb7d. Original app-dependent checkout retained at manager-app/TensorFold.

Final local gate: 175 Python / 64 Web tests passed, native tests and sealed-runtime proof passed. Final local alpha.3 DMG built. Full-disk native scan previously failed on EPERM; permission and network metadata ordering fixes have eight regression tests passing. Final real scan rerun pending Mac unlock.

Final review reproduced an event-routing regression caused by main[data-page]. Fixed using data-view and button-only navigation routing; the production dispatch function now has an action-event regression.

Actual CI App scan: 200000 dirs / 5 found / 4 registered / 596 skipped; explicitly partial at directory_limit. Two final downloader presentation defects were repaired and verified by render regressions: unrelated jobs and mirror source labels.
