// MCP model prompt policy — local workspace semantics and description-first tool labels.
// Add/remove server-specific model guidance here instead of editing chat.js.

export function buildMcpSystemPrompt({ tools = [], isServerEnabled = () => true } = {}) {
  const enabledTools = tools.filter(tool => isServerEnabled(tool.server));
  if (!enabledTools.length) return '';

  const toolNames = enabledTools.map(tool => `${tool.server}__${tool.name}`).join(', ');
  return [
    'MCP tools are available in this chat: ' + toolNames + '.',
    'MCP servers run inside this chat\'s Docker container. Tools use WORKING_DIR/PWD=/workspace, persisted on the host at ~/.lumen/containers/<chat_id>. Prefer relative paths like README.md or src/app.py unless the server documentation says otherwise. Keep commands scoped to the active workspace.',
    'For every MCP tool call, always provide a concise, human-readable `description` argument first. This description is shown in the chat UI as the live action label, for example: "Reading README.md", "Creating src/app.py", or "Installing packages with npm".',
    'For filesystem edits, view the target file immediately before str_replace, then re-view after successful edits before making further edits to the same file.',
    'Use bash tools for commands and filesystem tools for precise file reads/writes/edits. Keep commands scoped to the chat working directory unless the user clearly requests otherwise.',
    'When you create a file that the user should download, save it inside /workspace and mention it as a normal Markdown link using a file: URL, for example: [Download the file](file:/workspace/path/to/file.ext). Only use this syntax for files that already exist in /workspace. Do not invent download URLs, do not paste base64 file contents, and do not use the syntax for directories.',
  ].join('\n');
}
