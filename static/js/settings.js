// Settings — API + Chat behaviour settings persisted to localStorage.

import { state, SETTINGS_DEFAULTS, STORAGE_KEYS } from './state.js';
import { storage } from './storage.js';
import { api }     from './api.js';
import { showStatus, showToast } from './ui.js';

// ── Read / write ──────────────────────────────────────────────────────────────

const SETTINGS_KEYS = Object.keys(SETTINGS_DEFAULTS);

export function loadSettings() {
  Object.assign(state, SETTINGS_DEFAULTS, _savedSettings());

  const cachedModels = storage.get(STORAGE_KEYS.models);
  renderModelList(cachedModels || []);

  _syncAPIUI();
  _syncChatUI();
  updateModelBadge();
  updateInputHint();
}

export function saveSettings() {
  _readAPIControls();
  _persistSettings();
  updateModelBadge();
  showStatus('settings-status', 'Settings saved ✓', 'ok');
  showToast('Settings saved');
}

export function saveChatSettings() {
  _readChatControls();
  _persistSettings();
  updateInputHint();
  showToast('Chat settings saved');
}

export function updateInputHint() {
  const hint = document.querySelector('.input-hint');
  if (!hint) return;
  hint.textContent = state.enterToSend ? '⏎ send · ⇧⏎ newline' : '⏎ newline · ⇧⏎ send';
}

function _savedSettings() {
  const saved = storage.get(STORAGE_KEYS.settings, {});
  return Object.fromEntries(SETTINGS_KEYS.map(key => [key, saved[key]]).filter(([, v]) => v !== undefined));
}

function _persistSettings() {
  storage.set(STORAGE_KEYS.settings, Object.fromEntries(SETTINGS_KEYS.map(key => [key, state[key]])));
}

// ── Model list ────────────────────────────────────────────────────────────────

let _modelFetchId = 0;

export async function fetchModels() {
  const fetchId = ++_modelFetchId;
  const btn = document.getElementById('btn-fetch-models');
  btn.disabled = true;
  _setModelStatus('Loading models…', 'Checking the API connection.', 'ok');

  try {
    const data = await api.post('/api/models', {
      api_base: document.getElementById('api-base').value.trim(),
      api_key:  document.getElementById('api-key').value.trim(),
    });
    if (fetchId !== _modelFetchId) return;

    if (data.error) {
      _setModelStatus('Could not load models', data.error, 'err');
      return;
    }

    const models = data.models || [];
    storage.set(STORAGE_KEYS.models, models);
    renderModelList(models);
    _setModelStatus(models.length ? 'Models loaded' : 'No models found', '', models.length ? 'ok' : 'err');
  } catch (err) {
    if (fetchId === _modelFetchId) _setModelStatus('Could not load models', err.message, 'err');
  } finally {
    if (fetchId === _modelFetchId) btn.disabled = false;
  }
}

export function renderModelList(models = []) {
  _renderModelRows(document.getElementById('model-list'), models);
  _renderChips(document.getElementById('mp-model-list'), 'mp-chip', models);
}

function _renderModelRows(container, models) {
  if (!container) return;
  if (!models.length) {
    container.innerHTML = '<div class="model-empty">No models found</div>';
    return;
  }

  container.innerHTML = models.map(m =>
    `<button class="model-row${m === state.model ? ' selected' : ''}" data-model="${_escape(m)}" title="${_escape(m)}"><span>${_escape(m)}</span></button>`
  ).join('');

  container.querySelectorAll('.model-row').forEach(row => {
    row.addEventListener('click', () => _chooseModel(row.dataset.model, models));
  });
}

function _renderChips(container, chipClass, models) {
  if (!container) return;
  if (!models.length) {
    container.innerHTML = '<span class="mp-empty">No models — fetch them in API settings</span>';
    return;
  }
  container.innerHTML = models.map(m =>
    `<div class="${chipClass}${m === state.model ? ' selected' : ''}" data-model="${_escape(m)}" title="${_escape(m)}">${_escape(m)}</div>`
  ).join('');

  container.querySelectorAll(`.${chipClass}`).forEach(chip => {
    chip.addEventListener('click', () => _chooseModel(chip.dataset.model, models));
  });
}

function _chooseModel(model, models) {
  state.model = model;
  renderModelList(models);
  updateModelBadge();
  saveSettings();
}

function _setModelStatus(title, detail, type) {
  const el = document.getElementById('settings-status');
  if (!el) return;
  el.className = `status-msg ${type}`;
  el.innerHTML = `<strong>${_escape(title)}</strong>${detail ? `<span>${_escape(detail)}</span>` : ''}`;
  el.style.display = 'block';
}

function _escape(value) {
  return String(value).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

function updateModelBadge() {
  document.getElementById('model-badge-label').textContent = state.model || 'No model';
}

// ── Show/hide API key ─────────────────────────────────────────────────────────

export function initKeyToggle() {
  const btn   = document.getElementById('btn-toggle-key');
  const input = document.getElementById('api-key');
  const show  = document.getElementById('eye-icon-show');
  const hide  = document.getElementById('eye-icon-hide');
  if (!btn || !input) return;

  btn.addEventListener('click', () => {
    const isHidden = input.type === 'password';
    input.type  = isHidden ? 'text' : 'password';
    // Spans use data-icon and were hydrated by initIcons(); just toggle visibility
    if (show) show.style.display = isHidden ? 'none' : '';
    if (hide) hide.style.display = isHidden ? '' : 'none';
  });
}

// ── Temperature slider live badge ─────────────────────────────────────────────

export function initParameterSliders() {
  const tempSlider  = document.getElementById('setting-temperature');
  const tempBadge   = document.getElementById('temp-badge');
  if (tempSlider && tempBadge) {
    tempSlider.addEventListener('input', () => {
      tempBadge.textContent = parseFloat(tempSlider.value).toFixed(2);
    });
  }
}

// ── Private helpers ───────────────────────────────────────────────────────────

function _syncAPIUI() {
  const el = id => document.getElementById(id);
  el('api-base').value = state.apiBase;
  el('api-key').value  = state.apiKey;

  const temp = el('setting-temperature');
  if (temp) { temp.value = state.temperature; }
  const tempBadge = el('temp-badge');
  if (tempBadge) tempBadge.textContent = parseFloat(state.temperature).toFixed(2);
}

function _syncChatUI() {
  const el = id => document.getElementById(id);
  el('system-prompt').value = state.systemPrompt;

  _setCheckbox('setting-auto-titles',     state.autoGenerateTitles);
  _setCheckbox('setting-enter-send',      state.enterToSend);
  _setCheckbox('setting-auto-scroll',     state.autoScrollStreaming);
}

function _readAPIControls() {
  state.apiBase        = document.getElementById('api-base').value.trim();
  state.apiKey         = document.getElementById('api-key').value.trim();

  const temp = document.getElementById('setting-temperature');
  if (temp) state.temperature = parseFloat(temp.value);
}

function _readChatControls() {
  state.systemPrompt        = document.getElementById('system-prompt')?.value.trim()          ?? state.systemPrompt;
  state.autoGenerateTitles  = document.getElementById('setting-auto-titles')?.checked          ?? state.autoGenerateTitles;
  state.enterToSend         = document.getElementById('setting-enter-send')?.checked           ?? state.enterToSend;
  state.autoScrollStreaming = document.getElementById('setting-auto-scroll')?.checked          ?? state.autoScrollStreaming;
}

function _setCheckbox(id, value) {
  const el = document.getElementById(id);
  if (el) el.checked = !!value;
}
