# TensorFold Manager Workspace Simplification

## Intent and scope

The Manager should let a local operator see whether inference is ready, choose and configure a model, manage downloads, chat, and diagnose failures without navigating through separate display and configuration pages. Preserve existing engine, security, update, and data boundaries. This iteration changes the shipped App, not the old `prototype/` directory.

## Navigation and page content

Six top-level routes: Overview, Models, Downloads, Chat, Activity, Settings. Old hashes redirect to their new owner and retain a relevant section where possible.

- Overview combines runtime status and statistics. The first screen shows service state and controls, active model, usable memory/pressure, request count and input/output token totals. One compact usage section holds time/model filters and a concise recent-request table. Advanced telemetry and external service switching remain available behind disclosure controls, with their safety text intact. Do not show zero for uncollected metrics.
- Models places the model list and selected model's generation settings, advanced options, and profiles on the same route. Selection does not start or switch the engine. Saving a configuration retains the existing pending-restart semantics.
- Downloads keeps catalog and jobs together.
- Chat is described below.
- Activity has Logs and Benchmark sections, with one local tab control rather than two top-level pages. Backend task states remain visible at their relevant operation.
- Settings has four grouped sections: Runtime and directories, Storage and cache, API and keys, Versions and updates. Display and configuration for each topic appear together. Existing controls and backend gates remain intact.

The left sidebar bottom shows service status and App version only; no instance identifier. Remove the header last-updated text, refresh control, and task count. Keep automatic polling and show a concise connection error only when it fails. Language switching uses one symbolic button with an accessible label and title naming the target language; the preference and native bridge remain unchanged. Remove redundant refresh buttons from pages while retaining operations such as model rescan and explicit filtered queries.

Tables size columns according to their content. Short numeric/status/action columns do not consume equal fractions of the page; long model paths, errors, and request metadata wrap or are available in details. On narrow windows, a table may scroll inside its own container without growing the whole page. Controls remain usable at the shipped App window size and at a narrower viewport.

## Chat experience and persistence

Chat uses a conversation list, a central message stream, and a sticky composer. Search and rename operate on local conversations. New chat creates a new conversation rather than clearing a prior one. Conversation selection never starts generation or changes the loaded model. Generation options live in a collapsible side panel or drawer. Show separate user and assistant roles, safe Markdown with code blocks and copy actions, streaming/cancelled/failed status, per-turn metrics, and collapsed reasoning and tool-call details. Tool calls are explicitly display-only and never executed by the App. A failed last turn can be retried without duplicating the user message. Keep Enter to send, Shift+Enter for newline, and IME safety. Follow the stream only when the user is near its bottom.

Migrate the existing single `chat/default` document to the first conversation exactly once, within the private SQLite store. Keep the original record for recovery. A conversation has a generated ID, title, timestamps, and validated messages; list payloads omit full messages. The active conversation ID may be stored as UI preference, but server persistence is authoritative for content. Saving, renaming, and switching while a stream is active must not overwrite another conversation. No automatic deletion or pruning is introduced. Preserve the existing history endpoint for compatibility during migration, with the new UI using conversation endpoints.

## Data flow and failures

The six routes compose existing view modules and backend API calls. Existing security checks, model compatibility gates, resource admission, job controls, and update transactions are not relaxed. New chat endpoints use the same authenticated, same-origin API client and validate IDs, title length, role/content and message count server-side. Rendering escapes untrusted model, chat, and log text before adding allowed Markdown structure. Polling does not overwrite focused form fields, unsent chat text, a manual scroll position, or an active stream. Failed requests retain current content and expose the error; absent metrics remain “未采集” / “Not collected”.

## Acceptance

Use a fresh current-main checkout. Add focused red/green tests for route mapping, data composition, language control, chat migration/isolation/retry, safe rendering, and table layout hooks. Run the full Python and Web suites and native source checks. Exercise all six routes, English/Chinese switching, narrow layout, model inline configuration, conversation creation/rename/search/switch/reload, streaming/stop/failure, and old history recovery in a real browser against a local Manager fixture. Do not treat tests or saved settings as proof of real model inference; report the actual level reached.
