// MCP server config and tool management.

import { api }     from './api.js';
import { state, STORAGE_KEYS } from './state.js';
import { storage } from './storage.js';
import { escapeHtml }   from './renderer.js';
import { showToast } from './ui.js';
import { ICONS, MCP_ICON_OPTIONS } from './icons.js';

// ── Server settings helpers ───────────────────────────────────────────────────

function loadServerSettings() {
  state.mcpServerSettings = storage.get(STORAGE_KEYS.mcpServerSettings, {});
}

function saveServerSettings() {
  storage.set(STORAGE_KEYS.mcpServerSettings, state.mcpServerSettings);
}

function getServerSetting(serverName) {
  if (!state.mcpServerSettings[serverName]) {
    state.mcpServerSettings[serverName] = { enabled: true, autoApprove: false, icon: 'plug' };
  }
  if (!state.mcpServerSettings[serverName].icon) {
    state.mcpServerSettings[serverName].icon = 'plug';
  }
  return state.mcpServerSettings[serverName];
}

export function isServerEnabled(serverName) {
  return getServerSetting(serverName).enabled !== false;
}

export function isServerAutoApprove(serverName) {
  return getServerSetting(serverName).autoApprove === true;
}

// ── Config ────────────────────────────────────────────────────────────────────

export async function loadMcpConfig() {
  const cfg = await api.get('/api/mcp/config');
  document.getElementById('mcp-config-editor').value = JSON.stringify(cfg, null, 2);
}

export async function saveMcpConfig() {
  try {
    const cfg = JSON.parse(document.getElementById('mcp-config-editor').value);
    await api.post('/api/mcp/config', cfg);
    _setMcpStatus('Config saved ✓', 'ok');
    showToast('MCP config saved');
  } catch (err) {
    _setMcpStatus(`Invalid JSON: ${err.message}`, 'err');
  }
}


// ── Tool loading ──────────────────────────────────────────────────────────────


function normalizeToolsResponse(payload) {
  if (Array.isArray(payload)) return payload;
  if (payload && Array.isArray(payload.tools)) return payload.tools;
  const message = payload?.error || 'Unexpected MCP tools response';
  throw new Error(message);
}

function toolsEndpoint() {
  const params = new URLSearchParams();
  if (state.convId) params.set('conv_id', state.convId);
  const query = params.toString();
  return query ? `/api/mcp/tools?${query}` : '/api/mcp/tools';
}

export function loadCachedTools() {
  loadServerSettings();
  const cached = storage.get(STORAGE_KEYS.mcpTools);
  if (!cached) return;

  try {
    state.mcpTools = normalizeToolsResponse(cached);
    if (state.mcpTools.length) renderToolList();
  } catch {
    state.mcpTools = [];
    storage.remove(STORAGE_KEYS.mcpTools);
  }
}

export async function reloadTools() {
  const btn = document.getElementById('btn-reload-tools');
  if (btn) {
    btn.disabled = true;
    btn.classList.add('loading');
    btn.title = 'Loading tools…';
    btn.setAttribute('aria-label', 'Loading tools');
  }
  _setMcpStatus('Loading tools…', 'ok');

  try {
    const payload = await api.get(toolsEndpoint());
    state.mcpTools = normalizeToolsResponse(payload);
    storage.set(STORAGE_KEYS.mcpTools, state.mcpTools);
    renderToolList();
    _setMcpStatus(state.mcpTools.length ? `${state.mcpTools.length} tool(s) loaded ✓` : 'No tools loaded', state.mcpTools.length ? 'ok' : 'err');
    showToast(`${state.mcpTools.length} tool(s) loaded`);
  } catch (err) {
    state.mcpTools = [];
    storage.remove(STORAGE_KEYS.mcpTools);
    renderToolList();
    _setMcpStatus(`Error loading tools: ${err.message}`, 'err');
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.classList.remove('loading');
      btn.title = 'Reload tools';
      btn.setAttribute('aria-label', 'Reload tools');
    }
  }
}

function _setMcpStatus(message, type) {
  const el = document.getElementById('mcp-status');
  if (!el) return;
  el.textContent = message;
  el.className = `status-msg ${type}`;
  el.style.display = 'block';
}

// ── Render helpers ────────────────────────────────────────────────────────────

function buildToggleHtml(server, action, label, isOn) {
  const onCls = isOn ? 'mcp-toggle-on' : '';
  return `
    <label class="mcp-toggle-label" title="${label}">
      <span class="mcp-toggle-text">${label.split(' ')[0]}</span>
      <button class="mcp-toggle ${onCls}"
              data-server="${escapeHtml(server)}" data-action="${action}"
              aria-pressed="${isOn}" aria-label="Toggle ${action}">
        <span class="mcp-toggle-thumb"></span>
      </button>
    </label>`;
}

function buildIconPickerHtml(server, currentIconKey) {
  const optionsHtml = MCP_ICON_OPTIONS.map(opt => `
    <button class="icon-option${currentIconKey === opt.key ? ' selected' : ''}"
            data-server="${escapeHtml(server)}" data-icon="${opt.key}"
            title="${escapeHtml(opt.label)}" aria-label="${escapeHtml(opt.label)}">
      ${ICONS[opt.key]}
    </button>`).join('');
  return `
    <div class="server-icon-wrap" data-server="${escapeHtml(server)}">
      <button class="server-icon-btn" data-server="${escapeHtml(server)}"
              title="Change server icon" aria-label="Change server icon">
        <span class="server-icon-current">${ICONS[currentIconKey] || ICONS.plug}</span>
      </button>
      <div class="icon-picker-dropdown" style="display:none">
        ${optionsHtml}
      </div>
    </div>`;
}

function buildServerGroupHtml(server, tools, settings) {
  const disabledCls   = settings.enabled ? '' : ' server-disabled';
  const currentIcon   = settings.icon || 'plug';
  const toolsHtml     = tools.map(tool => `
    <div class="tool-card">
      <div class="tool-card-header">
        <span class="tool-card-name">${escapeHtml(tool.name)}</span>
      </div>
      <div class="tool-card-desc">${escapeHtml(tool.description)}</div>
    </div>`).join('');

  return `
    <div class="server-group${disabledCls}" data-server="${escapeHtml(server)}">
      <div class="server-group-header">
        ${buildIconPickerHtml(server, currentIcon)}
        <span class="server-group-name">${escapeHtml(server)}</span>
        <div class="server-group-controls">
          ${buildToggleHtml(server, 'enabled',     'Enable / disable all tools from this server', settings.enabled)}
          ${buildToggleHtml(server, 'autoApprove', 'Auto-approve tool calls from this server without confirmation', settings.autoApprove)}
        </div>
      </div>
      <div class="server-tools">${toolsHtml}</div>
    </div>`;
}

function groupToolsByServer(tools) {
  return tools.reduce((acc, tool) => {
    if (!acc[tool.server]) acc[tool.server] = [];
    acc[tool.server].push(tool);
    return acc;
  }, {});
}

function renderToolList() {
  loadServerSettings();
  const container = document.getElementById('tool-list');

  if (!state.mcpTools.length) {
    container.innerHTML = '<div class="no-tools-label">No tools loaded</div>';
    return;
  }

  const byServer = groupToolsByServer(state.mcpTools);
  container.innerHTML = Object.entries(byServer)
    .map(([server, tools]) => buildServerGroupHtml(server, tools, getServerSetting(server)))
    .join('');

  container.querySelectorAll('.mcp-toggle').forEach(btn => {
    btn.addEventListener('click', () => {
      const setting = getServerSetting(btn.dataset.server);
      setting[btn.dataset.action] = !setting[btn.dataset.action];
      saveServerSettings();
      renderToolList();
    });
  });

  // Icon picker: toggle dropdown visibility
  container.querySelectorAll('.server-icon-btn').forEach(btn => {
    btn.addEventListener('click', e => {
      e.stopPropagation();
      const wrap    = btn.closest('.server-icon-wrap');
      const dropdown = wrap.querySelector('.icon-picker-dropdown');
      const isOpen  = dropdown.style.display !== 'none';
      // Close all open dropdowns first
      container.querySelectorAll('.icon-picker-dropdown').forEach(d => { d.style.display = 'none'; });
      if (!isOpen) dropdown.style.display = 'flex';
    });
  });

  // Icon picker: select an icon option
  container.querySelectorAll('.icon-option').forEach(btn => {
    btn.addEventListener('click', e => {
      e.stopPropagation();
      const setting = getServerSetting(btn.dataset.server);
      setting.icon = btn.dataset.icon;
      saveServerSettings();
      // Dispatch a custom event so renderer.js can update live tool strips
      document.dispatchEvent(new CustomEvent('mcp:icon-changed', {
        detail: { server: btn.dataset.server, iconKey: btn.dataset.icon },
      }));
      renderToolList();
    });
  });

  // Close dropdowns when clicking outside
  document.addEventListener('click', () => {
    container.querySelectorAll('.icon-picker-dropdown').forEach(d => { d.style.display = 'none'; });
  }, { once: true });
}
