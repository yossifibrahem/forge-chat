# Agent Guide for Lumen AI Chat

This file is the working guide for agents modifying this repository. It reflects the current post-cleanup codebase, including server-side API provider settings, typed internal streaming events, cached conversation indexing, and the persistent cross-turn MCP session pool.

## Project at a glance

Lumen is a self-hosted Flask chat UI for OpenAI-compatible chat-completions APIs. It supports:

- Streaming responses over Server-Sent Events (SSE)
- OpenAI-compatible API base/model/temperature settings from the browser UI
- Server-side API key storage through `app_config.py` and `/api/settings`
- Local filesystem conversation persistence under `~/.lumen/`
- Per-conversation workspace directories mounted as `/workspace`
- Docker sandbox containers per conversation
- MCP server configuration through `mcp.json` and the UI
- MCP tool discovery, namespaced model-facing tool names, tool-call execution, approval/deny UI, and tool-result rendering
- Persistent cross-turn MCP stdio session reuse through `McpSessionPool`
- Image uploads stored by content hash
- Regular file uploads stored in the conversation workspace
- Markdown, code highlighting, KaTeX, voice input, theming, and conversation search

The app is intentionally lightweight: no database, no frontend framework, no bundler/build step, and plain browser ES modules served directly by Flask.

## Repository map

```text
.
├── app.py                         # Flask app factory, startup checks, CORS, shutdown cleanup
├── app_config.py                  # Server-side API provider config and API key storage
├── routes.py                      # HTTP API routes and SSE stream endpoint
├── chat_turn_service.py           # Long-running chat turn orchestration
├── streaming.py                   # Typed OpenAI streaming event generator + SSE helpers
├── mcp_service.py                 # MCP config, tool discovery, invocation, persistent cross-turn session pool
├── mcp_adapters.py                # Host/container MCP launch helpers
├── container_service.py           # Docker container lifecycle and command wrapping
├── workspace_service.py           # Workspace listing, reading, upload, download path safety
├── store.py                       # Filesystem persistence for conversations/images + cached index
├── Dockerfile.sandbox             # Required per-chat sandbox image
├── gunicorn.conf.py               # Single-worker/threaded production default
├── requirements.txt               # Flask, CORS, OpenAI SDK, MCP SDK
├── requirements-dev.txt           # Adds pytest and pytest-mock on top of requirements.txt
├── pytest.ini                     # Test discovery config
├── README.md                      # User-facing project description and setup docs
├── agent.md                       # This agent/developer guide
├── templates/index.html           # Full app shell and modal markup
├── tests/
│   ├── conftest.py                # Shared fixtures and filesystem isolation
│   ├── test_app_config.py         # Server-side API config tests
│   ├── test_store.py              # Image storage, conversation CRUD, cached index tests
│   ├── test_workspace_service.py  # Path safety, listing, reading, upload, _unique_path
│   ├── test_chat_turn_service.py  # Turn orchestration helpers, approvals, title generation
│   ├── test_streaming.py          # Typed stream event ordering, cancellation, tool accumulation
│   ├── test_mcp_service.py        # Config cache, run_async, McpSessionPool behavior
│   ├── test_mcp_adapters.py       # Docker process option and volume extraction helpers
│   ├── test_container_service.py  # Container naming, lifecycle helpers, idle reaping
│   └── test_routes.py             # Flask HTTP integration tests via test client
└── static/
    ├── css/                       # CSS entrypoint and module files
    └── js/
        ├── app.js                 # Browser bootstrapping and event binding
        ├── api.js                 # Thin fetch wrapper
        ├── chat.js                # Chat orchestration exports / compatibility surface
        ├── chat_attachments.js    # Image/file attachment lifecycle helpers
        ├── chat_edit.js           # Edit, resend, regenerate helpers
        ├── chat_payloads.js       # API message/payload construction
        ├── chat_send.js           # Send flow and stream start/handling
        ├── stream_consumer.js     # SSE response reader and error response helpers
        ├── conversations.js       # Conversation CRUD and sidebar list
        ├── customization.js       # Theme/font/accent/customization state
        ├── dom.js                 # Shared DOM lookup helpers
        ├── file_panel.js          # Workspace browser/preview/download UI
        ├── format.js              # Formatting helpers
        ├── icons.js               # SVG icon strings
        ├── markdown.js            # Markdown rendering and safe file-link enhancement
        ├── mcp.js                 # MCP config UI, tool loading, enable/auto-approve toggles
        ├── app_policy.js          # App-level system prompt guidance
        ├── mcp_tool_ui.js         # Generic tool-result rendering helpers
        ├── renderer.js            # Chat/message/thinking/tool strip rendering
        ├── settings.js            # API/model/chat settings UI
        ├── state.js               # Shared browser state and localStorage keys
        ├── storage.js             # localStorage wrapper
        ├── ui.js                  # General UI helpers
        ├── voice.js               # Web Speech API integration
        └── tool_adapters/         # Tool-specific display/rendering adapters
```

Root-level duplicate test files should not exist. In particular, keep `test_mcp_service.py` only under `tests/`.

## How to run locally

Install dependencies:

```bash
pip install -r requirements-dev.txt
```

Run the test suite:

```bash
pytest
```

Run the Flask app:

```bash
python app.py
```

Open:

```text
http://localhost:8080
```

Build the required sandbox image before using MCP tools:

```bash
docker build -f Dockerfile.sandbox -t lumen-sandbox .
```

Production-ish entrypoint:

```bash
gunicorn -c gunicorn.conf.py "app:create_app()"
```

`gunicorn.conf.py` intentionally uses one worker and multiple threads because active stream state and cancellation events are currently process-local.

## Persistence and runtime locations

The backend stores user data outside the repo by default:

```text
~/.lumen/
├── config.json       # server-side API provider config, unless LUMEN_CONFIG_FILE overrides it
├── mcp.json          # MCP server config, unless LUMEN_MCP_CONFIG_FILE overrides it
├── conversations/    # one JSON file per conversation
├── containers/       # one workspace directory per conversation
└── images/           # uploaded images keyed by SHA-256 hash
```

Important environment variables:

```text
OPENAI_API_KEY              overrides saved API key
OPENAI_BASE_URL             overrides saved API base URL
OPENAI_API_BASE             fallback alias for API base URL
LUMEN_CONFIG_FILE           path to server-side config JSON
LUMEN_CONFIG_CACHE_TTL      default: 5 seconds
LUMEN_MCP_CONFIG_FILE       path to MCP config JSON; default ~/.lumen/mcp.json
LUMEN_SANDBOX_IMAGE         default: lumen-sandbox
LUMEN_CONTAINERS_ROOT       default: ~/.lumen/containers
LUMEN_CONTAINER_MEMORY      default: 512m
LUMEN_CONTAINER_CPUS        default: 1
LUMEN_CONTAINER_NETWORK     default: bridge
LUMEN_CONTAINER_PREFIX      default: lumen-chat-
LUMEN_CONTAINER_IDLE_TIMEOUT default: 600 seconds; 0 disables idle reaping
LUMEN_MAX_CONTENT_LENGTH    default: 60 MiB Flask request body cap
LUMEN_CORS_ORIGINS          default: http://localhost:8080,http://127.0.0.1:8080
LUMEN_MAX_FILE_PREVIEW_BYTES default: 512 KiB
LUMEN_MAX_FILE_LIST_ENTRIES  default: 500
LUMEN_MAX_UPLOAD_BYTES       default: 50 MiB
LUMEN_MCP_CONFIG_CACHE_TTL   default: 5 seconds
```

Browser `localStorage` keys such as `lumen_settings`, `lumen_models`, and `lumen_mcp_server_settings` are unrelated to the uppercase environment variables.

## Backend architecture

### `app.py`

- Creates the Flask app.
- Sets `MAX_CONTENT_LENGTH` from `LUMEN_MAX_CONTENT_LENGTH` to cap request body size globally.
- Configures CORS from `LUMEN_CORS_ORIGINS`, defaulting to localhost origins.
- Verifies Docker and the sandbox image at startup.
- Registers the single blueprint from `routes.py`.
- Calls stale container cleanup at startup.
- Registers shutdown cleanup through `atexit` and `SIGTERM`, guarded against double execution.

### `app_config.py`

Server-side provider config lives here. Sensitive API keys should not be stored in browser `localStorage` or sent in `/api/chat/stream` request bodies.

Key behavior:

- Config defaults to `~/.lumen/config.json`.
- `LUMEN_CONFIG_FILE` can override the config path.
- `OPENAI_API_KEY`, `OPENAI_BASE_URL`, and `OPENAI_API_BASE` override saved config at load time.
- `public_config()` returns only safe browser metadata: `api_base` and `has_api_key`.
- `save_config()` persists allowed keys atomically with a temp-file replace.
- Blank API key updates intentionally keep the existing saved key.

### `routes.py`

Route handlers are intentionally thin. They parse request bodies, call service modules, and return JSON/streaming responses.

Main route groups:

- `/` renders `templates/index.html`.
- `/api/conversations` CRUDs conversation JSON through `store.py`.
- `/api/conversations/<conv_id>/workspace` returns the host workspace path.
- `/api/conversations/<conv_id>/container` returns Docker status metadata.
- `/api/mcp/config` loads/saves `mcp.json`.
- `/api/mcp/tools` discovers MCP tools from configured servers.
- `/api/mcp/call` directly invokes one MCP tool.
- `/api/conversations/<conv_id>/files` lists or uploads workspace files.
- `/api/conversations/<conv_id>/files/content` previews text files.
- `/api/conversations/<conv_id>/files/download` downloads workspace files.
- `/api/images` stores image uploads.
- `/api/chat/stream` starts or reattaches to a streaming chat turn.
- `/api/chat/cancel` cancels an active stream.
- `/api/chat/approve` approves or denies a pending MCP tool call.
- `/api/settings` reads/writes server-side API provider config.
- `/api/models` proxies model-list fetching through the server-side OpenAI-compatible config.

Conversation update is whitelisted. `PUT /api/conversations/<conv_id>` should only accept allowed user-facing fields such as `title` and `system_prompt`; do not reintroduce `data.update(_body())`.

Streaming state is stored in module-level dictionaries:

- `_cancel_events`: `stream_id -> threading.Event`
- `_active_streams`: `stream_id -> replayable stream state`

Because these are in-memory, active stream reattach works only within the same Python process. Multiple worker processes are unsafe for cancellation/reattach until stream state moves to shared storage or a broker.

### `chat_turn_service.py`

This is the core backend orchestration layer for a chat turn.

Key responsibilities:

- Create an OpenAI client from `app_config.load_config()`.
- Stream model chunks through `streaming.stream_chat_completion()`.
- Accumulate text and `reasoning_content`.
- Persist partial assistant output using `TurnRecorder`.
- Detect streamed tool calls.
- Pre-mount host volumes for all enabled MCP servers at turn start by calling `mcp_service.collect_all_extra_volumes()` and `container_service.ensure_container()`.
- Request frontend approval for tools unless the server is set to auto-approve.
- Invoke MCP tools through a persistent `mcp_service.McpSessionPool` (one pool per conversation, kept alive across turns) when tools are available.
- Append tool messages back into the API message history.
- Loop until the model completes without more tool calls.
- Emit final `assistant_done` and optional generated `title` events.

`TurnRecorder` saves conversation checkpoints during long streams and removes `active_stream_id` on finalize.

SSE event types produced/forwarded include:

```text
reasoning
done
text
tool_start
tool_calls
tool_approval_required
tool_running
tool_result
assistant_done
title
error
```

The model-facing messages and UI-facing `displayLog` are related but not identical. Be careful to update both when changing turn logic.

### `streaming.py`

- Wraps OpenAI streaming chat completions.
- Yields typed Python dictionaries internally, not already-serialized SSE strings.
- Merges incremental tool-call deltas by tool-call index.
- Emits `tool_start` as soon as a tool name appears.
- Emits `tool_calls` when the finish reason is `tool_calls`.
- Supports cancellation by closing the OpenAI stream when the cancellation event is set.
- Provides `sse_event(payload)` for HTTP-boundary serialization.
- Provides `make_streaming_response(generator)` for Flask streaming responses.

Do not restore the old internal SSE encode/decode round-trip. Keep stream internals dict-based and serialize only at the HTTP boundary.

### `mcp_service.py`

- Persists MCP config at `~/.lumen/mcp.json` by default; `LUMEN_MCP_CONFIG_FILE` can override the path.
- Caches MCP config for a short TTL to avoid reading `mcp.json` on every tool call.
- Validates only the top-level config shape: `{"mcpServers": {...}}`.
- Connects to each MCP server through stdio.
- Uses `mcp_adapters.apply_workspace_process_options()` to configure the container runtime for each MCP server.
- `collect_all_extra_volumes()` gathers the union of host mount volumes for a list of server names.
- `fetch_tools()` returns OpenAI-tool-like metadata for the frontend.
- `invoke_tool()` remains available for one-off calls.
- MCP config cache reads/writes are protected by a lock because Flask can run threaded.
- `run_async()` bridges async MCP calls into Flask sync route/service code.

#### `McpSessionPool`

`McpSessionPool` reuses MCP stdio sessions across all tool calls for a conversation — the pool is kept alive between turns and only closed when the conversation's container is stopped or removed.

Important implementation detail: AnyIO-backed MCP context managers must be exited from the same asyncio Task that entered them. The pool uses one dedicated worker coroutine for the whole turn so session open, tool invocation, `ClientSession.__aexit__`, and `stdio_client.__aexit__` happen in the same Task. Do not replace this with `run_coroutine_threadsafe()` per call unless you also preserve same-task cleanup semantics.

The pool is used by `chat_turn_service.run_persistent_chat_turn()` and closed in the `finally` block.

### `mcp_adapters.py`

All MCP servers run inside the per-conversation Docker container. There is no host runtime fallback for normal chat execution.

Container runtime:

- Requires `conv_id` for real conversation execution; otherwise raises `ContainerConversationRequired` unless discovery behavior applies.
- Ensures the per-conversation Docker container is running.
- Mounts the conversation workspace as `/workspace`.
- Wraps the MCP command with `docker exec -i --workdir /workspace ...`.
- Injects explicit MCP env vars into the container with `docker exec --env`.
- Extracts absolute script/project paths from server args and mounts nearby project roots read-only.

### MCP discovery container

`/api/mcp/tools` can run without an open conversation. When `conv_id` is missing, it uses the reusable `mcp-discovery` container, lists MCP tools, then stops it for idle reuse.

Keep this behavior intact:

- Stale-container cleanup must skip `mcp-discovery`.
- Real chat tool discovery/calls must still use the actual conversation `conv_id`.
- Remote MCP servers may log harmless shutdown noise when discovery stops the container after tools load.

### `container_service.py`

- Creates and reuses Docker containers named with `LUMEN_CONTAINER_PREFIX` plus a sanitized conversation id.
- One host workspace directory is created per conversation under `LUMEN_CONTAINERS_ROOT`.
- Containers are started with `/workspace` mounted to the host workspace.
- The sandbox drops all capabilities, then adds back a minimal set: `CHOWN`, `DAC_OVERRIDE`, `SETUID`, `SETGID`.
- Provides stale container cleanup, container removal, workspace deletion, status inspection, and `docker exec` command wrapping.
- Uses per-conversation locks to avoid concurrent create/start races.
- The idle reaper stops conversation containers that have been idle beyond `LUMEN_CONTAINER_IDLE_TIMEOUT`; `0` disables idle reaping.
- The MCP discovery container is excluded from stale cleanup/reaping.

### `workspace_service.py`

Handles safe file operations inside the conversation workspace.

Important safety behaviors:

- Only `/workspace` paths are accepted for absolute-style paths.
- Parent traversal with `..` is rejected.
- Resolved paths must stay inside the workspace root.
- Upload filenames are sanitized.
- Duplicate upload names get `-1`, `-2`, etc.
- Uploads are stored under `/workspace/uploads/`.
- Preview is limited to text-like files under `LUMEN_MAX_FILE_PREVIEW_BYTES`.

### `store.py`

- Conversations are JSON files under `~/.lumen/conversations`.
- Images are stored under `~/.lumen/images` using SHA-256 filenames.
- `working_directory(conv_id)` delegates to `mcp_adapters.conversation_working_directory()`, which delegates to `container_service`.
- Writes use temp-file replace.
- `list_all()` uses a cached in-memory conversation summary index.
- The cached index is protected by `_index_lock`, a `threading.RLock()`, because threaded Flask/Gunicorn can mutate the index concurrently.

When editing the index, keep lock coverage around `_rebuild_index()`, `_update_index_for()`, `_remove_index_entry()`, and `list_all()` read/copy access.

## Frontend architecture

The frontend is plain browser ES modules. `templates/index.html` defines the DOM shell and imports `static/js/app.js` with `type="module"`.

### Shared state

`static/js/state.js` exports a single mutable `state` object. Major fields include:

```js
state.convId
state.messages
state.displayLog
state.mcpTools
state.mcpServerSettings
state.isStreaming
state.streamId
state.apiBase
state.model
state.systemPrompt
state.temperature
state.autoGenerateTitles
state.enterToSend
state.autoScrollStreaming
state.serverHasApiKey
```

The API key should not be persisted in `state` or localStorage. The settings UI may accept a key and send it to `/api/settings`, but it should clear the input after saving and only retain `serverHasApiKey` metadata in browser state.

### App startup: `app.js`

- Loads server/client settings, customization, cached MCP tools, and conversation list.
- Binds sidebar, modal, settings, input, keyboard, model picker, MCP, voice, attachments, and file-panel events.
- Initializes icons.
- Opens the last active conversation if available.

Because chat behavior is now split across several modules, keep imports explicit and verify browser module exports after refactors. `chat.js` intentionally re-exports some helpers for compatibility, but new code should usually import from the owning module.

### Chat modules

The previous oversized `chat.js` has been decomposed.

- `chat.js`: compatibility surface and high-level chat exports.
- `chat_send.js`: send flow, stream start, stream event handling, cancellation.
- `chat_payloads.js`: builds model/API messages and chat request payloads.
- `chat_attachments.js`: pending image/file attachment processing and helpers such as `hasPendingAttachments`.
- `chat_edit.js`: edit, resend, regenerate, and related mapping helpers.
- `stream_consumer.js`: reads SSE responses and forwards raw event strings to a callback; also reads response error bodies.

`stream_consumer.readSSEStream(response, onEvent)` requires a callback. It should fail loudly if called incorrectly rather than silently swallowing stream data.

### Chat flow

When the user sends a message:

1. Pending attachments finish processing.
2. A conversation is created if none exists.
3. Images are uploaded to `/api/images` and stored as `image_ref` blocks in local message history.
4. Regular files are uploaded to `/api/conversations/<conv_id>/files` and their `/workspace/uploads/...` paths are attached to the user message metadata.
5. The user message is appended to `state.messages` and `state.displayLog`.
6. The conversation is persisted before model streaming starts.
7. `buildApiMessages()` constructs the API payload:
   - Prepends system prompt and MCP policy prompt.
   - Adds file attachment context into user content.
   - Expands stored image refs to base64 `image_url` blocks for OpenAI-compatible vision input.
8. `/api/chat/stream` is called without an API key in the body.
9. The frontend reads SSE lines and updates the UI incrementally.

### Conversation history model

There are two parallel histories:

- `state.messages`: model/API-facing history.
- `state.displayLog`: UI-facing render log, including messages, thinking blocks, and tool results.

Do not assume they have the same indices. Use helper mapping logic when editing/regenerating messages.

### MCP/app frontend: `mcp.js`, `app_policy.js`, `mcp_tool_ui.js`, `tool_adapters/`

`mcp.js` handles:

- Loading/saving raw `mcp.json` config.
- Fetching tools from `/api/mcp/tools`.
- Caching tools in localStorage.
- Per-server enable/disable and auto-approve toggles.
- Per-server icon selection.
- Rendering grouped tool lists.

`app_policy.js` injects app-level model instructions. It tells the model:

- That it is running in Lumen AI Chat with per-chat workspace files.
- How to use uploaded file paths appended to user messages.
- To use `file:/workspace/...` links only for real workspace files.

Tool-specific behavior belongs in the MCP tool schemas/Zod definitions, not in `app_policy.js`. Keep this file focused on app-level behavior only.

`mcp_tool_ui.js` and `tool_adapters/` control how tool calls/results are displayed. To add rich rendering for a new MCP tool, prefer adding a tool adapter rather than special-casing in `renderer.js`.

Tool names sent to the model are namespaced as `server_tool` in `chat_payloads.js` to prevent collisions when multiple enabled MCP servers expose the same bare tool name. Keep tool descriptions clean and semantic (`tool.description || tool.name`); do not prepend `[server]` labels to model-facing descriptions because the namespace is already encoded in the function name. For UI and MCP dispatch, `chat_turn_service._bare_tool_name()` strips the namespace or uses `originalName` from metadata. If display and dispatch behavior ever need to diverge, split the helper at that point with a clear comment explaining why.

Existing adapters:

- `bash.js`: shell/command tools
- `filesystem.js`: `view`, `create_file`, `str_replace`
- `exa.js`: Exa search/fetch/deep-research tools with custom card rendering

### Renderer: `renderer.js`

Responsible for:

- Message rows and avatars
- Copy/edit/regenerate actions
- Streaming assistant message rows
- Thinking blocks
- Tool strips, approval UI, running UI, and final result UI
- Grouping sequential tool/thinking blocks when configured
- Rendering historical `displayLog`

### Workspace panel: `file_panel.js`

- Lists `/workspace` entries.
- Previews text/Markdown/code-like files.
- Downloads files through `/api/conversations/<conv_id>/files/download`.
- Refreshes after file uploads and tool results.
- Stores panel width in localStorage.

### Markdown and file links

`markdown.js` uses `marked`, `DOMPurify`, KaTeX, and highlight.js. It also enhances safe `file:/workspace/...` links into downloadable conversation-file links.

Only use `file:/workspace/...` links for files that already exist in the active conversation workspace.

## MCP config shape

All MCP servers run in the per-conversation container. A typical server configuration:

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/workspace"]
    }
  }
}
```

With explicit environment variables:

```json
{
  "mcpServers": {
    "search": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-brave-search"],
      "env": {
        "BRAVE_API_KEY": "your-key-here"
      }
    }
  }
}
```

Server-level UI settings such as enabled, auto-approve, and icon are not stored in `mcp.json`; they are stored in browser localStorage under `lumen_mcp_server_settings`.

## Development conventions

Follow the existing separation of concerns:

- Keep Flask route handlers thin.
- Put backend logic in service modules.
- Keep streaming and persistence behavior deliberate; partial responses are saved during generation.
- Keep `state.messages` and `state.displayLog` in sync conceptually, but do not merge them into one structure.
- Prefer adding frontend tool adapters for tool-specific UI instead of hardcoding tool names in renderer logic.
- Keep workspace path handling strict. Do not weaken traversal checks.
- Avoid introducing a frontend build step unless the whole project intentionally moves that direction.
- Do not send API keys in chat/model request bodies. Use `app_config.py` and `/api/settings`.
- Remember that MCP servers run in Docker; ensure the sandbox image is built and Docker is running before testing MCP behavior.
- Be cautious with module-level Python state if changing deployment assumptions; multi-worker servers will not share active streams/cancellation events.
- Keep cached module-level state protected where threaded access can mutate it.

## Automated test suite

Run `pytest` from the project root. The exact collected test count can change as the suite evolves, so do not hardcode a pass count in docs; the expected status is a clean passing run with no collection errors or failures.

```bash
pytest
```

Tests are isolated: `conftest.py` redirects filesystem paths to `tmp_path`, patches Docker startup checks in the app factory, and stubs container cleanup where needed. No Docker daemon, real API key, or running server is required for the unit/integration-style tests.

Coverage summary:

| File | Key contracts verified |
| --- | --- |
| `test_app_config.py` | Server-side config loading/saving, env overrides, public config, atomic persistence |
| `test_store.py` | SHA-256 image naming, media type validation, conversation CRUD, cached index ordering, index locking/concurrency |
| `test_workspace_service.py` | Path traversal rejection, `resolve_workspace_path` boundary check, preview size limit, upload rollback/collision handling |
| `test_chat_turn_service.py` | Tool approval flow, title extraction, safe tool args, tool message format, `TurnRecorder` throttle/finalize behavior |
| `test_streaming.py` | Typed event ordering, multi-delta tool name accumulation, parallel tool calls, cancellation closes stream, error+done events |
| `test_mcp_service.py` | Config cache, malformed-config handling, atomic writes, `run_async`, `McpSessionPool` same-task cleanup behavior |
| `test_mcp_adapters.py` | Docker exec param mutation, project-root detection, host mount extraction/deduplication |
| `test_container_service.py` | Safe container names, exec argv/env ordering, name-conflict handling, idle reaper behavior |
| `test_routes.py` | HTTP routes, route error paths, settings routes, conversation update whitelist |

Also syntax-check frontend modules after JS refactors:

```bash
find static/js -name '*.js' -print0 | xargs -0 -n1 node --check
```

## Manual verification checklist

Run this checklist manually after changes that touch streaming, MCP, Docker, or frontend module exports:

1. Python files compile:

   ```bash
   python -m py_compile *.py
   ```

2. Frontend modules parse:

   ```bash
   find static/js -name '*.js' -print0 | xargs -0 -n1 node --check
   ```

3. Test suite passes:

   ```bash
   pytest
   ```

4. App starts:

   ```bash
   python app.py
   ```

5. Browser opens `/` and renders the app.
6. API settings save through `/api/settings`; API key field clears and only shows saved-key metadata.
7. Creating, renaming, opening, and deleting conversations works.
8. A basic chat response streams token-by-token.
9. Stop/cancel works during streaming.
10. Settings save and reload.
11. Model list fetch works for the chosen OpenAI-compatible endpoint.
12. Image upload sends image input successfully.
13. Regular file upload appears in `/workspace/uploads` and the file panel.
14. Workspace preview/download works for text files.
15. MCP config save/load works.
16. MCP tool reload discovers tools.
17. Tool calls render `tool_start`, approval, running, and final result states.
18. Auto-approved tool calls skip approval and still render running/result states.
19. Multi-tool turns against the same MCP server do not log AnyIO cancel-scope cleanup errors.
20. Reopening a conversation during an active stream can reattach if still in the same backend process.
21. Docker container is created for a new conversation and MCP tools are discoverable once the conversation is open.

## Known limitations and things to inspect before feature work

### 1. Active stream reattach is process-local

`routes.py` stores active stream state in memory. This is fine for the dev server and a single Gunicorn worker, but it will not work across multiple worker processes without shared state.

Short-term deployment default: one worker with threads, as in `gunicorn.conf.py`.

Long-term fix: move cancellation and stream event delivery to Redis/pub-sub or another shared backend.

### 2. No authentication/user accounts

The app is local-first and self-hosted. Do not expose it publicly without adding authentication, stricter CORS, rate limiting, and stronger secret handling.

### 3. No database or migration layer

Persistent JSON shapes should remain backward-compatible, or migration code should be added deliberately.

## Safe editing advice for agents

Before editing:

1. Read `README.md` and this file first for intended behavior.
2. Read the backend service that owns the behavior, not just the route.
3. Read the corresponding frontend module; many features span backend, JS state, and renderer code.
4. Search for the event/type/string you plan to modify across the whole repo.
5. Preserve persistent JSON shapes unless you add migration/backward-compatible handling.
6. Run the relevant tests before and after the change.

When changing chat streaming:

- Preserve event ordering.
- Preserve cancellation behavior.
- Preserve partial persistence.
- Keep `streaming.py` dict-based internally.
- Test plain responses and tool-call responses.
- Test switching away from and back to a streaming conversation.

When changing MCP:

- Test container runtime with Docker running.
- Test approval and auto-approval.
- Test tool display labels and result rendering.
- Avoid assuming all MCP result content is JSON.
- Preserve `McpSessionPool` same-task lifecycle semantics.

When changing workspace files:

- Keep `/workspace` path normalization strict.
- Never permit arbitrary absolute host paths through file panel routes.
- Treat upload filenames as untrusted.
- Keep preview limits to avoid loading huge files into the browser.

When changing frontend rendering or module boundaries:

- Render current live stream and historical `displayLog` consistently.
- Keep edit/regenerate actions aligned with `displayLog` to `messages` index mapping.
- Avoid injecting unsanitized HTML unless it is controlled UI markup and escaped user data.
- Run `node --check` on all `static/js/**/*.js` files.
- Open the browser console and verify there are no missing module exports.

## Useful search commands

```bash
# Find route definitions
grep -R "@blueprint.route" -n .

# Find all stream event types
grep -R "tool_\|assistant_done\|reasoning\|stream_id\|tool_calls" -n *.py static/js

# Find MCP-specific code
grep -R "mcp\|MCP\|tool_calls\|tool_result\|McpSessionPool" -n *.py static/js tests

# Find workspace path handling
grep -R "workspace\|/workspace\|file:/" -n *.py static/js

# Check for accidental API key body usage
grep -R "api_key" -n static/js *.py tests

# Check for duplicate root tests
find . -maxdepth 1 -name 'test_*.py' -print
```

## Current non-goals / absent pieces

- No database layer
- No formal migration system
- No frontend package/build system
- No authentication/user accounts
- No shared backend state for multi-worker active stream reattach
- No server-side encryption for stored conversations, images, config, or workspaces

Keep these assumptions in mind before adding features that depend on users, accounts, distributed processes, or durable job queues.