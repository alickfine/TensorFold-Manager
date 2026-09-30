# Selective oMLX-Inspired Manager Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a compact, oMLX-inspired TensorFold Manager with five top-level destinations, genuine service and usage data, a searchable model workspace, and a focused three-region chat.

**Architecture:** Recompose the existing Web views behind a new top navigation and canonical route resolver. Keep the Manager APIs, SQLite documents, resource admission, native bridge, and external-service ownership rules intact; only add view state needed for selection, search, and drawer visibility.

**Tech Stack:** AppKit/WKWebView, vanilla ES modules and CSS, Node `node:test`, Python 3.12 `unittest`, Swift native checks.

**Spec:** `docs/superpowers/specs/2026-09-30-omlx-inspired-manager-redesign-design.md`

## Global Constraints

- Native window: default 1400×960, minimum 1000×700; all five top navigation labels remain visible at the minimum size.
- Main content width: 1360 px maximum except Chat; body text at least 14 px and secondary labels at least 12 px.
- Five canonical routes: `overview`, `models`, `activity`, `settings`, `chat`; legacy hashes keep their relevant subsection and selected model.
- Model row selection, default setting, service lifecycle, and external attachment are distinct actions; external service offers Detach, never Stop.
- Use only observed `/api/state`, `/api/stats`, upstream health, and existing API values; unavailable metrics show “未采集” / “Not collected”.
- Preserve the current authenticated streaming/chat APIs, SQLite conversations, safe Markdown, native language bridge, secret masking, resource gates, and existing App installation.
- No oMLX-only scheduler, cache, heatmap, launch commands, attachment, web search, or tool execution controls.

## File map

- Create `web/workspace-route.js`: canonical hash parsing, including old route redirects.
- Modify `web/index.html`, `web/app.css`, `web/app.js`, `web/i18n-catalog.js`: top frame, navigation and layout state; the existing App controller remains the only API event dispatcher.
- Modify `web/views/overview.js`: service/usage hierarchy and separate running versus launch model presentation.
- Create `web/views/model-workspace.js`; modify `web/views/models.js`, `web/views/downloads.js`: Library/Downloads composition and searchable compact list.
- Modify `web/views/chat.js`: conversation/message/settings geometry without changing message storage or request construction.
- Modify `web/views/activity.js`, `web/views/workspace-settings.js`: local tabs and concise grouped presentation.
- Update focused `tests/*.test.mjs`, then `docs/acceptance.md` and `docs/acceptance.en.md` only with observed results. Backend and native source changes require a concrete failure that the view layer cannot solve.

## Review Focus

1. An attached DeepSeek service while the stored default is Qwen must show DeepSeek as running and Qwen only as a separate launch target (Task 2 test).
2. A model name/path containing HTML metacharacters or very long text must remain escaped and locally scrollable (Task 3 test).
3. Legacy `#downloads`, `#benchmark`, and selected-model links must land on the right tab without starting a model (Task 1 test).
4. A long chat history with a partially edited prompt at 1000×700 must retain the draft and keep Send/Stop visible (Task 4 test plus browser QA).
5. A stopped Manager or temporarily missing metric must preserve history and show an honest disabled/“not collected” state (Tasks 2 and 4 tests).

---

### Task 1: Canonical routes and top frame

**Files:** Create `web/workspace-route.js`; modify `web/index.html`, `web/app.js`, `web/app.css`, `web/i18n-catalog.js`; test `tests/workspace-layout.test.mjs`, `tests/workspace-chrome.test.mjs`.

**Interfaces:** `resolveWorkspaceRoute(hash: string) -> { page: string, query: URLSearchParams }` maps `#downloads` to `models?section=downloads`, old stats/logs/benchmark/settings hashes to their owners, and retains `model` queries. `renderCurrent()` and `navigate()` in `app.js` use the resolver; the existing `data-page` click contract remains.

- [ ] **Step 1: Write failing tests.** Assert five nav buttons in the stated order, a symbolic accessible language button, no side rail/breadcrumb/footer, and resolver outputs for `#downloads`, `#benchmark`, and `#models?model=%2FModels%2FQwen`.
- [ ] **Step 2: Verify red.** Run `node --test tests/workspace-layout.test.mjs tests/workspace-chrome.test.mjs`; expect failures for old six-page navigation and missing resolver.
- [ ] **Step 3: Implement.** Add the resolver, new top frame, active navigation and route-specific data loading; preserve old deep links and update translations. At 1000 px show all labels; below it allow only the nav strip to scroll.
- [ ] **Step 4: Verify green.** Rerun the two focused test files; expect all tests to pass and no legacy-route assertion to be removed without replacement.
- [ ] **Step 5: Commit.** `git add web tests && git commit -m "feat: add compact manager top navigation"`.

### Task 2: Overview service and real usage

**Files:** Modify `web/views/overview.js`, `web/app.js`, `web/app.css`; test `tests/workspace-layout.test.mjs`, `tests/resources-web.test.mjs`.

**Interfaces:** Keep `renderOverview(state) -> string`. Extend `chooseLaunchModel(snapshot, preferredId = '') -> { options, selected }`; `state.launchTarget` retains a user's explicit selection through polling. Running model always comes from `snapshot.engine.model`, never `settings.selected_model`.

- [ ] **Step 1: Write failing tests.** Assert `attached` with running DeepSeek/default Qwen renders DeepSeek as current, Detach without Stop, and a distinct Qwen launch target. Assert explicit target survives a new snapshot; model/time filters remain wired to `/api/stats`; absent memory/footprint displays “未采集”, measured zero displays `0`.
- [ ] **Step 2: Verify red.** Run `node --test tests/workspace-layout.test.mjs tests/resources-web.test.mjs`; expect the new active/target and missing-metric assertions to fail.
- [ ] **Step 3: Implement.** Recompose the service card, compact usage strip, filters and request table; keep advanced diagnostics in a disclosure. Wire launch-target input to `state.launchTarget` without calling any lifecycle API on selection. Preserve existing start/stop/detach confirmations and resource gates.
- [ ] **Step 4: Verify green.** Rerun the focused tests; verify the real `/api/stats` mapping and local table scrolling in a browser at 1000×700.
- [ ] **Step 5: Commit.** `git add web tests && git commit -m "feat: focus overview on service and measured usage"`.

### Task 3: Model workspace and downloads

**Files:** Create `web/views/model-workspace.js`; modify `web/views/models.js`, `web/views/downloads.js`, `web/app.js`, `web/app.css`, `web/i18n-catalog.js`; test `tests/manager-usability-web.test.mjs`, `tests/workspace-layout.test.mjs`, `tests/workspace-models.test.mjs` (new).

**Interfaces:** `renderModelWorkspace(state) -> string` chooses Library or Downloads from `state.routeQuery.get('section')`. `filterModels(models, query) -> model[]` matches normalized name/repo/path without changing the source array. Existing `renderModels(state)` remains the Library body and `renderDownloads(state)` remains the supported-catalog body.

- [ ] **Step 1: Write failing tests.** Assert Library/Downloads tabs, search by name/path, escaped `<model>` text, long paths constrained to the table region, selected configuration on Library, and Downloads showing only supported catalog entries and download jobs.
- [ ] **Step 2: Verify red.** Run `node --test tests/workspace-models.test.mjs tests/manager-usability-web.test.mjs`; expect new tab/search tests to fail.
- [ ] **Step 3: Implement.** Compose both existing views, load catalog/jobs only for Downloads, keep profile/config data on Library, and wire search without replacing focused input. Retain exact action IDs and gates for validate/start/switch/default/config/download.
- [ ] **Step 4: Verify green.** Rerun focused tests and inspect selected-model deep links and 1000 px table overflow in a browser.
- [ ] **Step 5: Commit.** `git add web tests && git commit -m "feat: combine model library and downloads workspace"`.

### Task 4: Focused chat workspace

**Files:** Modify `web/views/chat.js`, `web/app.js`, `web/app.css`, `web/i18n-catalog.js`; test `tests/chat-workspace.test.mjs`, `tests/workspace-chrome.test.mjs`.

**Interfaces:** Keep `renderChat(state) -> string` and the existing `/api/chat/sessions` and streamed request shapes. `state.chat.settingsOpen: null | boolean` controls the right drawer: `null` means open above 1100 px and closed at or below 1100 px, while an explicit boolean is the user's current choice. Hiding the drawer never destroys its form state. Chat model display derives only from the ready/attached engine.

- [ ] **Step 1: Write failing tests.** Assert three named regions on wide layout, accessible open/close drawer controls, no upload/search/tool-execution controls, stopped-engine explanation, existing session/message/stream/retry behavior, and draft preservation on language rerender.
- [ ] **Step 2: Verify red.** Run `node --test tests/chat-workspace.test.mjs tests/workspace-chrome.test.mjs`; expect drawer/layout assertions to fail.
- [ ] **Step 3: Implement.** Move generation controls into a collapsible right drawer, keep sticky composer and safe message rendering, and route Change model to Models without a service request. Keep the current stream/persist/error paths unchanged.
- [ ] **Step 4: Verify green.** Rerun focused tests; in a real browser inspect long history, draft, session switching, stream/cancel/retry, 1000×700 and narrow layouts.
- [ ] **Step 5: Commit.** `git add web tests && git commit -m "feat: give chat a focused three-region layout"`.

### Task 5: Activity, settings, and visual consistency

**Files:** Modify `web/views/activity.js`, `web/views/workspace-settings.js`, `web/app.css`, `web/i18n-catalog.js`; test `tests/workspace-layout.test.mjs`, `tests/i18n-web.test.mjs`.

**Interfaces:** Keep `renderActivity(state) -> string` and `renderWorkspaceSettings(state) -> string`; their existing `section` query values and backend actions remain intact.

- [ ] **Step 1: Write failing tests.** Assert one page title per tab, the existing logs/benchmark and four settings sections, benchmark safety text, effective/pending labels where actual state supplies them, no oMLX-only control names, and minimum font/spacing hooks.
- [ ] **Step 2: Verify red.** Run `node --test tests/workspace-layout.test.mjs tests/i18n-web.test.mjs`; expect presentation assertions to fail.
- [ ] **Step 3: Implement.** Apply the restrained white/neutral visual system, compact pill tabs, 1360 px content cap, readable typography, and grouped status/control pairs. Keep benchmark safety text and the current settings forms and confirmations.
- [ ] **Step 4: Verify green.** Rerun focused tests; visually inspect Chinese/English, keyboard focus, 1400×960 and 1000×700.
- [ ] **Step 5: Commit.** `git add web tests && git commit -m "feat: align activity and settings with compact workspace"`.

### Task 6: Integrated release-candidate acceptance

**Files:** Modify `docs/acceptance.md`, `docs/acceptance.en.md` after evidence exists; touch product code only to fix observed failures, with a focused red/green regression.

**Interfaces:** No new API. The deliverable is a local QA DMG and evidence, not a public Release.

- [ ] **Step 1: Run full checks.** `python3.12 -B -m unittest discover -s tests`; `node --test tests/*.test.mjs`; `swiftc macos/Bootstrap.swift macos/CredentialRequest.swift macos/tests/main.swift -o /tmp/tfm-native-tests && /tmp/tfm-native-tests`. Record counts and failures; repair ordinary failures before continuing.
- [ ] **Step 2: Exercise the browser fixture.** At wide, 1000×700, and narrow viewports, inspect five routes and subsections, both languages, search/config/download display, stats filters, long chat, stream/cancel/failure/retry, and zero console errors. Record fixture behavior separately from model inference.
- [ ] **Step 3: Build and install local QA package.** Use `python3.12 -B scripts/build-app.py --runtime /Users/fanwenbin/.local/share/uv/python/cpython-3.12.9-macos-aarch64-none --uv /Users/fanwenbin/.local/bin/uv --output dist/omlx-ui-qa --version 0.1.0-alpha.4-qa.2`; verify `SHA256SUMS.txt`, strict App/DMG signatures and packaged source bytes; mount read-only, copy to a distinct `/Applications/TensorFold Manager oMLX QA.app`, then unmount. Preserve both existing installed Apps.
- [ ] **Step 4: Verify the installed App and live service.** Inspect 1400×960 and 1000×700 native windows. Record external-service PID/config/health before attachment, attach only if identity and parameters match, send one short real streaming chat request, restart the App to read back the session, and confirm its exit leaves the original service PID healthy. If the live service is unavailable or incompatible, report that real-model gate unverified rather than loading another large model or stopping a user service.
- [ ] **Step 5: Document and review.** Apply the requested `grill-me` audit to the five Review Focus branches, resolving code-answerable questions from evidence and asking the user only about a remaining product decision. Update both acceptance records with exact evidence and limits; run `git diff --check`; commit docs; request a whole-branch review under the selected execution method and resolve findings; push the draft PR branch. Publication, notarization, and replacement of the user's original App remain separate decisions.
