# TensorFold Manager: selective oMLX-inspired redesign

Date: 2026-09-30
Status: awaiting written-spec review
Reference observed locally: `http://127.0.0.1:8000/admin/dashboard` and its model, settings, activity, and chat views.

## Intent

Make the installed TensorFold Manager feel as direct and coherent as the useful parts of the local oMLX console while retaining TensorFold's actual service, model, and security semantics. The operator should see what is running, understand real usage, select and configure a model, manage a download, and chat without navigating through redundant pages. The App must remain usable when inference is stopped or only attached to an external same-user service.

This is a selective reproduction of information architecture and interaction patterns, not an oMLX feature port or a copy of its branding. Do not display a control, metric, or claimed capability merely because oMLX shows it.

## Reference decisions

| Observed oMLX pattern | TensorFold decision | Reason |
|---|---|---|
| Compact centered top navigation | Use five top-level destinations: Overview, Models, Activity, Settings, Chat | Frees width and reduces the existing side rail's visual weight |
| Model table with search, type, size, and row actions | Use a compact searchable model list with actual compatibility and lifecycle state; show selected configuration alongside or below it | TensorFold already validates models and stores per-model settings |
| Download and model settings under model-related navigation | Put Library and Downloads in the Models destination; keep selected model configuration on the Library view | Keeps a model and its configuration together |
| Separate chat workspace with conversations, centered messages, and settings rail | Use the same spatial roles with TensorFold's persistent sessions and a collapsible generation drawer | Improves focus without inventing attachments or agent execution |
| Service statistics and usage history on one dashboard | Put service state, genuine usage totals, filters, and a concise recent-request table on Overview | Answers the operator's first questions without a long telemetry page |
| Dense global settings with live/restart indicators | Keep the four existing TensorFold settings groups and mark pending restart accurately | Preserves configuration meaning without reproducing oMLX-only toggles |
| Customizable blocks, heatmap, app launch commands, oMLX cache, web search, and document attachment | Omit | No necessary TensorFold workflow or supported backend capability in this iteration |

## Navigation and frame

The App uses a fixed-height top bar with TensorFold name and App version at left, compact navigation in the center, and a service-state indicator plus the existing symbolic 文/A language switch at right. Main content is centered and capped at 1360 pixels on wide displays, but the Chat workspace may use the available width. Remove the redundant breadcrumb, footer, and side rail. Keep keyboard focus indicators and full accessible names on icon-only controls. No external fonts, icon libraries, or network assets are required.

Top-level routes are `overview`, `models`, `activity`, `settings`, and `chat`. Existing `downloads` and older hash routes redirect to the appropriate destination and subsection. Models has Library and Downloads tabs; Activity has Logs and Benchmark tabs; Settings retains Runtime, Storage, API, and Updates tabs. Deep links preserve the subsection and selected model where applicable. Merely changing a route never starts inference, selects a new default model, or alters settings.

At the shipped minimum window size of 1000×700, all five navigation labels remain visible without horizontal page overflow. Below 1000 pixels in browser QA, only the navigation strip may scroll horizontally; the whole page may not. Tables scroll inside their containers. The chat composer remains visible above the bottom edge. All controls remain large enough to click comfortably; oMLX's very small labels are not reproduced.

## Visual language

Use the calm density observed in oMLX: a white or near-white canvas, dark text, thin neutral borders, restrained rounded cards, compact pill navigation, and a table whose row height allows a quick scan. Retain TensorFold identity and use its blue only for the active location and primary action; status colors indicate actual ready, warning, or failure states. Prefer one clear page title and a short explanatory line over nested card titles and repeated labels. Avoid decorative grid backgrounds, draggable dashboard furniture, oversized metric tiles, and duplicated action bars. Body text remains at least 14 pixels, with secondary labels at least 12 pixels at normal display scaling. The first screen should reveal the service state and usage without scrolling at 1400×960, while at 1000×700 the primary service action and active model remain above the fold.

## Overview

The first screen shows one service card with state (`stopped`, `starting`, `ready`, `attached`, or failure), current running model, source of control (Manager-owned or external attachment), and the corresponding lifecycle action. A separate explicit launch target may be selected when stopped. The launch target must not be visually confused with the running model; polling cannot reset a user's in-progress selection. External attachment exposes Detach, not Stop. Existing confirmation and resource-admission gates remain in force.

The same screen shows available/reclaimable memory and macOS pressure, then a compact usage strip: request count, input tokens, output tokens, and measured engine footprint when available. Data comes from the existing `/api/state` and `/api/stats` responses. Model and time filters apply to usage history, and a concise request table sits below. Unavailable values read “未采集” / “Not collected”; zero is shown only when zero was actually measured. Advanced process identity, capacity diagnostics, and external-service actions stay under a clearly labeled disclosure, not in the first scan path. No oMLX-only cache-efficiency, token-speed, or heatmap widget is implied by the design.

## Models and downloads

Library has a search field and a compact list. Each row shows name, actual installed size, TensorFold compatibility/startability, and current/default status. The selected row reveals the existing per-model generation options and profiles on the same view. Dense diagnostic paths, probe reasons, and secondary actions are available in an expanded detail region. Existing CLI compatibility checks remain distinct from a real load or successful inference.

Starting, switching, attaching, setting a default, and saving configuration are separate actions. Selecting a row or editing a field does not load weights. Pending-restart configuration remains labeled until the running service reflects it. External attached services remain read-only. The Downloads tab retains the supported catalog, source/revision provenance, and resumable job state; it does not introduce generic downloads from arbitrary model IDs.

## Chat

On wide windows, Chat uses three regions: a narrow local conversation list with new/search/rename, a message stream, and a collapsible right generation-settings drawer. At the minimum App width, the drawer closes by default; at narrower widths, conversations and settings become accessible drawers or stacked sections without pushing the composer off-screen. The model chip names the currently served model. “Change model” goes to the Models lifecycle view; choosing a chip must not silently load or switch a model.

Reuse the current authenticated streaming API and SQLite conversations. Preserve migrated `chat/default` history, exact message text, failed/cancelled states, retry without duplicate user turns, safe Markdown/code copy, collapsed reasoning and tool-call detail, and non-executing tool display. Keep the composer fixed within the chat workspace, with Enter to send, Shift+Enter for a newline, and IME safety. Polling and language changes preserve drafts, scroll position, the selected conversation, and unsaved parameter edits. After a Manager restart, prior messages stay visible even if an external inference service requires explicit reattachment; this state must be explained in the composer.

No document upload, web search, autonomous tool execution, or agent workflow is claimed. Those require backend design and separate authorization.

## Activity and settings

Activity keeps the existing log viewer and benchmark workflows under two local tabs. Log filters, source, timestamps, and errors remain legible. Benchmarks keep their existing safety checks and clearly state any effect on running models before execution. The visual redesign must not inherit oMLX's behavior of unloading other models.

Settings retains Runtime and directories, Storage and cache, API and keys, and Versions and updates. Within each section, status and the control that changes it appear together. Indicate which values require restart and which are already effective. Preserve the current local-origin token boundary, secret masking, update transaction, cache ownership checks, and service identity gates. Do not bring oMLX's global scheduler, memory-tier, MCP, or client-launch settings into TensorFold without actual backend support.

## Data flow and implementation boundaries

This iteration primarily changes `web/index.html`, `web/app.css`, route composition in `web/app.js`, and the relevant `web/views/*` modules. Existing Manager API contracts and persistent data schemas remain intact unless a concrete UI need cannot be met without a narrowly specified backend change. Reuse translation catalogs and the native language bridge. Treat all model names, logs, messages, and external-service descriptions as untrusted text; retain escaping and safe Markdown handling. Do not read or alter oMLX data, keys, settings, or service state.

Before editing, establish the current branch/worktree baseline and preserve existing uncommitted work. The QA App and original installed App are separate; installing a new QA package must not replace the original App without explicit release approval.

## Verification and acceptance

1. Focused tests cover route redirects, visible information hierarchy, active versus launch model distinction, table/search behavior, language accessibility, chat drawer/composer behavior, and preservation of drafts and session data. Run the full Python/Web and native-source checks after changes.
2. In a real browser against an isolated local Manager fixture, inspect all five destinations and their subsections in Chinese and English at wide, 1000×700, and narrow viewports. Exercise non-destructive model selection/configuration, usage filters, download display, chat sessions, stream/cancel/failure/retry, and absence of console errors. Check that unsupported oMLX controls are absent.
3. Build an ad hoc signed local QA DMG from the final code, verify checksum and bundle/source identity, mount read-only, install side by side, and inspect the actual App at its shipped minimum and default window sizes. Reuse a compatible existing external TensorFold service only after identity/configuration checks; send one real streamed model request through the packaged Chat UI. Verify conversation persistence after App restart and that quitting Manager leaves the external service healthy.
4. Report the evidence separately: static/UI tests, fixture-browser behavior, installed-App behavior, and real-model inference. Do not turn a passing fixture, health endpoint, or single prompt into claims of general model quality, long-context support, or benchmark performance. Publication, notarization, and replacing the existing App are separate decisions.

## Grill-me review: resolved branches and remaining review gate

- **Which oMLX content is necessary?** Service readiness, model identity, actual usage, a compact model list, and chat workspace support the Manager's daily decisions. oMLX-only operational controls are excluded.
- **Where does each number come from?** The existing TensorFold state/stats endpoints or actual upstream health sampling. Missing values remain uncollected.
- **Could a visual model selector unexpectedly load a 100+ GB model?** No. Selection, default setting, lifecycle, and external attachment remain explicit separate actions with the current gates.
- **Can the layout work at 1000×700 and with long chat history?** The top bar has a compact mode, tables scroll locally, chat drawers collapse, and the composer receives explicit viewport acceptance.
- **Could the redesign erase conversations or weaken security?** The current SQLite and API contracts, origin/token checks, and service ownership rules are retained; migration is not repeated.

The user approved the in-chat selective-reproduction direction. This written specification remains subject to user review before an implementation plan is created.
