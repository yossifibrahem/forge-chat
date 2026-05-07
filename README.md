
# Forge chat

A Flask-based chatbot application with support for MCP servers, real-time streaming responses, file handling, workspace management, and an interactive web UI.

## 📋 Project Description

**Forge chat** is a web-based chatbot application built with Flask. It provides a clean chat interface for interacting with AI models while supporting advanced capabilities through MCP servers.

The application is designed to support real-time AI streaming, persistent conversations, file uploads, workspace file access, and tool execution through MCP integrations. It is suitable for local AI workflows, developer assistants, research tools, automation dashboards, and experimental AI applications.

The goal of this project is to provide a modular, maintainable, and extensible chatbot foundation that can be customized for different AI providers, MCP tools, and user workflows.

---

## ✨ Features

- Real-time streaming AI responses
- Persistent chat conversations
- Conversation title generation
- MCP server integration
- Native-style tool execution support
- File upload support
- Workspace file preview and download links
- Markdown rendering for assistant responses
- Reasoning and tool-call UI blocks
- Conversation switching without losing active assistant turns
- Backend-managed assistant turns independent of the active UI chat
- Modular Flask backend architecture
- Clean JavaScript frontend modules
- Configurable AI model/provider settings
- Local workspace isolation for generated files
- Lightweight and customizable UI

---

## 🚀 Quick Start

Clone the repository:

```bash
git clone <repository-url>
cd <project-folder>
````

Create a virtual environment:

```bash
python -m venv .venv
```

Activate the virtual environment:

```bash
# macOS / Linux
source .venv/bin/activate

# Windows
.venv\Scripts\activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Run the application:

```bash
python app.py
```

Open the app in your browser:

```text
http://localhost:5000
```

---

## 📦 Installation

### Requirements

Make sure you have the following installed:

* Python 3.10+
* pip
* Node.js, if using Node-based MCP servers
* An AI provider or local model server compatible with the project configuration
* Optional: Docker, if your workspace or MCP setup uses containers

### Install Python Dependencies

```bash
pip install -r requirements.txt
```

### Install MCP Server Dependencies

If your MCP servers are Node.js-based, install their dependencies separately:

```bash
cd path/to/mcp-server
npm install
npm run build
```

Repeat this for each MCP server used by the application.

---

## ⚙️ Configuration

Configuration may be handled through environment variables, local config files, or application settings depending on your setup.

Common configuration values include:

```env
FLASK_ENV=development
SECRET_KEY=your-secret-key

AI_API_BASE_URL=http://localhost:1234/v1
AI_API_KEY=your-api-key
DEFAULT_MODEL=your-model-name

WORKSPACE_DIR=/path/to/workspace
MCP_CONFIG_PATH=/path/to/mcp.json
```

### MCP Configuration

MCP servers can be configured using a JSON file such as `mcp.json`.

Example:

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "node",
      "args": [
        "/path/to/filesystem-mcp-server/dist/index.js"
      ],
      "env": {
        "WORKING_DIR": "/path/to/workspace"
      }
    },
    "bash": {
      "command": "node",
      "args": [
        "/path/to/bash-mcp-server/dist/index.js"
      ],
      "env": {
        "WORKING_DIR": "/path/to/workspace"
      }
    }
  }
}
```

### Workspace Configuration

The workspace is used for uploaded files, generated files, and files returned by tools.

Recommended behavior:

```text
/workspace
```

Inside the application, files can be referenced using markdown-style links:

```markdown
[Download the file](file:/workspace/example.pdf)
```

The UI can render these links as downloadable file references.

---

## 💻 Usage Examples

### Start a New Conversation

Open the application and click **New Chat**. Enter a message and send it to the assistant.

Example prompt:

```text
Explain how Flask blueprints work and show a simple example.
```

### Upload a File

Use the attach button in the chat input to upload a file. The uploaded file becomes available to the assistant and can also be stored in the workspace.

Example:

```text
Please summarize the uploaded PDF and extract the main action items.
```

### Use MCP Tools

When MCP servers are configured, the assistant can call available tools during a conversation.

Example prompt:

```text
Create a Python script that analyzes this CSV file and saves a chart in the workspace.
```

The assistant may use filesystem or shell tools to inspect files, run commands, and generate outputs.

### Download Generated Files

When a tool or assistant creates a file, it can return a link like:

```markdown
[Download the report](file:/workspace/report.pdf)
```

Clicking the link downloads the file from the workspace.

---

## 🧪 Running Tests

If the project includes tests, run them with:

```bash
pytest
```

For verbose output:

```bash
pytest -v
```

To run a specific test file:

```bash
pytest tests/test_chat.py
```

### Code Quality Checks

Recommended checks:

```bash
python -m py_compile app.py
```

If the project uses JavaScript modules, you can validate syntax with:

```bash
node --check static/js/chat.js
node --check static/js/renderer.js
node --check static/js/conversations.js
```

For larger projects, consider adding:

```bash
ruff check .
black .
pytest
```

---

## 📝 Contributing

Contributions are welcome.

To contribute:

1. Fork the repository.
2. Create a new branch:

```bash
git checkout -b feature/your-feature-name
```

3. Make your changes.
4. Run tests and checks.
5. Commit your changes:

```bash
git commit -m "Add your feature"
```

6. Push your branch:

```bash
git push origin feature/your-feature-name
```

7. Open a pull request.

### Contribution Guidelines

Please keep contributions focused and maintainable.

Good contributions should:

* Reduce unnecessary complexity
* Preserve existing behavior unless intentionally changed
* Keep backend and frontend responsibilities separated
* Avoid large unrelated rewrites
* Include tests where practical
* Keep UI changes consistent with the existing design

---

## 📄 License

This project is licensed under the **[LICENSE NAME]** license.

See the `LICENSE` file for more details.

---

## Notes

This project is intended to be easy to extend. The recommended architecture is:

```text
Backend routes handle HTTP only.
Services contain business logic.
Frontend modules handle UI state and rendering.
MCP integrations stay isolated from core chat logic.
Workspace logic stays separate from chat logic.
```

Keeping these boundaries clear makes the project easier to debug, refactor, and expand.
