# lumen · AI Chat
A self-hosted, Flask-powered chat UI for any OpenAI-compatible AI model — with streaming, MCP tool integration, Docker sandboxes, and a polished frontend.

---

## 📋 Project Description

**lumen** is a lightweight, self-hosted web application that gives you a beautiful, full-featured chat interface for any AI model that speaks the OpenAI API format — including GPT-4o, Claude (via compatible proxies), and local models running through Ollama or LM Studio.

Conversations are persisted locally on your filesystem. Each conversation gets its own isolated file workspace and, optionally, a Docker-backed sandbox container so AI-generated code can run safely without touching your host system. MCP (Model Context Protocol) servers can be wired in at any time to give the model access to external tools.

---

## ✨ Features

- **Any OpenAI-compatible model** — Point lumen at OpenAI, Anthropic, a local Ollama instance, LM Studio, or any other compatible endpoint via a configurable base URL and API key.
- **Real-time streaming** — Responses stream token-by-token over Server-Sent Events (SSE) with full support for cancellation mid-reply.
- **MCP tool integration** — Configure one or more [Model Context Protocol](https://modelcontextprotocol.io) servers in `mcp.json`. Tools are auto-discovered and injected into the model's tool list.
- **Per-conversation Docker sandboxes** — Each conversation can spin up an isolated `lumen-sandbox` Docker container with a shared `/workspace` volume, so the model can write and execute code safely.
- **File workspaces** — Upload files to a conversation, browse the workspace directory tree, preview file contents, and download results — all from the sidebar.
- **Voice input** — Dictate messages using the Web Speech API (Chrome and Edge).
- **Rich rendering** — Markdown, fenced code blocks with syntax highlighting (highlight.js), and inline/block LaTeX math (KaTeX) all render beautifully.
- **Thinking steps** — Extended reasoning / chain-of-thought blocks are displayed in a collapsible "thinking" panel.
- **Auto-generated titles** — After the first exchange, a separate lightweight model call names the conversation in 2–5 words.
- **Image uploads** — Paste or attach images; they are stored by content hash and sent as vision inputs.
- **Customisable UI** — Accent colour, theme, font size, sidebar default state, timestamps, character count, and suggestion chips are user-configurable and persisted in `localStorage`.
- **Conversation search** — Filter the sidebar conversation list in real time.

---

## 🚀 Quick Start

```bash
# 1. Clone the repository
git clone https://github.com/your-org/flask-chatbot-ui.git
cd flask-chatbot-ui

# 2. Install Python dependencies
pip install -r requirements.txt

# 3. Run the development server
python app.py
```

Open **http://localhost:8080** in your browser, enter your API key and model name in the settings panel, and start chatting.

---

## 📦 Installation

### Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.10+ | Earlier versions are untested |
| pip | any | Comes with Python |
| Docker | 20.10+ | Optional — only needed for sandbox containers |
| Node.js | 22 (slim) | Only if you build the sandbox image yourself |

### Step-by-step

**1. Clone and enter the project directory**

```bash
git clone https://github.com/yossifibrahem/lumen-ai-chat
cd lumen-ai-chat
```

**2. (Recommended) Create a virtual environment**

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
```

**3. Install dependencies**

```bash
pip install -r requirements.txt
```

The `requirements.txt` pins:

```
flask>=3.0.0
flask-cors>=4.0.0
openai>=1.30.0
mcp>=1.0.0
```

**4. (Optional) Build the sandbox Docker image**

If you want the model to be able to execute code in an isolated container, build the sandbox image once:

```bash
docker build -f Dockerfile.sandbox -t lumen-sandbox .
```

Rebuild whenever `Dockerfile.sandbox` changes.

**5. Start the server**

```bash
python app.py
```

The app starts on `http://0.0.0.0:8080` with `debug=True`. For production, run behind a WSGI server such as Gunicorn:

```bash
gunicorn -w 4 -b 0.0.0.0:8080 "app:create_app()"
```

---

## ⚙️ Configuration

### API settings (in-app)

All API settings are configured through the **Settings** panel in the UI — no `.env` file is required:

| Setting | Description |
|---|---|
| **API Key** | Your provider's API key (e.g. `sk-...` for OpenAI) |
| **Base URL** | Defaults to `https://api.openai.com/v1`; change for Anthropic proxies, Ollama (`http://localhost:11434/v1`), etc. |
| **Model** | Any model ID returned by the `/v1/models` endpoint |
| **System prompt** | Optional system-level instruction prepended to every conversation |

### Environment variables

Override defaults for Docker sandbox behaviour without editing source:

| Variable | Default | Description |
|---|---|---|
| `lumen_SANDBOX_IMAGE` | `lumen-sandbox` | Docker image used for per-conversation containers |
| `lumen_CONTAINERS_ROOT` | `~/.lumen/containers` | Host path for container workspace volumes |
| `lumen_CONTAINER_MEMORY` | `512m` | Memory limit per sandbox container |
| `lumen_CONTAINER_CPUS` | `1` | CPU quota per sandbox container |
| `lumen_CONTAINER_NETWORK` | `bridge` | Docker network mode for sandbox containers |
| `lumen_CONTAINER_PREFIX` | `lumen-chat-` | Prefix for auto-named containers |

### MCP tool servers (`mcp.json`)

Create `mcp.json` in the project root (or manage it through the **MCP** panel in the UI):

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp/workspace"]
    },
    "brave-search": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-brave-search"],
      "env": {
        "BRAVE_API_KEY": "your-key-here"
      }
    }
  }
}
```

Tools are discovered automatically on each conversation load and injected into the model's available tool list.

### Persistent data locations

All data is stored under `~/.lumen/` by default:

```
~/.lumen/
├── conversations/   # One JSON file per conversation
├── containers/      # Docker workspace volumes (one dir per conversation)
└── images/          # Uploaded images, keyed by SHA-256 hash
```

---

## 💻 Usage Examples

### Basic chat

1. Open `http://localhost:8080`
2. Click **New Chat** in the sidebar
3. Click the ⚙️ settings icon, enter your API key and select a model
4. Type a message and press **Enter** (or **Shift+Enter** for a new line)

### Voice input

Click the microphone button to start dictating. lumen uses the browser's Web Speech API to transcribe in real time and appends the transcript to the message box. Press the mic button again to stop.

### Uploading files to a conversation

Open the **Files** panel (folder icon in the toolbar). Drag-and-drop files or click **Upload**. Files land in the conversation's isolated workspace directory and are accessible to MCP tools or sandbox code.

### Using MCP tools

1. Open the **MCP** panel in the UI
2. Add a server entry (name, command, args, env)
3. Save — tools are listed immediately
4. Ask the model to use a tool: the tool call, arguments, and result are all shown inline in the chat

### Cancelling a response

Click the **Stop** button (■) that appears in the toolbar while a response is streaming. The partial response is saved to the conversation history.

### Switching models mid-conversation

Open Settings at any time and change the model. The new model takes effect from the very next message; the full conversation history is replayed in the API call.

---

## 🧪 Running Tests

lumen does not currently ship a test suite. To add one, the recommended approach is:

```bash
pip install pytest pytest-flask
```

Then create a `tests/` directory and use Flask's built-in test client:

```python
# tests/test_routes.py
import pytest
from app import create_app

@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client

def test_index(client):
    response = client.get("/")
    assert response.status_code == 200

def test_list_conversations(client):
    response = client.get("/api/conversations")
    assert response.status_code == 200
    assert isinstance(response.get_json(), list)
```

Run with:

```bash
pytest -v
```

Contributions that add test coverage are especially welcome — see [Contributing](#-contributing) below.

---

## 📝 Contributing

Contributions are welcome! Here's how to get started:

**1. Fork and clone**

```bash
git clone https://github.com/your-org/flask-chatbot-ui.git
cd flask-chatbot-ui
```

**2. Create a feature branch**

```bash
git checkout -b feature/your-feature-name
```

**3. Make your changes**

- Backend logic lives in the Python modules (`routes.py`, `chat_turn_service.py`, etc.)
- Frontend JS is organised as ES modules under `static/js/`
- Keep route handlers thin — heavy logic belongs in service modules
- New MCP adapter patterns go in `mcp_adapters.py`

**4. Test your changes**

Run the dev server and manually verify the feature works end-to-end. If you write automated tests (very appreciated!), run `pytest` before opening a PR.

**5. Open a pull request**

Describe *what* the change does and *why*. Link any related issues. PRs should:
- Be focused on a single concern
- Not break existing functionality
- Include a brief description of manual testing performed

**Reporting bugs:** Open a GitHub Issue with steps to reproduce, the Python/browser version, and any relevant console output.

---

## 📄 License

This project is released under the [MIT License](LICENSE).

```
MIT License

Copyright (c) 2024 lumen Contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

---

*Built with Flask, love, and a healthy distrust of vendor lock-in.*
