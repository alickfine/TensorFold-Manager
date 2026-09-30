# Manager Workspace Simplification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a six-page, compact bilingual Manager with inline model configuration and persistent multi-conversation chat.

**Architecture:** Recompose existing Web views and routes without changing engine behavior. Add bounded conversation CRUD in the private SQLite store and Manager HTTP API, then wire a richer chat view to it. Preserve legacy chat history for recovery.

**Tech Stack:** Python 3.12 standard library/SQLite, vanilla JavaScript modules, CSS, Node test runner, AppKit/WKWebView.

**Spec:** `docs/superpowers/specs/2026-09-30-manager-workspace-simplification-design.md`

## Global Constraints

- Six top-level routes: Overview, Models, Downloads, Chat, Activity, Settings.
- Keep legacy `chat/default` after one-time migration. No automatic conversation deletion or pruning.
- Tool calls are display-only. All untrusted content is escaped before safe Markdown structure is emitted.
- Existing engine, update, resource, credential, and same-origin security gates remain in place.
- Null metrics stay uncollected; polling preserves focused edits, chat draft and manual scroll position.

## Review Focus

- Existing chat history is nonempty: migration must retain every message and remain idempotent (Task 2).
- Two conversations are saved in alternating order: content and titles must stay isolated (Task 2).
- Stream fails or is cancelled: partial assistant content and status remain, retry avoids user duplication (Task 3).
- English switch occurs during an unsaved edit or chat draft: both survive re-render (Task 4).
- Long paths, errors and multilingual content: no page-level horizontal overflow or HTML execution (Tasks 3, 5).

---

### Task 1: Navigation and composed pages

**Files:** Modify `web/index.html`, `web/app.js`, `web/views/overview.js`, `web/views/models.js`, `web/views/shared.js`; create `web/views/activity.js`, `web/views/workspace-settings.js`; modify or add Web tests.

**Interfaces:** `renderOverview(state)` includes compact usage; `renderModels(state)` accepts a selected model route query; `renderActivity(state)` composes logs/benchmark; `renderSettings(state)` composes runtime, storage, API and updates. `loadPageData(page)` fetches all necessary sections. Old hashes map to canonical pages.

- [ ] Write failing Web tests for exactly six navigation routes, old-route mapping, overview usage and same-page model configuration.
- [ ] Run focused tests and confirm the expected failures.
- [ ] Compose pages and route/data loading; retain backend action contracts and focused-edit preservation.
- [ ] Run focused and full Web tests, then commit.

### Task 2: Conversation persistence and API

**Files:** Modify `manager/tfmanager/state.py`, `manager/tfmanager/server.py`; add `tests/test_chat_sessions.py`; adjust backend tests if the API contract changes.

**Interfaces:** Store methods `chat_sessions()`, `chat_session(id)`, `chat_session_create(data)`, `chat_session_update(id,data)`; authenticated `/api/chat/sessions` collection and `/api/chat/sessions/{id}` item endpoints. The first list/read migrates legacy history once without deleting the legacy document.

- [ ] Write failing tests for migration, idempotency, isolation, validation and authenticated API routing.
- [ ] Run focused tests and confirm expected failures.
- [ ] Implement bounded SQLite-backed sessions and server routes; keep legacy history endpoint.
- [ ] Run focused and full Python tests, then commit.

### Task 3: Conversation UI and message rendering

**Files:** Modify `web/app.js`, `web/views/chat.js`, `web/chat-options.js`, `web/app.css`, `web/i18n-catalog.js`; add `web/chat-markdown.js` and focused Web tests.

**Interfaces:** Chat page consumes list/detail endpoints from Task 2. `renderChat(state)` exposes a session list, message stream, composer and collapsible settings. `renderChatMarkdown(text)` emits escaped, safe HTML. Retry constructs a request from the last failed turn without adding another user message.

- [ ] Write failing tests for session actions, safe Markdown, stream status and retry semantics.
- [ ] Run focused tests and confirm expected failures.
- [ ] Implement UI/API wiring, scoped updates during stream, auto-scroll rule and bilingual copy.
- [ ] Run focused and full Web tests, then commit.

### Task 4: Chrome, localization and responsive density

**Files:** Modify `web/index.html`, `web/app.js`, `web/i18n.js`, `web/app.css`, `web/i18n-catalog.js`; modify Web i18n/usability tests.

**Interfaces:** One language toggle button calls `applyLanguage`; `updateChrome()` writes status/version only. Tables use intrinsic width and local overflow while long values wrap.

- [ ] Write failing tests for removed chrome items, language toggle/accessibility, preservation of drafts and table hooks.
- [ ] Run focused tests and confirm expected failures.
- [ ] Implement chrome, responsive CSS and table layout.
- [ ] Run focused and full Web tests, then commit.

### Task 5: Integrated acceptance

**Files:** Update `README.md`, `README.en.md`, `docs/acceptance.md`, `docs/acceptance.en.md` only with observed results; add integration tests only for actual gaps.

**Interfaces:** No new runtime interface.

- [ ] Run complete Python, Web and native checks with fresh output.
- [ ] Exercise six routes, bilingual and narrow layout, inline model configuration and multi-session chat against a local Manager fixture in a real browser.
- [ ] Inspect diff for old routes, XSS/data-loss risks and misleading capability claims; fix and rerun relevant checks.
- [ ] Record actual evidence and limitations, then commit.
