# Agent Guide for Lumen AI Chat

This file is a working guide for agents modifying this repository. It is based on a codebase pass over `README.md`, the Flask backend modules, the frontend ES modules, MCP integration code, workspace/file handling, streaming logic, and Docker sandbox support.

## Project at a glance

Lumen is a self-hosted Flask chat UI for OpenAI-compatible chat-completions APIs. It supports:

- Streaming responses over Server-Sent Events (SSE)
- OpenAI-compatible model settings from the browser UI
- Local filesystem conversation persistence under `~/.lumen/`
- Per-conversation workspace directories mounted as `/workspace`
- Docker sandbox containers per conversation
- MCP server configuration through `mcp.json` and the UI
- MCP tool discovery, tool-call execution, approval/deny UI, and tool-result rendering
- Image uploads stored by content hash
- Regular file uploads stored in the conversation workspace
- Markdown, code highlighting, KaTeX, voice input, theming, and conversation search

The app is intentionally lightweight: no database, no build step, no frontend framework, and no automated test suite currently included.

## Repository map

```text
.
├── app.py                         # Flask app factory and startup cleanup
├── routes.py                      # HTTP API routes and SSE stream endpoint
├── chat_turn_service.py           # Long-running chat turn orchestration
├── streaming.py                   # OpenAI streaming generator + SSE helpers
├── mcp_service.py                 # MCP config, tool discovery, tool invocation
├── mcp_adapters.py                # Host/container MCP launch helpers
├── container_service.py           # Docker container lifecycle and command wrapping
├── workspace_service.py           # Workspace listing, reading, upload, download path safety
├── store.py                       # Filesystem persistence for conversations and images
├── Dockerfile.sandbox             # Required per-chat sandbox image
├── requirements.txt               # Flask, CORS, OpenAI SDK, MCP SDK
├── requirements-dev.txt           # Adds pytest and pytest-mock on top of requirements.txt
├── pytest.ini                     # Test discovery config: pythonpath = ., testpaths = tests
├── README.md                      # User-facing project description and setup docs
├── templates/index.html           # Full app shell and modal markup
├── tests/
│   ├── conftest.py                # Shared fixtures: tmp_lumen (filesystem isolation), app, client
│   ├── test_store.py              # Image storage and conversation CRUD unit tests
│   ├── test_workspace_service.py  # Path safety, listing, reading, upload, _unique_path
│   ├── test_chat_turn_service.py  # _parse_stream_payload, _extract_title, TurnRecorder, etc.
│   ├── test_streaming.py          # SSE formatting, event ordering, cancellation, tool accumulation
│   ├── test_mcp_service.py        # Config load/save/find, run_async bridge
│   ├── test_mcp_adapters.py       # apply_workspace_process_options, find_project_root, extract_host_mounts
│   ├── test_container_service.py  # _safe_id, wrap_command_for_exec, _is_name_conflict, _volume_args
│   └── test_routes.py             # Flask HTTP integration tests via test client
└── static/
    ├── css/                       # CSS entrypoint and module files
    └── js/
        ├── app.js                 # Browser bootstrapping and event binding
        ├── api.js                 # Thin fetch wrapper
        ├── chat.js                # Message sending, attachments, SSE client, regeneration/editing
        ├── conversations.js       # Conversation CRUD and sidebar list
        ├── customization.js       # Theme/font/accent/customization state
        ├── file_panel.js          # Workspace browser/preview/download UI
        ├── markdown.js            # Markdown rendering and safe file-link enhancement
        ├── mcp.js                 # MCP config UI, tool loading, enable/auto-approve toggles
        ├── mcp_policy.js          # System prompt injected when MCP tools are enabled
        ├── mcp_tool_ui.js         # Generic tool-result rendering helpers
        ├── renderer.js            # Chat/message/thinking/tool strip rendering
        ├── settings.js            # API/model/chat settings UI
        ├── state.js               # Shared browser state and localStorage keys
        ├── storage.js             # localStorage wrapper
        ├── ui.js                  # General UI helpers
        ├── voice.js               # Web Speech API integration
        └── tool_adapters/         # Tool-specific display/rendering adapters
```

## How to run locally

Install dependencies:

```bash
pip install -r requirements-dev.txt
```

Run the test suite (no Docker or API key required):

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

Required sandbox image (build once before first run):

```bash
docker build -f Dockerfile.sandbox -t lumen-sandbox .
```

Production-ish entrypoint from the README:

```bash
gunicorn -w 4 -b 0.0.0.0:8080 "app:create_app()"
```

## Persistence and runtime locations

The backend stores user data outside the repo by default:

```text
~/.lumen/
├── conversations/   # one JSON file per conversation
├── containers/      # one workspace directory per conversation
└── images/          # uploaded images keyed by SHA-256 hash
```

Important environment variables:

```text
LUMEN_SANDBOX_IMAGE       default: lumen-sandbox
LUMEN_CONTAINERS_ROOT     default: ~/.lumen/containers
LUMEN_CONTAINER_MEMORY    default: 512m
LUMEN_CONTAINER_CPUS      default: 1
LUMEN_CONTAINER_NETWORK   default: bridge
LUMEN_CONTAINER_PREFIX    default: lumen-chat-
LUMEN_CONTAINER_IDLE_TIMEOUT default: 1800 (seconds; 0 disables idle reaping)
LUMEN_MAX_FILE_PREVIEW_BYTES default: 512 KiB
LUMEN_MAX_FILE_LIST_ENTRIES  default: 500
LUMEN_MAX_UPLOAD_BYTES       default: 50 MiB
```

Note: both the README and the code use uppercase `LUMEN_*` env var names. Browser `localStorage` keys (such as `lumen_mcp_server_settings`) intentionally use lowercase and are unrelated to these environment variables.

## Backend architecture

### `app.py`

- Creates the Flask app with CORS enabled.
- Registers the single blueprint from `routes.py`.
- On startup, attempts to remove stale Docker containers whose conversation JSON no longer exists.
- Docker cleanup is non-fatal; the app should still start when Docker is unavailable.

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
- `/api/models` proxies model-list fetching through the configured OpenAI-compatible endpoint.

Streaming state is stored in module-level dictionaries:

- `_cancel_events`: `stream_id -> threading.Event`
- `_active_streams`: `stream_id -> replayable stream state`

Because these are in-memory, active stream reattach works only within the same Python process. Multiple Gunicorn workers may not share active stream state.

### `chat_turn_service.py`

This is the core backend orchestration layer for a chat turn.

Key responsibilities:

- Create an OpenAI client using the user-provided API key/base URL.
- Stream model chunks through `streaming.stream_chat_completion()`.
- Accumulate text and `reasoning_content`.
- Persist partial assistant output using `TurnRecorder`.
- Detect streamed tool calls.
- Request frontend approval for tools unless the server is set to auto-approve.
- Invoke MCP tools through `mcp_service.invoke_tool()`.
- Append tool messages back into the API message history.
- Loop until the model completes without more tool calls.
- Emit final `assistant_done` and optional generated `title` events.

SSE event types produced/forwarded include:

```text
reasoning
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
- Converts chunks to JSON SSE events.
- Merges incremental tool-call deltas by tool-call index.
- Emits `tool_start` as soon as a tool name appears.
- Emits `tool_calls` when the finish reason is `tool_calls`.
- Supports cancellation by closing the OpenAI stream when the cancellation event is set.

The generator yields already-formatted SSE strings, so callers parse those strings again in `chat_turn_service._parse_stream_payload()`.

### `mcp_service.py`

- Persists `mcp.json` in the project root.
- Validates only the top-level shape: `{"mcpServers": {...}}`.
- Connects to each MCP server through stdio.
- Uses `mcp_adapters.apply_workspace_process_options()` to configure the container runtime for each MCP server.
- `fetch_tools()` returns OpenAI-tool-like metadata for the frontend.
- `invoke_tool()` returns text output by joining result content blocks.
- `run_async()` bridges async MCP calls into Flask sync route/service code.

### `mcp_adapters.py`

All MCP servers run inside the per-conversation Docker container. There is no host runtime fallback.

Container runtime:

- Requires `conv_id`; otherwise raises `ContainerConversationRequired`.
- Ensures the per-conversation Docker container is running.
- Mounts the conversation workspace as `/workspace`.
- Wraps the MCP command with `docker exec -i --workdir /workspace ...`.
- Injects explicit MCP env vars into the container with `docker exec --env`.
- Extracts absolute script/project paths from server args and mounts nearby project roots read-only.


### MCP discovery container

`/api/mcp/tools` can run without an open conversation. When `conv_id` is missing, it uses the reusable `__mcp_discovery__` container, lists MCP tools, then stops it for idle reuse.

Keep this behavior intact:

- Stale-container cleanup must skip `__mcp_discovery__`.
- Real chat tool discovery/calls must still use the actual conversation `conv_id`.
- Remote MCP servers may log harmless `AbortError`/SSE shutdown noise when discovery stops the container after tools load.

Covered by tests: no-`conv_id` discovery, discovery start/stop/reuse, skipped-server response preservation, stale-cleanup skip, and normal `conv_id` behavior.

### `container_service.py`

- Creates and reuses Docker containers named with `LUMEN_CONTAINER_PREFIX` plus a sanitized conversation id.
- One host workspace directory is created per conversation under `LUMEN_CONTAINERS_ROOT`.
- Containers are started with `/workspace` mounted to the host workspace.
- The sandbox drops all capabilities, then adds back a minimal set: `CHOWN`, `DAC_OVERRIDE`, `SETUID`, `SETGID`.
- Provides stale container cleanup, container removal, workspace deletion, status inspection, and `docker exec` command wrapping.
- **Idle reaper**: a daemon thread stops conversation containers that have been idle beyond `LUMEN_CONTAINER_IDLE_TIMEOUT` (default 1800 s / 30 min). Activity is tracked via `_touch(conv_id)`, called automatically from `ensure_container()` and `wrap_command_for_exec()`. The reaper uses `stop_container_process()` (soft stop, not removal), so the container can be restarted instantly on next use. Set `LUMEN_CONTAINER_IDLE_TIMEOUT=0` to disable. The MCP discovery container is explicitly excluded from reaping.

The Docker container command is `sleep infinity`, so it stays alive for later `docker exec` MCP calls.

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
- Writes are atomic-ish: write temp file, then replace target.

## Frontend architecture

The frontend is plain browser ES modules. `templates/index.html` defines the DOM shell and imports `static/js/app.js` with `type="module"`.

### Shared state

`static/js/state.js` exports a single mutable `state` object. Major fields:

```js
state.convId
state.messages
state.displayLog
state.mcpTools
state.mcpServerSettings
state.isStreaming
state.streamId
state.apiBase
state.apiKey
state.model
state.systemPrompt
state.temperature
state.autoGenerateTitles
state.enterToSend
state.autoScrollStreaming
```

Settings and customization are persisted in `localStorage` using keys from `STORAGE_KEYS`.

### App startup: `app.js`

- Loads settings, customization, cached MCP tools, and conversation list.
- Binds sidebar, modal, settings, input, keyboard, model picker, MCP, voice, attachments, and file-panel events.
- Initializes icons.
- Opens the last active conversation if available.

### Chat flow: `chat.js`

When the user sends a message:

1. Pending attachments finish processing.
2. A conversation is created if none exists.
3. Images are uploaded to `/api/images` and stored as `image_ref` blocks in local message history.
4. Regular files are uploaded to `/api/conversations/<conv_id>/files` and their `/workspace/uploads/...` paths are attached to the user message metadata.
5. The user message is appended to `turn.messages` and `turn.displayLog`.
6. The conversation is persisted before model streaming starts.
7. `buildApiMessages()` constructs the API payload:
   - Prepends system prompt and MCP policy prompt.
   - Adds file attachment context into user content.
   - Expands stored image refs to base64 `image_url` blocks for OpenAI-compatible vision input.
8. `/api/chat/stream` is called with API settings, messages, tools, MCP metadata, stream id, and conversation id.
9. The frontend reads SSE lines and updates the UI incrementally.

### Conversation history model

There are two parallel histories:

- `state.messages`: model/API-facing history.
- `state.displayLog`: UI-facing render log, including messages, thinking blocks, and tool results.

Do not assume they have the same indices. Use helper mapping logic when editing/regenerating messages.

### MCP frontend: `mcp.js`, `mcp_policy.js`, `mcp_tool_ui.js`, `tool_adapters/`

`mcp.js` handles:

- Loading/saving raw `mcp.json` config.
- Fetching tools from `/api/mcp/tools`.
- Caching tools in localStorage.
- Per-server enable/disable and auto-approve toggles.
- Per-server icon selection.
- Rendering grouped tool lists.

`mcp_policy.js` injects model instructions when MCP tools are enabled. It tells the model:

- Which tools are available.
- Workspace semantics for the container runtime.
- To include a concise `description` argument first for each MCP tool call.
- To view files before and after filesystem edits.
- To use `file:/workspace/...` links only for real workspace files.

`mcp_tool_ui.js` and `tool_adapters/` control how tool calls/results are displayed. To add rich rendering for a new MCP tool, prefer adding a tool adapter rather than special-casing in `renderer.js`.

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
- Remember that MCP servers always run in Docker; ensure the sandbox image is built and Docker is running before testing MCP behaviour.
- Be cautious with module-level Python state if changing deployment assumptions; multi-worker servers will not share active streams/cancellation events.

## Automated test suite

Run `pytest` from the project root. All 255 tests must pass before merging any change.

```bash
pytest
# 255 passed in ~3s
```

Tests are isolated: `conftest.py` redirects all filesystem paths to `tmp_path`, patches `_require_docker` and `_require_sandbox_image` in the app factory, and stubs `container_service.cleanup_stale`. No Docker daemon, real API key, or running server is needed.

**Coverage summary:**

| File | Key contracts verified |
| --- | --- |
| `test_store.py` | SHA-256 image naming, media type validation, conversation CRUD atomicity, `list_all` newest-first ordering |
| `test_workspace_service.py` | Path traversal rejection (all forms), `resolve_workspace_path` boundary check, preview size limit, `save_uploads` 413 with rollback, `_unique_path` collision deduplication |
| `test_chat_turn_service.py` | `_parse_stream_payload` (all 4 SSE parse paths), `_extract_title` (3 model-format paths), `_safe_tool_args` silent failure, `_tool_call_message` OpenAI wire format, `TurnRecorder` throttle and force-bypass |
| `test_streaming.py` | SSE event ordering, multi-delta tool name accumulation, parallel tool calls, cancellation closes stream, errors produce error+done events |
| `test_mcp_service.py` | Config load/save/roundtrip, malformed-config handling, atomic writes, `run_async` exception propagation |
| `test_mcp_adapters.py` | `apply_workspace_process_options` param mutation, `find_project_root` depth limit (prevents mounting `/home`/`/`), `extract_host_mounts` deduplication and `:ro` flag |
| `test_container_service.py` | `_safe_id` character sanitisation (shell-safety), `wrap_command_for_exec` argv and env ordering, `_is_name_conflict` race detection, `_touch` timestamp recording, `_reap_once` idle stop/skip/discovery-exclusion/disable |
| `test_routes.py` | All HTTP routes via Flask test client, including 400/404/413 error paths |

## Manual verification checklist

Run this checklist manually after changes that touch streaming, MCP, or Docker — areas that involve real subprocesses that cannot be fully mocked:

1. Python files compile:

   ```bash
   python -m py_compile *.py
   ```

2. App starts:

   ```bash
   python app.py
   ```

3. Browser opens `/` and renders the app.
4. Creating, renaming, opening, and deleting conversations works.
5. A basic chat response streams token-by-token.
6. Stop/cancel works during streaming.
7. Settings save and reload from localStorage.
8. Model list fetch works for the chosen OpenAI-compatible endpoint.
9. Image upload sends image input successfully.
10. Regular file upload appears in `/workspace/uploads` and the file panel.
11. Workspace preview/download works for text files.
12. MCP config save/load works.
13. MCP tool reload discovers tools.
14. Tool calls render `tool_start`, approval, running, and final result states.
15. Auto-approved tool calls skip approval and still render running/result states.
16. Reopening a conversation during an active stream can reattach if still in the same backend process.
17. Docker container is created for a new conversation and MCP tools are discoverable once the conversation is open.

Recommended future tests:

- Flask route tests with `pytest` and Flask test client.
- Unit tests for `workspace_service.workspace_relpath()` and `resolve_workspace_path()`.
- Unit tests for `store.save_image()` and invalid image handling.
- Unit tests for `mcp_adapters.apply_workspace_process_options()` and container launch parameter mutation.
- Integration-ish tests for chat stream event ordering using mocked OpenAI streams.

## Known issues and things to inspect before feature work

These were found during the repository pass and should be verified/fixed before relying heavily on MCP tool calls:

### 1. Active stream reattach is process-local

`routes.py` stores active stream state in memory. This is fine for the dev server and maybe one Gunicorn worker, but it will not work across multiple workers/processes without shared state.

### 2. Tool-name collisions across MCP servers

OpenAI tool names are currently just `tool.name`, while tool metadata maps by `name` only. If two enabled MCP servers expose the same tool name, metadata lookup may collide. A future-safe design would namespace tool names or track call-to-server mapping more explicitly.

## Safe editing advice for agents

Before editing:

1. Read `README.md` first for intended behavior.
2. Read the backend service that owns the behavior, not just the route.
3. Read the corresponding frontend module; many features are split across backend and JS state/rendering.
4. Search for the event/type/string you plan to modify across the whole repo.
5. Preserve persistent JSON shapes unless you add migration/backward-compatible handling.

When changing chat streaming:

- Preserve event ordering.
- Preserve cancellation behavior.
- Preserve partial persistence.
- Test with plain responses and tool-call responses.
- Test switching away from and back to a streaming conversation.

When changing MCP:

- Test container runtime with Docker running.
- Test approval and auto-approval.
- Test tool display labels and result rendering.
- Avoid assuming all MCP result content is JSON.

When changing workspace files:

- Keep `/workspace` path normalization strict.
- Never permit arbitrary absolute host paths through the file panel routes.
- Treat upload filenames as untrusted.
- Keep preview limits to avoid accidentally loading huge files into the browser.

When changing frontend rendering:

- Render current live stream and historical `displayLog` consistently.
- Keep edit/regenerate actions aligned with `displayLog` to `messages` index mapping.
- Avoid injecting unsanitized HTML unless it is controlled UI markup and escaped user data.

## Useful search commands

```bash
# Find route definitions
grep -R "@blueprint.route" -n .

# Find all SSE event types
grep -R "type.*tool_\|assistant_done\|reasoning\|stream_id" -n *.py static/js

# Find MCP-specific code
grep -R "mcp\|MCP\|tool_calls\|tool_result" -n *.py static/js

# Find workspace path handling
grep -R "workspace\|/workspace\|file:/" -n *.py static/js
```

## Current non-goals / absent pieces

- No database layer
- No formal migration system
- No bundled automated tests
- No frontend package/build system
- No authentication/user accounts
- No shared backend state for multi-worker active stream reattach
- No server-side encryption for stored conversations, images, or workspaces

Keep these assumptions in mind before adding features that depend on users, accounts, distributed processes, or durable job queues.