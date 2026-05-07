# Lumen — Flask AI Chatbot

A sleek, feature-rich AI chatbot with streaming, Markdown/LaTeX rendering, MCP tool calling, and persistent conversations.

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run
python app.py
# → Open http://localhost:8080
```

## Features

| Feature | Details |
|---|---|
| **Streaming** | Real-time token-by-token response via SSE |
| **Markdown + LaTeX** | Full GitHub Flavored Markdown + KaTeX math rendering |
| **Code Highlighting** | Syntax highlighting via highlight.js with copy button |
| **OpenAI-compatible** | Works with OpenAI, Ollama, LM Studio, Groq, Together, etc. |
| **Model Fetch** | Auto-fetch available models from any API endpoint |
| **Persistent Conversations** | Saved as JSON files in `./conversations/` |
| **MCP Tool Calling** | Configure MCP servers in `mcp.json` |
| **Tool Confirmation** | Every tool call shows name + arguments; requires user approval |

## Settings

Go to **Settings** tab:
- Set your **API Base URL** (e.g., `http://localhost:11434/v1` for Ollama)
- Enter your **API Key**
- Click **Fetch Models** to auto-discover available models
- Click a model chip to select it
- Optionally set a **System Prompt**

## MCP Tool Calling

Edit `mcp.json` or use the **MCP** tab in the UI:

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
      "env": {}
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

Click **Reload Tools** to connect and list available tools. When the model requests a tool, you'll see a confirmation card with the tool name and arguments before anything executes.

## File Structure

```
chatbot/
├── app.py                  # App factory + entry point
├── routes.py               # All HTTP routes (one Blueprint)
├── store.py                # Conversation persistence (file-system CRUD)
├── mcp_service.py          # MCP config, tool discovery, tool invocation
├── streaming.py            # SSE formatting + OpenAI stream loop
├── mcp.json                # MCP server configuration (auto-created)
├── requirements.txt
├── conversations/          # Saved conversations (auto-created)
├── templates/
│   └── index.html          # App shell (no inline CSS or JS)
└── static/
    ├── css/
    │   └── main.css        # All styles
    └── js/
        ├── app.js          # Entry point — event binding + boot
        ├── state.js        # Shared state object + constants
        ├── storage.js      # localStorage wrapper
        ├── api.js          # Typed HTTP client
        ├── markdown.js     # Markdown + LaTeX rendering pipeline
        ├── renderer.js     # DOM rendering (messages, tool dialogs)
        ├── conversations.js# Conversation list, open, create, delete
        ├── settings.js     # Settings load/save, model list
        ├── mcp.js          # MCP config, tool list, tool execution
        ├── chat.js         # SSE stream loop + tool-call orchestration
        └── ui.js           # Toast, modals, sidebar, input helpers
```

## Compatible APIs

- **OpenAI** → `https://api.openai.com/v1`
- **Ollama** → `http://localhost:11434/v1`
- **LM Studio** → `http://localhost:1234/v1`
- **Groq** → `https://api.groq.com/openai/v1`
- **Together AI** → `https://api.together.xyz/v1`
- **Anthropic (via proxy)** → any OpenAI-compatible proxy


## Optimized Bash + Filesystem MCP Setup

Lumen now treats the companion `bash-mcp-server` and `filesystem-mcp-server` as first-class chat tools:

- Each conversation gets an isolated workspace at `~/.lumen/working_directory/<chat_id>`.
- MCP invocations automatically receive that path as `WORKING_DIR`, so relative paths and shell commands stay scoped to the active chat.
- The chat UI displays each tool call by its required `description` argument instead of the raw tool name, e.g. `Reading README.md` or `Installing packages with npm`.

### Recommended local configuration

Build both servers first:

```bash
cd bash-mcp-server-main && npm install && npm run build
cd ../filesystem-mcp-server-main && npm install && npm run build
```

Then open **Settings → MCP Servers**, add the built server paths manually in `mcp.json`, click **Save Config**, then **Reload Tools**:

```json
{
  "mcpServers": {
    "BASH_MCP_SERVER": {
      "command": "node",
      "args": ["/absolute/path/to/bash-mcp-server-main/dist/index.js"],
      "env": {}
    },
    "FILESYSTEM_MCP_SERVER": {
      "command": "node",
      "args": ["/absolute/path/to/filesystem-mcp-server-main/dist/index.js"],
      "env": {}
    }
  }
}
```
