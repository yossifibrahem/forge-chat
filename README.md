# Lumen AI Chat

A self-hosted Flask chatbot interface for OpenAI-compatible models, with real-time streaming, local conversation persistence, per-conversation file workspaces, Docker-sandboxed MCP execution, and Model Context Protocol (MCP) server support.

Lumen is designed for developers who want a capable local AI chat app without a heavy framework stack. The backend is plain Flask, the frontend is browser-native JavaScript modules, and all persistent data is stored on the local filesystem.

---

## 📋 Project description

**Lumen AI Chat** is a lightweight web application that provides a polished chat experience for any API that follows the OpenAI chat-completions format. It can be used with OpenAI-hosted models, local OpenAI-compatible servers, or proxy providers that expose a compatible `/v1/chat/completions` API.

The application focuses on three core ideas:

1. **Local-first control** — conversations, uploads, images, and workspaces are stored locally under `~/.lumen/` by default.
2. **Tool-ready chat** — MCP servers can be configured from the UI or through `mcp.json`, allowing the model to discover and call external tools.
3. **Safer experimentation** — each conversation runs MCP servers inside an isolated Docker-backed sandbox, keeping generated files and code execution separate from the host machine.

The project intentionally avoids a frontend build pipeline. The UI is served directly by Flask from `templates/` and `static/`, making it simple to run, inspect, and modify.

---

## ✨ Features

- **OpenAI-compatible model support**  
  Configure an API key, base URL, model name, and system prompt from the browser UI.

- **Real-time streaming responses**  
  Assistant responses stream through Server-Sent Events (SSE), including support for cancellation and stream reattachment.

- **MCP server support**  
  Add MCP servers through the UI or `mcp.json`; Lumen discovers tools and makes them available to the model.

- **Tool approval flow**  
  Tool calls can require user approval before execution, with optional auto-approval for trusted MCP servers.

- **Per-conversation workspaces**  
  Every conversation gets an isolated workspace directory that can store uploaded files, generated outputs, and files used by tools.

- **Docker sandbox containers**  
  Every MCP server runs inside a per-conversation Docker container with the workspace mounted at `/workspace`, isolating code execution from the host machine.

- **Workspace file browser**  
  Upload, list, preview, and download files from the browser UI.

- **Image uploads**  
  Images are stored by content hash and can be sent as vision inputs to compatible models.

- **Markdown, code, and math rendering**  
  Supports Markdown, syntax-highlighted code blocks, and KaTeX-powered math rendering.

- **Voice input**  
  Uses the browser Web Speech API where available.

- **Conversation management**  
  Create, rename, delete, search, and persist conversations locally.

- **Auto-generated chat titles**  
  After the first exchange, the app can generate a concise conversation title.

- **Customizable UI**  
  Supports theme, accent color, font size, sidebar behavior, timestamps, character count, and suggestion chips through local browser settings.

---

## 🚀 Quick start

```bash
# 1. Clone the repository
git clone https://github.com/yossifibrahem/lumen-ai-chat.git
cd lumen-ai-chat

# 2. Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Start the Flask development server
python app.py
```

Open the app in your browser:

```text
http://localhost:8080
```

Then open the settings panel, enter your API key, base URL, and model name, and start a new chat.

---

## 📦 Installation

### Prerequisites

| Requirement | Version | Required? | Notes |
| --- | --- | --- | --- |
| Python | 3.10+ recommended | Yes | Flask backend runtime |
| pip | Latest recommended | Yes | Installs Python dependencies |
| Docker | 20.10+ recommended | Yes | Required for MCP sandbox containers |
| Node.js / npm | Current LTS recommended | Optional | Needed for MCP servers launched through commands such as `npx` |
| OpenAI-compatible API | Provider-dependent | Yes | OpenAI, local model server, or compatible proxy |

### Python setup

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install --upgrade pip
pip install -r requirements.txt
```

Current Python dependencies:

```text
flask>=3.0.0
flask-cors>=4.0.0
openai>=1.30.0
mcp>=1.0.0
```

### Docker sandbox setup

Lumen runs all MCP servers inside per-conversation Docker containers. The sandbox image must be built before starting the app. The image name is configured by `LUMEN_SANDBOX_IMAGE` (default: `lumen-sandbox`).

Build the sandbox image from the project root:

```bash
docker build -f Dockerfile.sandbox -t lumen-sandbox .
```

The app will refuse to start if Docker is unreachable or if the sandbox image has not been built.

### Production-style run

For local development, use:

```bash
python app.py
```

For a more production-like deployment, run the Flask app behind a WSGI server such as Gunicorn:

```bash
gunicorn -w 4 -b 0.0.0.0:8080 "app:create_app()"
```

> Note: active streaming state is stored in process memory. If you use multiple Gunicorn workers, stream reattachment and cancellation state may not be shared across workers.

---

## ⚙️ Configuration

### In-app model settings

Open the settings panel in the UI to configure:

| Setting | Description |
| --- | --- |
| API key | The provider API key used for chat and model-list requests |
| Base URL | OpenAI-compatible API base URL, for example `https://api.openai.com/v1` |
| Model | Model ID to use for the next chat request |
| System prompt | Optional instruction prepended to the conversation |

For local model providers, use their OpenAI-compatible base URL. Common examples include:

```text
http://localhost:11434/v1      # Ollama-style OpenAI compatibility
http://localhost:1234/v1       # LM Studio-style local server
```

Exact model IDs depend on your provider.

### Environment variables

Lumen reads the following environment variables at runtime:

| Variable | Default | Description |
| --- | --- | --- |
| `LUMEN_SANDBOX_IMAGE` | `lumen-sandbox` | Docker image used for sandbox containers |
| `LUMEN_CONTAINERS_ROOT` | `~/.lumen/containers` | Host directory for per-conversation workspaces |
| `LUMEN_CONTAINER_MEMORY` | `512m` | Docker memory limit per sandbox container |
| `LUMEN_CONTAINER_CPUS` | `1` | Docker CPU quota per sandbox container |
| `LUMEN_CONTAINER_NETWORK` | `bridge` | Docker network mode for sandbox containers |
| `LUMEN_CONTAINER_PREFIX` | `lumen-chat-` | Prefix used for generated container names |
| `LUMEN_MAX_FILE_PREVIEW_BYTES` | `524288` | Maximum size for text file previews in the UI |
| `LUMEN_MAX_FILE_LIST_ENTRIES` | `500` | Maximum number of entries returned when listing a workspace directory |
| `LUMEN_MAX_UPLOAD_BYTES` | `52428800` | Maximum file upload size in bytes |

Example:

```bash
export LUMEN_CONTAINER_MEMORY=1g
export LUMEN_CONTAINER_CPUS=2
export LUMEN_MAX_UPLOAD_BYTES=104857600
python app.py
```

### Persistent data

By default, runtime data is stored under the current user's home directory:

```text
~/.lumen/
├── conversations/   # Conversation JSON files
├── containers/      # Per-conversation workspace directories
└── images/          # Uploaded images keyed by SHA-256 hash
```

These files are not stored in the project repository unless you manually copy them there.

### MCP configuration

MCP servers are stored in `mcp.json` in the project root. The UI can read and write this file through the MCP settings panel.

Model-facing tool names are namespaced as `server_tool` so two enabled MCP servers can expose the same bare tool name without colliding. The namespace is kept in the API tool name, while tool descriptions stay clean and semantic instead of being prefixed with server labels. The UI still groups tools by server for readability.

All MCP servers run inside the conversation's Docker sandbox container, with the workspace mounted at `/workspace`. Example `mcp.json`:

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

The conversation workspace is available as `/workspace` inside the container. Prefer `/workspace`-relative paths in server arguments rather than host-absolute paths.

---

## 💻 Usage examples

### Start a basic chat

1. Start the server with `python app.py`.
2. Open `http://localhost:8080`.
3. Create a new chat from the sidebar.
4. Open settings and enter your API key, base URL, and model.
5. Type a message and press **Enter**.

Use **Shift + Enter** to insert a new line without sending.

### Use a local OpenAI-compatible model

If your local model server exposes an OpenAI-compatible API, set the base URL in the settings panel, for example:

```text
Base URL: http://localhost:1234/v1
Model: your-local-model-id
```

Then send a normal chat message. Lumen will use the configured endpoint for the next request.

### Upload and preview files

1. Open the file/workspace panel.
2. Upload a file into the current conversation workspace.
3. Preview supported text files directly in the browser.
4. Download generated or uploaded files from the same panel.

Workspace paths are normalized to `/workspace/...` for safe tool and sandbox usage.

### Use MCP tools in a conversation

1. Build the sandbox image (first time only):

   ```bash
   docker build -f Dockerfile.sandbox -t lumen-sandbox .
   ```

2. Start the app — Docker availability and the sandbox image are validated at startup.
3. Open the MCP settings panel.
4. Add an MCP server command, arguments, and optional environment variables.
5. Save the configuration.
6. Load or refresh available tools — a conversation must be open for tool discovery to work.
7. Ask the assistant to use one of the tools.
8. Approve or deny the tool call when prompted, unless auto-approval is enabled for that server.

Tool activity is shown inline in the chat, including bare tool names, arguments, status, and results. Internally, API tool names use the `server_tool` namespace and are stripped back to the bare MCP tool name for display and dispatch. All tool execution happens inside the conversation's Docker container with the workspace mounted at `/workspace`.

### Cancel a streaming response

While a response is streaming, click the stop button. The server marks the active stream as cancelled and saves the partial assistant response that was already generated.

### Customize the interface

Use the UI customization controls to change theme, accent color, font size, timestamps, sidebar behavior, and related display settings. These preferences are stored in browser `localStorage`.

---

## 🧪 Running tests

Install test dependencies:

```bash
pip install -r requirements-dev.txt
```

Run the full test suite:

```bash
pytest
```

The test suite covers store, workspace service, chat turn service, streaming, MCP service, MCP adapters, container service, and Flask HTTP routes. Tests are isolated using temporary filesystem paths and do not require Docker or an API key.

Manual smoke test checklist before opening a pull request:

- App starts with `python app.py`
- New chat can be created
- A message streams successfully
- Response cancellation works
- Conversation reload preserves messages
- File upload/list/preview/download works
- MCP config can be saved and tools can be listed
- Docker is running and the sandbox image exists before starting the app

---

## 📝 Contributing

Contributions are welcome. Please keep changes focused, documented, and easy to review.

### Development workflow

```bash
git clone https://github.com/yossifibrahem/lumen-ai-chat.git
cd lumen-ai-chat
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
git checkout -b feature/your-change
```

### Codebase guidelines

- Keep Flask route handlers thin; place business logic in service modules.
- Keep persistent data access inside `store.py` where possible.
- Keep workspace file safety checks centralized in `workspace_service.py`.
- Treat MCP server commands and tool arguments as sensitive execution boundaries.
- Avoid introducing a frontend build step unless the project intentionally adopts one.
- Keep browser code modular under `static/js/`.
- Update `README.md` and `agent.md` when changing architecture, setup, configuration, or agent-facing workflows.

### Pull request checklist

Before submitting a pull request:

- All automated tests pass (`pytest`)
- Explain what changed and why.
- Include manual test steps and results.
- Keep unrelated formatting changes out of functional PRs.
- Confirm the app still starts locally.
- Confirm no secrets, API keys, conversation data, or local workspace files are committed.

### Reporting issues

When reporting a bug, include:

- Operating system
- Python version
- Browser and version
- Whether Docker is installed and running
- Steps to reproduce
- Expected behavior
- Actual behavior
- Relevant terminal logs or browser console errors

---

## 📄 License

This project is released under the MIT License.
Built for people who like local control, readable code, and AI tools that do not require a 14-step deployment ritual.