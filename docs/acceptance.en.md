# TensorFold Manager acceptance record

[简体中文](acceptance.md) | **English**

## Verified alpha.1 baseline — 2026-09-29

Developer acceptance was performed on Apple Silicon, macOS 27, with 256 GiB RAM. GitHub CI ran on macOS 14 arm64. User installation feedback is tracked separately.

- 149 Python tests, 38 Web tests and native bootstrap/origin/export/credential/integrity checks passed.
- Official TensorFold v0.3.6.1 and v0.3.6.2 were installed in isolated environments pinned to official commits. Actual CLI and HTTP inference were verified.
- A fixed-revision Gemma download completed with 12 verified files (15,373,588,575 bytes). ModelScope file-tree/config verification was exercised separately.
- The installed App switched Gemma → Qwen → Gemma, verified old process exit before replacement and completed real chat requests. Quitting released its engine processes and port.
- A converted Gemma model returned HTTP 401 without a gateway key and HTTP 200 with a disposable test key. The test key was removed afterwards.
- Two real benchmark requests completed. A reference-answer test returned `2` for `1+1`; this is reference-text agreement, not general model accuracy.
- Gemma was converted from 4-bit/group-64 to 4-bit/group-32 using a two-stage conversion with bfloat16 scales. Source fingerprints were unchanged, intermediate files were cleaned and actual inference succeeded.
- Real engine activation/rollback (.1 → .2 → .1) completed with old process exit and real requests. Fixtures verified recovery and OS lease exclusion across both successful and failed transitions.
- Unsaved form inputs survived polling; cancelled native confirmations performed no stop action.
- The public alpha.1 DMG was downloaded, checksum-verified, mounted read-only, copied, unmounted and launched. Its source matched the tested source. Gemma answered `4` to `2+2`; normal quit released its engine. Strict ad hoc signature validation passed.

[alpha.1 CI](https://github.com/alickfine/TensorFold-Manager/actions/runs/36510596995) / [Release](https://github.com/alickfine/TensorFold-Manager/releases/tag/v0.1.0-alpha.1).

## Resource and service boundaries

The manager samples macOS memory pressure and capacity before loading a model, conservatively budgets weights, KV, concurrency, drafter, cache and workspace, and reserves system capacity. Unknown budgets block startup. RSS is not used as the peak-memory budget.

An OS heavy-task lease covers inference, conversion, switching, activation and recovery. Only the original verified external process can be stopped after confirmation; external service termination is graceful, with no forced pursuit of replacement PIDs. Existing user services were not stopped during acceptance.

## Limitations

- Builds are ad hoc signed, not Apple Developer ID signed or notarized. Signature checks do not establish Gatekeeper approval. Target: macOS 14+, Apple Silicon.
- Initial engine/model installation requires internet access; model weights are not included in the DMG.
- Quantization configuration preflight is not proof of runtime compatibility. Converted weights require a separate compatibility check and real inference verification.
- Upload scope, repository visibility, credentials and content-change rejection were tested with fixtures. No real model was uploaded to Hugging Face and no user provider credentials were changed.
- When ModelScope lacks an immutable repository commit, downloads are described as file-tree snapshots with per-file immutable revisions.
- Anonymous GitHub API rate limiting was observed during dense tests. The App reports errors and does not read `gh` credentials.
- Unsupported oMLX-specific features and image/audio/embedding/ANE capabilities remain unavailable with explicit reasons. No simulated runtime metrics are presented.

## alpha.2 bilingual acceptance — 2026-09-29

- Added Chinese/English project documentation and release notes.
- Fresh checks passed: 149 Python tests, 48 Web tests, nine native bootstrap/origin/export/language checks plus credential-scope and runtime-integrity checks.
- Actual alpha.2 App switched Chinese → English → Chinese. All 17 English renderers are covered by regression tests; navigation, menus and the native confirmation dialog were checked visibly. Cancelling cache cleanup performed no cleanup.
- An unsaved port value (18081) survived language switching without being saved. Existing chat text and an unsent bilingual draft remained unchanged. No new model was loaded.
- After quitting in English, the manager port changed from 63491 to 63975 on restart; both the workspace and native menu stayed English. After switching back, another restart on port 64126 retained Chinese. The App was closed after acceptance.
- Regression tests cover dependent quantization format restoration for different models and English local validation errors; independent review confirmed both fixes.
- Local alpha.2 DMG build and strict App signature verification passed. Signing remains ad hoc, not Apple notarized. Public-package verification will be recorded after release.
