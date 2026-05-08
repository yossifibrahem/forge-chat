/**
 * Tool Adapter Registry
 *
 * Central store for per-tool UI overrides. Each adapter may override any
 * combination of three extension points:
 *
 *   getMetaText(args)          → string
 *     Short inline preview shown next to the tool name in the strip header
 *     (e.g. the command for bash, the file path for filesystem tools).
 *     Return '' to show nothing.
 *
 *   filterArgs(args)           → object
 *     Return a subset/transformation of the raw args object for display.
 *     The default strips nothing (all args shown).
 *
 *   renderResult(result, args) → string | null
 *     Return custom HTML for the result section, or null to fall through
 *     to the generic JSON/text renderer in mcp_tool_ui.js.
 *
 * Registration:
 *   import { registerAdapter } from './registry.js';
 *   registerAdapter({ tools: ['my_tool'], getMetaText(args) { … } });
 *
 * Lookup (used by mcp_tool_ui.js):
 *   import { adapterFor } from './registry.js';
 *   const adapter = adapterFor('bash_tool');
 */

/** @type {Map<string, Object>} */
const _registry = new Map();

/**
 * Register a tool adapter.
 *
 * @param {Object}   adapter
 * @param {string[]} adapter.tools          - Tool names this adapter handles.
 * @param {Function} [adapter.getMetaText]  - (args) => string
 * @param {Function} [adapter.filterArgs]   - (args) => object
 * @param {Function} [adapter.renderResult] - (result, args) => string | null
 */
export function registerAdapter(adapter) {
  if (!Array.isArray(adapter.tools) || !adapter.tools.length) {
    throw new Error('registerAdapter: adapter.tools must be a non-empty array');
  }
  for (const toolName of adapter.tools) {
    _registry.set(toolName, adapter);
  }
}

/**
 * Look up the adapter for a given tool name.
 * Returns null when no adapter is registered, so callers can fall through
 * to generic behaviour.
 *
 * @param   {string}      toolName
 * @returns {Object|null}
 */
export function adapterFor(toolName) {
  return _registry.get(toolName) ?? null;
}

/**
 * Return all registered tool names (useful for debugging / inspection).
 * @returns {string[]}
 */
export function registeredTools() {
  return [..._registry.keys()];
}
