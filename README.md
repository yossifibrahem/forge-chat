# Lumen AI Chat

A self-hosted Flask chatbot with real-time streaming, per-conversation Docker sandboxes, MCP server support, and a zero-build-step frontend.

Lumen is built for developers who want a capable local AI chat application without heavy infrastructure. The backend is plain Flask, the frontend is native browser ES modules served directly — no bundler, no framework, no deployment ritual.

---

## Screenshots

<table>
  <tr>
    <td align="center" width="50%"><img src="https://github.com/user-attachments/assets/8c8040eb-56f1-4f37-a331-9eddaa560294" alt="new chat" /><br/><sub>New chat screen</sub></td>
    <td align="center" width="50%"><img src="https://github.com/user-attachments/assets/e474ab80-6009-422d-ab5c-d83dd923e53e" alt="latex" /><br/><sub>LaTeX math rendering and conversation management</sub></td>
  </tr>
  <tr>
    <td align="center"><img src="https://github.com/user-attachments/assets/71b706e1-3ec6-4f2e-bdbd-145e9dcff9fb" alt="image upload" /><br/><sub>Image upload</sub></td>
    <td align="center"><img src="https://github.com/user-attachments/assets/c910ca2d-bf5d-471c-930d-d46b23e2790a" alt="file upload" /><br/><sub>File upload to the tools container</sub></td>
  </tr>
  <tr>
    <td align="center"><img src="https://github.com/user-attachments/assets/d46dcc44-7366-449b-8986-376b1f37a210" alt="workspace container" /><br/><sub>Per-conversation container and workspace browser</sub></td>
    <td align="center"><img src="https://github.com/user-attachments/assets/4a5f7412-80ac-4f8b-8eb6-302bcc096282" alt="tool approve" /><br/><sub>Tool approval flow</sub></td>
  </tr>
  <tr>
    <td align="center"><img src="https://github.com/user-attachments/assets/c941a553-c3ab-4ff2-991c-e3a6e89a2dbe" alt="api settings" /><br/><sub>API settings</sub></td>
    <td align="center"><img src="https://github.com/user-attachments/assets/15a74efb-9fe7-40c8-affe-c1764a72016f" alt="chat settings" /><br/><sub>Chat settings</sub></td>
  </tr>
  <tr>
    <td align="center"><img src="https://github.com/user-attachments/assets/d1cee8ef-9934-4ee3-88b5-47eb3abf28fb" alt="appearance settings" /><br/><sub>Appearance settings</sub></td>
    <td align="center"><img src="https://github.com/user-attachments/assets/027d0196-b1b4-4b4f-9020-824ac73346c5" alt="mcp settings" /><br/><sub>MCP server settings</sub></td>
  </tr>
</table>

---

## Features

**Model support**
- Any OpenAI-compatible API — OpenAI, Ollama, LM Studio, or a local proxy
- Configure API key, base URL, model, and system prompt from the browser UI
- Proxied model-list fetching so you can pick models without leaving the chat

**Streaming**
- Responses stream over Server-Sent Events (SSE) token-by-token
- Cancel mid-stream; the partial response is saved automatically
- Reattach to an in-progress stream if you navigate away and return

**MCP (Model Context Protocol)**
- Add MCP servers through the UI or `mcp.json`
- Tools are namespaced as `server_tool` to prevent name collisions across servers
- Per-turn MCP stdio session pooling — sessions are opened once and reused across tool calls in a single turn
- Approve or deny individual tool calls; enable auto-approval per server
- Tool activity renders inline: arguments, running state, and results

**Per-conversation Docker sandboxes**
- Every conversation gets its own Docker container and workspace directory
- The workspace is mounted at `/workspace` inside the container
- MCP servers run inside the container — code execution is isolated from the host
- Containers are stopped automatically when idle (configurable timeout)
- Stale containers from previous sessions are cleaned up at startup

**File handling**
- Upload files into the conversation workspace via the browser panel
- Preview text/code/Markdown files inline; download any workspace file
- Images are stored by SHA-256 content hash and sent as vision inputs to compatible models

**UI**
- Markdown, syntax-highlighted code blocks, and KaTeX math rendering
- Voice input via the browser Web Speech API
- Auto-generated conversation titles after the first exchange
- Create, rename, delete, and search conversations
- Customizable theme, accent color, font size, sidebar, timestamps, and more — stored in `localStorage`

**Architecture**
- No database — conversations are plain JSON files under `~/.lumen/`
- No frontend build step — Flask serves `templates/` and `static/` directly
- No bundler — browser ES modules imported with `type="module"`

---

## Quick Start

```bash
# 1. Clone
git clone https://github.com/yossifibrahem/lumen-ai-chat.git
cd lumen-ai-chat

# 2. Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Build the Docker sandbox image (required for MCP tools)
docker build -f Dockerfile.sandbox -t lumen-sandbox .

# 5. Start the app
python app.py
```

Open **http://localhost:8080**, then open the settings panel to enter your API key, base URL, and model name.

> The app will refuse to start if Docker is not running or if the `lumen-sandbox` image has not been built.

---

## Installation

### Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.10+ | Flask backend |
| Docker | 20.10+ | Required for MCP sandbox containers |
| Node.js / npm | Current LTS | Optional — needed for MCP servers launched via `npx` |
| OpenAI-compatible API | — | OpenAI, Ollama, LM Studio, or a compatible proxy |

### Python Dependencies

```bash
python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

```
flask>=3.0.0
flask-cors>=4.0.0
openai>=1.30.0
mcp>=1.0.0
```

### Build the Sandbox Image

All MCP servers run inside a per-conversation Docker container. Build the image once before starting the app:

```bash
docker build -f Dockerfile.sandbox -t lumen-sandbox .
```

The image name is configurable via `LUMEN_SANDBOX_IMAGE` (default: `lumen-sandbox`).

### Production Deployment

For a single-process production-style deployment, use Gunicorn:

```bash
gunicorn -c gunicorn.conf.py "app:create_app()"
```

`gunicorn.conf.py` defaults to **one worker with multiple threads**. Active stream state (cancellation events, reattach buffers) is stored in process memory, so multiple worker processes are not supported until stream state is moved to shared storage.

---

## Configuration

### In-App Settings

Open the settings panel in the browser to configure:

| Setting | Description |
|---|---|
| API Key | Provider API key — stored server-side, never in `localStorage` |
| Base URL | OpenAI-compatible endpoint, e.g. `https://api.openai.com/v1` |
| Model | Model ID for the next request |
| System Prompt | Optional instruction prepended to every conversation |

Local model providers typically use:

```
http://localhost:11434/v1    # Ollama
http://localhost:1234/v1     # LM Studio
```

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `OPENAI_API_KEY` | — | Overrides the saved API key |
| `OPENAI_BASE_URL` | — | Overrides the saved API base URL |
| `OPENAI_API_BASE` | — | Fallback alias for `OPENAI_BASE_URL` |
| `LUMEN_CONFIG_FILE` | `~/.lumen/config.json` | Server-side API config path |
| `LUMEN_CONFIG_CACHE_TTL` | `5` | Seconds to cache API config reads |
| `LUMEN_MCP_CONFIG_FILE` | `~/.lumen/mcp.json` | MCP server config path |
| `LUMEN_MCP_CONFIG_CACHE_TTL` | `5` | Seconds to cache MCP config reads |
| `LUMEN_SANDBOX_IMAGE` | `lumen-sandbox` | Docker image for sandbox containers |
| `LUMEN_CONTAINERS_ROOT` | `~/.lumen/containers` | Host directory for per-conversation workspaces |
| `LUMEN_CONTAINER_MEMORY` | `512m` | Memory limit per sandbox container |
| `LUMEN_CONTAINER_CPUS` | `1` | CPU quota per sandbox container |
| `LUMEN_CONTAINER_NETWORK` | `bridge` | Docker network mode |
| `LUMEN_CONTAINER_PREFIX` | `lumen-chat-` | Prefix for generated container names |
| `LUMEN_CONTAINER_IDLE_TIMEOUT` | `1800` | Seconds before idle containers are stopped; `0` disables |
| `LUMEN_MAX_CONTENT_LENGTH` | `62914560` | Flask request body cap (bytes) |
| `LUMEN_CORS_ORIGINS` | `http://localhost:8080,...` | Comma-separated allowed origins |
| `LUMEN_MAX_FILE_PREVIEW_BYTES` | `524288` | Max bytes for in-browser text file preview |
| `LUMEN_MAX_FILE_LIST_ENTRIES` | `500` | Max workspace directory entries returned |
| `LUMEN_MAX_UPLOAD_BYTES` | `52428800` | Max file upload size (bytes) |

### Persistent Data

All runtime data is stored outside the repo under `~/.lumen/`:

```
~/.lumen/
├── config.json       # Server-side API provider config
├── mcp.json          # MCP server configuration
├── conversations/    # One JSON file per conversation
├── containers/       # One workspace directory per conversation
└── images/           # Uploaded images keyed by SHA-256 hash
```

### MCP Configuration

MCP servers are configured in `~/.lumen/mcp.json` (or the path set by `LUMEN_MCP_CONFIG_FILE`). The settings panel can read and write this file from the browser.

All MCP servers run inside the conversation's Docker container with the workspace mounted at `/workspace`. Use `/workspace`-relative paths in server arguments.

**Example `mcp.json`:**

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": [
        "-y",
        "@modelcontextprotocol/server-filesystem",
        "/workspace"
      ]
    },
    "search": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-brave-search"],
      "env": {
        "BRAVE_API_KEY": "your-api-key-here"
      }
    }
  }
}
```

Per-server UI settings (enabled, auto-approve, icon) are stored in browser `localStorage` under `lumen_mcp_server_settings` — not in `mcp.json`.

Model-facing tool names are namespaced as `server_tool` so that two servers can expose identically-named tools without conflict. Tool descriptions stay clean and semantic; the namespace is encoded in the function name only.

---

## Usage

### Basic Chat

1. Run `python app.py` and open `http://localhost:8080`.
2. Create a new conversation from the sidebar.
3. Open settings and enter your API key, base URL, and model.
4. Type a message and press **Enter**. Use **Shift + Enter** for a newline.

### Uploading Files

Open the workspace panel, upload a file, and it will appear under `/workspace/uploads/` inside the conversation container. Preview text files in the browser or download any workspace file directly.

### Using MCP Tools

1. Build the sandbox image if you haven't already: `docker build -f Dockerfile.sandbox -t lumen-sandbox .`
2. Open the MCP settings panel and add a server (command, args, optional env vars).
3. Save the config and click **Load Tools** — a conversation must be open for tool discovery.
4. Send a message asking the model to use a tool.
5. Approve or deny the tool call when prompted (or enable auto-approval per server).

Tool activity is shown inline with the tool name, arguments, running state, and result.

### Cancelling a Stream

Click the stop button while a response is streaming. The server marks the stream as cancelled and saves whatever was already generated.

---

## Architecture

### Backend

| File | Responsibility |
|---|---|
| `app.py` | Flask app factory; Docker and sandbox image checks at startup; CORS; shutdown cleanup |
| `app_config.py` | Server-side API key and provider config storage; env var overrides; safe public metadata |
| `routes.py` | Thin HTTP handlers delegating to service modules; streaming and cancellation state |
| `chat_turn_service.py` | Full chat turn orchestration: streaming, tool approval, MCP calls, persistence |
| `streaming.py` | Typed OpenAI streaming event generator; SSE serialization helpers |
| `mcp_service.py` | MCP config, tool discovery, tool invocation, `McpSessionPool` for per-turn session reuse |
| `mcp_adapters.py` | Wraps MCP commands for Docker `exec`; extracts and mounts host volume paths |
| `container_service.py` | Docker container lifecycle: create, start, stop, idle reaping, workspace management |
| `store.py` | Filesystem persistence for conversations and images; cached conversation index |

### Chat Turn Flow

A single chat turn in `chat_turn_service.py`:

1. Build an OpenAI client from server-side config.
2. Pre-mount MCP server volumes and ensure the conversation container is running.
3. Stream model output via `streaming.py`; accumulate text and tool calls.
4. For each tool call: request approval (unless auto-approved), invoke via `McpSessionPool`, append the tool result to message history.
5. Loop until the model finishes without further tool calls.
6. Emit `assistant_done` and optionally a generated `title` event.

Partial output is saved during streaming by `TurnRecorder` so that cancelled or interrupted turns are not lost.

### Frontend

The frontend is plain browser ES modules — no build step, no framework. `templates/index.html` imports `static/js/app.js` with `type="module"`.

| Module | Responsibility |
|---|---|
| `state.js` | Single shared mutable state object |
| `app.js` | Bootstrap, event binding, startup loading |
| `chat_send.js` | Send flow, stream start, SSE event handling |
| `chat_payloads.js` | Builds API message payloads including images and file context |
| `chat_attachments.js` | Pending image and file attachment lifecycle |
| `chat_edit.js` | Edit, resend, and regenerate helpers |
| `stream_consumer.js` | SSE response reader |
| `renderer.js` | Message rows, tool strips, thinking blocks, approval UI |
| `mcp.js` | MCP config UI, tool loading, enable/auto-approve toggles |
| `file_panel.js` | Workspace browser, preview, and download |
| `conversations.js` | Conversation CRUD and sidebar |
| `settings.js` | API and chat settings UI |
| `markdown.js` | Markdown, code highlighting, KaTeX, safe workspace file links |
| `tool_adapters/` | Per-tool display adapters (`bash.js`, `filesystem.js`, `exa.js`) |

The frontend maintains two parallel histories: `state.messages` (model/API-facing) and `state.displayLog` (UI-facing). These have different structures and indices — do not conflate them.

---

## Testing

Install test dependencies:

```bash
pip install -r requirements-dev.txt
```

Run the full suite:

```bash
pytest
```

Tests are fully isolated: `conftest.py` redirects filesystem paths to `tmp_path`, patches Docker startup checks in the app factory, and stubs container operations. No running Docker daemon, API key, or live server is required.

| Test file | What it covers |
|---|---|
| `test_app_config.py` | Config load/save, env overrides, public config, atomic persistence |
| `test_store.py` | SHA-256 image naming, conversation CRUD, cached index, concurrency |
| `test_workspace_service.py` | Path traversal rejection, preview limits, upload collision handling |
| `test_chat_turn_service.py` | Tool approval, title extraction, `TurnRecorder` throttle/finalize |
| `test_streaming.py` | Event ordering, tool delta accumulation, parallel tools, cancellation |
| `test_mcp_service.py` | Config cache, malformed config, `McpSessionPool` same-task cleanup |
| `test_mcp_adapters.py` | Docker exec params, project-root detection, volume deduplication |
| `test_container_service.py` | Container naming, exec argv/env, name conflicts, idle reaper |
| `test_routes.py` | HTTP routes, error paths, conversation update whitelist |

Also lint frontend modules after any JS changes:

```bash
find static/js -name '*.js' -print0 | xargs -0 -n1 node --check
```

---

## Contributing

### Workflow

```bash
git clone https://github.com/yossifibrahem/lumen-ai-chat.git
cd lumen-ai-chat
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
git checkout -b feature/your-change
```

### Codebase Guidelines

- Keep Flask route handlers thin — business logic lives in service modules.
- Keep workspace path safety checks in `workspace_service.py`; never weaken traversal restrictions.
- Keep persistent data access inside `store.py` where possible.
- Do not send API keys in chat or model request bodies — use `app_config.py` and `/api/settings`.
- Avoid introducing a frontend build step unless the project intentionally adopts one.
- Keep browser code modular under `static/js/`; prefer adding tool adapters over hardcoding tool names in `renderer.js`.
- Update both `README.md` and `agent.md` when changing architecture, setup, configuration, or agent-facing behavior.

### Pull Request Checklist

- All tests pass (`pytest`) and frontend modules lint cleanly (`node --check`).
- Describe what changed and why; include manual test steps and results.
- Keep unrelated formatting changes out of functional PRs.
- Confirm the app still starts locally with Docker running.
- Confirm no API keys, conversation data, or local workspace files are committed.

### Reporting Issues

When filing a bug, please include the OS, Python version, browser and version, whether Docker is installed and running, reproduction steps, expected and actual behavior, and any relevant terminal or browser console output.

---

## Known Limitations

**Active stream reattach is process-local.** Cancellation events and stream replay buffers are stored in process memory (`routes.py`). This works fine with the default single-worker Gunicorn config but will not work across multiple worker processes. Long-term fix: move stream state to Redis or a shared broker.

**No authentication.** Lumen is local-first and not hardened for public exposure. Do not deploy it publicly without adding authentication, rate limiting, and stricter CORS.

**No database or migrations.** Conversation JSON shapes must remain backward-compatible, or migration code must be added deliberately.

---

## License

MIT — built for people who like local control, readable code, and AI tools that do not require a 14-step deployment ritual.
