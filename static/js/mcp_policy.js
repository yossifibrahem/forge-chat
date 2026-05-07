// MCP model prompt policy — local workspace semantics and description-first tool labels.
// Add/remove server-specific model guidance here instead of editing chat.js.

export function buildMcpSystemPrompt({ tools = [], isServerEnabled = () => true } = {}) {
  const enabledTools = tools.filter(tool => isServerEnabled(tool.server));
  if (!enabledTools.length) return '';

  const toolNames = enabledTools.map(tool => `${tool.server}.${tool.name}`).join(', ');
  return [
    'MCP tools are available in this chat: ' + toolNames + '.',
    'Local MCP servers are started with this conversation\'s workspace as WORKING_DIR/PWD/cwd: ~/.lumen/working_directory/<chat_id>. Filesystem path sandboxing is handled by the filesystem MCP server itself; prefer relative paths like README.md or src/app.py unless the server documentation says otherwise. For bash commands, the process starts inside the same chat workspace.',
    'For every MCP tool call, always provide a concise, human-readable `description` argument first. This description is shown in the chat UI as the live action label, for example: "Reading README.md", "Creating src/app.py", or "Installing packages with npm".',
    'For filesystem edits, view the target file immediately before str_replace, then re-view after successful edits before making further edits to the same file.',
    'Use bash tools for commands and filesystem tools for precise file reads/writes/edits. Keep commands scoped to the chat working directory unless the user clearly requests otherwise.',
  ].join('\n');
}
