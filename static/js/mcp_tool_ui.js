// MCP tool UI policy — display labels, argument filtering, and generic JSON result rendering.
// Keep UI-specific MCP behavior here so renderer.js stays mostly orchestration/DOM code.
//
// Per-tool overrides (meta text, arg filtering, result rendering) live in
// tool_adapters/. Add or remove adapters by editing tool_adapters/index.js.

import { adapterFor } from './tool_adapters/index.js';

export function escapeHtml(value) {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

export function getToolDisplayLabel(toolName, args = {}) {
  const description = String(args?.description || '').trim();
  return description || toolName;
}

export function getToolMetaText(toolName, args = {}) {
  const adapter = adapterFor(toolName);
  return adapter?.getMetaText?.(args) ?? '';
}

function normalizeBlockText(value) {
  return String(value ?? '')
    .replace(/\r\n?/g, '\n')
    .replace(/^\s*\n+/, '')
    .replace(/\n+\s*$/, '');
}

function formatToolValue(value) {
  if (value == null) return '';
  if (typeof value === 'object') return normalizeBlockText(JSON.stringify(value, null, 2));
  return normalizeBlockText(value);
}

export function visibleToolArgs(toolNameOrArgs, args) {
  // Support legacy two-arg call (toolName, args) and original one-arg call (args).
  let toolName, rawArgs;
  if (typeof toolNameOrArgs === 'string') {
    toolName = toolNameOrArgs;
    rawArgs  = args ?? {};
  } else {
    toolName = null;
    rawArgs  = toolNameOrArgs ?? {};
  }

  if (!rawArgs || typeof rawArgs !== 'object') return {};

  // Strip the `description` sentinel that the model injects for the UI label.
  const withoutDescription = Object.fromEntries(
    Object.entries(rawArgs).filter(([key]) => key !== 'description')
  );

  // Delegate to the adapter's filterArgs if one is registered.
  if (toolName) {
    const adapter = adapterFor(toolName);
    if (adapter?.filterArgs) return adapter.filterArgs(withoutDescription);
  }

  return withoutDescription;
}

export function formatArgsHtml(args = {}) {
  return Object.entries(args).map(([key, value]) => `
    <div class="arg-item">
      <span class="arg-name">${escapeHtml(key)}</span>
      <pre class="arg-value">${escapeHtml(formatToolValue(value))}</pre>
    </div>`).join('');
}

function parseToolJson(value) {
  if (value && typeof value === 'object') return value;
  if (typeof value !== 'string') return null;
  const text = value.trim();
  if (!text || !/^[\[{]/.test(text)) return null;
  try { return JSON.parse(text); } catch { return null; }
}

function renderJsonResult(data) {
  if (Array.isArray(data)) {
    return `<div class="tr-command-result"><pre class="tr-result">${escapeHtml(formatToolValue(data))}</pre></div>`;
  }

  const entries = Object.entries(data || {});
  if (!entries.length) {
    return `<pre class="tr-result">${escapeHtml(formatToolValue(data))}</pre>`;
  }

  const blocks = entries.map(([key, value]) => `
    <div>
      <div class="tr-section-label">${escapeHtml(key)}</div>
      <pre class="tr-result">${escapeHtml(formatToolValue(value))}</pre>
    </div>`).join('');

  return `<div class="tr-command-result">${blocks}</div>`;
}

export function renderToolResultHtml(result, toolName = null, args = {}) {
  // Let the registered adapter take first shot at rendering.
  if (toolName) {
    const adapter = adapterFor(toolName);
    const custom = adapter?.renderResult?.(result, args);
    if (custom != null) return custom;
  }

  const data = parseToolJson(result);
  return data
    ? renderJsonResult(data)
    : `<pre class="tr-result">${escapeHtml(formatToolValue(result))}</pre>`;
}
