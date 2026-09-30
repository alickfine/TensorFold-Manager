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
- Local alpha.2 DMG build and strict App signature verification passed. Signing remains ad hoc, not Apple notarized. Public-package verification is recorded below.

- [alpha.2 CI](https://github.com/alickfine/TensorFold-Manager/actions/runs/36513259885) completed successfully: 149 Python / 48 Web tests, native checks, build and publication.
- The DMG downloaded from the [alpha.2 Release](https://github.com/alickfine/TensorFold-Manager/releases/tag/v0.1.0-alpha.2) matched its checksum file and GitHub digest: `a080d5a66ade9c6c2b22371d94a23d0dfb2a19e7c9c762957ce20fd359ae5789`.
- The public App was mounted read-only, copied, unmounted and launched. Manager/Web source bytes and version matched the tested source; strict signature checks passed. Chinese/English page and native-menu switching worked. The preference was restored to Chinese; normal quit removed the manager process and closed port 65085.

## alpha.3 repair acceptance (2026-09-29)

Two independent agents handled investigation/review and Web fixes; the coordinator integrated backend/native changes.

- Python 3.12.9: 175 tests passed. Web: 64 passed. Native bootstrap/language, full manifest integrity and directory write protection checks passed.
- The actual native App opened existing data with 12 retained navigation items and no duplicate three-light header. Library buttons were uniform; model settings opened in a dialog. Unsaved Temperature=0.73 survived Chinese-to-English switching and was discarded on close.
- Installed Gemma/Qwen/GLM compatibility was checked using the actual TensorFold CLI and MLX reader, without loading weights. Detection does not prove inference or weight provenance.
- Existing installer logs and chat history remained visible. Generation is explicitly disabled while stopped; old conversations are not new-release inference evidence.
- Actual startup reproduced an old runtime with unmanifested pyc files. A new runtime namespace copies clean App resources and removes directory write bits while preserving old runtimes/engines and strict integrity checking. The source of the prior mutation is unproven; it is not attributed to uv.
- Actual uv venv creation, offline local fixture wheel installation/import and plain imports without -B left every manifest entry, mode and link unchanged, with no additional files. This is runtime isolation evidence, not a TensorFold upgrade acceptance.
- Real HTTP fixture-engine regressions cover candidate completion, pre-stop rejection, original model/running-parameter recovery, concurrent pending edits and recovery to a stopped state without unwanted model loads.
- Regressions cover first-install access, actual gateway binding/pending settings, partial scan limits, duplicate chat submissions/error recovery and inherited model settings.

Full large-model downloads, new-release GLM loading and a live GLM upgrade were not performed in this pass. The build is ad hoc signed, without Developer ID signing or Apple notarization. Previous heavy-model acceptance does not prove these new-release flows.

- [Branch CI](https://github.com/alickfine/TensorFold-Manager/actions/runs/36578444335) passed. Its downloaded DMG matched SHA256SUMS; strict signature, version and manager/Web byte equality checks passed.
- Actual CI App discovery completed: 200000 directories, five model locations, four registered directories and 596 skipped entries. The directory_limit and partial result are displayed explicitly; this is not a complete whole-disk scan. Permission errors no longer abort it. Actual CLI detection completed and the library expanded from five to nine entries.
- The long-history chat composer stays visible with generation parameters collapsed or expanded; the parameter panel scrolls independently. The actual scan button dispatched its job; page navigation worked.
- Actual uv offline fixture-wheel installation, plain imports without -B and full manifest verification preserved the CI App runtime. Normal quit/relaunch succeeded and retained Chinese, without starting an inference service.
- Final QA additionally found unrelated jobs in the downloader and an incorrect mirror label; both were repaired and passed render regressions; final package checks continue. alpha.3 publication is not yet claimed.

## Six-page workspace and multi-session chat source acceptance (2026-09-30)

- The current source has six top-level entries: Overview, Model Library, Model Downloader, Chat, Activity and Settings. Usage is part of Overview; model configuration and profiles share the library page; logs and benchmarks share Activity; the remaining configuration is grouped by task under Settings.
- The sidebar bottom shows only the App version. Instance ID, last-updated time, refresh button and task count were removed. A symbolic 文/A button switches languages. Tables size columns to content and scroll within their own containers.
- SQLite conversations migrate legacy `chat/default` history once while retaining the original document. The chat UI includes session creation, search and rename, streaming messages, safe Markdown, code copying, failure details, stop and retry. Reasoning and tool calls are inspectable in disclosures; the App does not execute or replay tool calls as executable history.
- Fresh checks passed: 187 Python tests, 81 Web tests, nine native bootstrap/origin/export/language checks, plus credential and runtime integrity checks.
- A real browser against a local Manager and small fixture engine exercised all six entries, Settings/Activity tabs and their actions, session creation and rename, streaming, failure and repeated retry, history after reopening, draft preservation across languages, 375/600/800-pixel layouts and local table scrolling. The browser console had zero errors. The fixture wrote only to a temporary directory.
- A multiline first message saved with a normalized title while SQLite retained the exact line break in its body. Delaying session A's save while switching to and sending in session B left each session's messages and revision isolated.
- At an 800×700 browser viewport, the chat composer and send button remained near the viewport bottom before and after a response. This is fixture-browser layout evidence, not an installed App screenshot.

At the source-and-fixture acceptance stage above, the fixture engine returned `ok`; the current DMG had not yet been built or installed, and no real TensorFold inference had been exercised. The subsequent installed-App acceptance is recorded below.

## Six-page workspace DMG and real inference acceptance (2026-09-30)

- Built a local `0.1.0-alpha.4-qa.1` QA DMG from branch commit `cd82dde`. SHA-256: `e800044fdd3777e923d7f7ac229c5bbccfe6bb37e2acf6ad2e1bebbb00868b85`. The checksum manifest, strict App and DMG signature checks passed. The image was mounted read-only; its Web and Manager files matched the source byte for byte.
- Copied the App from the DMG to `/Applications/TensorFold Manager UI QA.app` and launched it. The existing `/Applications/TensorFold Manager.app` (alpha.3) was preserved. The App and sidecar process paths pointed to the QA installation, and the UI showed its QA version. The disk image was unmounted.
- Selected `DeepSeek-V4-Flash-4bit` in the installed App and attached to the existing, same-user TensorFold inference service with matching parameters. The Manager showed `attached` and the running model path `/Users/fanwenbin/.omlx/models/DeepSeek-V4-Flash-4bit`; external PID 2718 did not change. This reused already-loaded real weights, without starting or downloading another model.
- Created a separate conversation in the installed App and sent “请只回复：UIQA_REAL_OK”. The UI first showed `generating`, then returned `UIQA_REAL_OK` with 2.15 seconds browser elapsed time and 6 tokens. Overview request count rose from 1 to 2, input tokens from 54 to 67, and output tokens from 1 to 7. This is a real local model request through the packaged App, not a fixture response. One prompt does not establish general answer quality.
- On normal QA App quit, its App and sidecar processes exited while external PID 2718 remained. `/health` returned `ok` with `warming:false`. Relaunch retained the conversation, question, answer, and request count of 2. The external service is not automatically reattached after Manager restart; the operator selects and attaches it again. The service remained healthy.
- This local QA DMG was installed for acceptance only and has not been published as a public Release. It is ad hoc signed, without Apple Developer ID signing or notarization.

## Five-destination oMLX-inspired QA acceptance (2026-09-30)

- The new top navigation has Overview, Models, Activity, Settings and Chat. Downloads belongs to Models; usage belongs to Overview; model selection and configuration share a page. Legacy `#downloads`, `#benchmark` and model-specific links retain their relevant subsection without starting a service. The earlier six-destination acceptance above remains a historical record of that version.
- Fresh checks passed: Python 187/187, Web 96/96, native 9/9, and `git diff --check`. A real browser against a local fixture covered 1400×960, 1000×700 and 375×700, all destinations and tabs, the 7-day stats request, both languages and draft preservation, with zero console errors or warnings. With 80 chat messages at 1000×700, the composer and Send/Stop remained in view. Fixture streaming, error, retry and cancel passed; its response is not real model inference.
- The requested `grill-me` audit resolved five review branches from tests and observed behavior: attached DeepSeek remains distinct from default Qwen and offers Detach; HTML metacharacters are escaped and long paths scroll locally; legacy links retain context without launching; long chat and language changes preserve the draft; a stopped service retains history, disables generation and labels missing metrics “Not collected” while preserving measured zero. No additional product decision remains for these branches.
- Independent whole-branch review found a first-send race, lost drafts during streaming, path search/render mismatch, and undersized text. Each was fixed with a failing then passing regression. In the browser, rapid submissions created one session; path search survived language switching and model selection; a new draft and unsaved Temperature survived completion, cancel and failure. Computed chat body and secondary text sizes were 14px and 12px.
- The final local `0.1.0-alpha.4-qa.3` DMG was built from commit `34adbe9`; SHA-256 `80b68288b963c2e6d5add25375205c7d0cb8ac7c0b0afa2e11184db34de8dd5d`. Its checksum manifest, strict App/DMG signatures and byte comparison of 18 manager and 39 Web source files passed. It was mounted read-only, copied to `/Applications/TensorFold Manager oMLX QA.app`, and unmounted. The original and prior QA installations remain.
- The installed App visibly showed the five destinations, version and symbolic language button at its native 1400×960 window. Request times were readable (`2026/9/30 19:40:05`), and a restart retained the earlier real DeepSeek conversation and counters. A confirmed native 1000×700 screenshot was not obtained; that layout is supported by browser evidence and the native minimum-size code check only.
- No TensorFold service was listening on `127.0.0.1:18080` during this final package check. No new large model was loaded and oMLX was not stopped. The earlier QA package's persisted `UIQA_REAL_OK` answer does not count as inference by this DMG, so the **new DMG real-model gate remains unverified**. This is a local ad hoc-signed QA build, neither notarized nor published.
