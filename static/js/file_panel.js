// Workspace file panel — browse files inside the per-chat /workspace.

import { api } from './api.js';
import { STORAGE_KEYS, state } from './state.js';
import { ICONS } from './icons.js';
import { applyMarkdown, codeFenceFor } from './markdown.js';
import { showToast } from './ui.js';
import { storage } from './storage.js';
import { escapeHtml, formatBytes, fileExtension as ext } from './format.js';

const PANEL_WIDTH_KEY = 'lumen_file_panel_width';
const MIN_PANEL_WIDTH = 280;
const DEFAULT_PANEL_WIDTH = 380;

let currentPath = '/workspace';
let selectedPath = null;
let isOpen = false;

const els = () => ({
  panel:    document.getElementById('file-panel'),
  resizer:  document.getElementById('file-panel-resizer'),
  toggle:   document.getElementById('btn-toggle-files'),
  close:    document.getElementById('btn-close-files'),
  refresh:  document.getElementById('btn-refresh-files'),
  previewRefresh: document.getElementById('btn-refresh-files-preview'),
  previewClose: document.getElementById('btn-close-files-preview'),
  back:     document.getElementById('btn-back-files'),
  path:     document.getElementById('file-panel-path'),
  list:     document.getElementById('file-panel-list'),
  title:    document.getElementById('file-preview-title'),
  meta:     document.getElementById('file-preview-meta'),
  body:     document.getElementById('file-preview-body'),
  copy:     document.getElementById('btn-copy-file'),
  download: document.getElementById('btn-download-file'),
});

function maxPanelWidth() {
  return Math.max(MIN_PANEL_WIDTH, Math.min(Math.round(window.innerWidth * 0.72), 920));
}

function clampPanelWidth(width) {
  return Math.min(Math.max(width, MIN_PANEL_WIDTH), maxPanelWidth());
}

function applyPanelWidth(width) {
  const { panel } = els();
  if (!panel) return;
  const nextWidth = clampPanelWidth(Number(width) || DEFAULT_PANEL_WIDTH);
  panel.style.setProperty('--file-panel-w', `${nextWidth}px`);
}

function loadSavedPanelWidth() {
  const saved = Number(localStorage.getItem(PANEL_WIDTH_KEY));
  applyPanelWidth(saved || DEFAULT_PANEL_WIDTH);
}

function savePanelWidth(width) {
  const nextWidth = clampPanelWidth(width);
  localStorage.setItem(PANEL_WIDTH_KEY, String(nextWidth));
  applyPanelWidth(nextWidth);
}

function formatDate(seconds) {
  if (!seconds) return '';
  return new Date(seconds * 1000).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' });
}

function languageFromName(name = '') {
  const map = {
    js: 'javascript', mjs: 'javascript', jsx: 'javascript', ts: 'typescript', tsx: 'typescript',
    py: 'python', rb: 'ruby', rs: 'rust', go: 'go', java: 'java', c: 'c', h: 'c', cpp: 'cpp', hpp: 'cpp',
    cs: 'csharp', php: 'php', sh: 'bash', bash: 'bash', css: 'css', html: 'html', htm: 'html',
    json: 'json', yaml: 'yaml', yml: 'yaml', xml: 'xml', sql: 'sql', md: 'markdown', toml: 'toml',
  };
  return map[ext(name)] || '';
}

function isMarkdown(name = '') {
  return ['md', 'markdown'].includes(ext(name));
}

function isMissingWorkspacePath(error = '') {
  return ['Path not found', 'File not found', 'Path is not a file'].includes(error);
}

function setPanelOpen(open, { persist = true } = {}) {
  isOpen = open;
  if (persist) storage.set(STORAGE_KEYS.filePanelOpen, open);
  const { panel, toggle } = els();
  panel?.classList.toggle('open', open);
  toggle?.classList.toggle('active', open);

  if (open) {
    refreshFilePanel({ keepPreview: Boolean(selectedPath) }).catch(() => {});
  }
}

function setPreviewOpen(open) {
  const { panel } = els();
  panel?.classList.toggle('preview-open', open);
}

function resetPreview() {
  const { title, meta, body, copy, download } = els();
  selectedPath = null;
  title.textContent = 'Preview';
  meta.textContent = '';
  body.innerHTML = '';
  copy.disabled = true;
  copy.removeAttribute('data-content');
  download.disabled = true;
  download.removeAttribute('data-path');
}

function closePreview() {
  resetPreview();
  setPreviewOpen(false);
}

function setEmptyPreview(message = 'Select a file to preview it here.') {
  const { title, meta, body, copy, download } = els();
  selectedPath = null;
  title.textContent = 'Preview';
  meta.textContent = '';
  body.innerHTML = `<div class="file-panel-empty">${escapeHtml(message)}</div>`;
  copy.disabled = true;
  copy.removeAttribute('data-content');
  download.disabled = true;
  download.removeAttribute('data-path');
}

function renderList(payload) {
  const { list, path } = els();
  path.textContent = payload.path || currentPath;
  list.innerHTML = '';

  if (payload.parent) {
    list.appendChild(fileRow({ name: '..', path: payload.parent, type: 'directory', size: null }, true));
  }

  if (!payload.entries?.length && !payload.parent) {
    list.innerHTML = '<div class="file-panel-empty">No files yet. Tool output and uploads will appear here.</div>';
    return;
  }

  payload.entries.forEach(entry => list.appendChild(fileRow(entry)));
  if (payload.truncated) {
    const note = document.createElement('div');
    note.className = 'file-panel-note';
    note.textContent = payload.limit ? `Showing the first ${payload.limit} entries.` : 'Showing a partial list.';
    list.appendChild(note);
  }
}

function fileRow(entry, isParent = false) {
  const row = document.createElement('button');
  row.className = `file-row ${entry.type === 'directory' ? 'is-dir' : 'is-file'}${entry.path === selectedPath ? ' active' : ''}`;
  row.title = entry.path;
  row.innerHTML = `
    <span class="file-row-icon">${entry.type === 'directory' ? ICONS.mcpFileSystem : ICONS.file}</span>
    <span class="file-row-main">
      <span class="file-row-name">${escapeHtml(entry.name)}</span>
      <span class="file-row-sub">${entry.type === 'directory' ? (isParent ? 'Parent folder' : 'Folder') : formatBytes(entry.size)}</span>
    </span>`;
  row.addEventListener('click', () => {
    if (entry.type === 'directory') loadFileList(entry.path);
    else loadFilePreview(entry.path);
  });
  return row;
}

async function loadFileList(path = currentPath, { fallbackToRoot = true } = {}) {
  const { list } = els();
  if (!state.convId) {
    currentPath = '/workspace';
    list.innerHTML = '<div class="file-panel-empty">Start or open a chat to browse its workspace.</div>';
    setEmptyPreview('Workspace files will appear after a chat exists.');
    setPreviewOpen(false);
    return;
  }

  currentPath = path || '/workspace';
  if (!list.children.length) {
    list.innerHTML = '<div class="file-panel-empty">Loading files…</div>';
  }
  const payload = await api.get(`/api/conversations/${encodeURIComponent(state.convId)}/files?path=${encodeURIComponent(currentPath)}`);
  if (payload.error) {
    if (payload.error === 'Path not found' && fallbackToRoot && currentPath !== '/workspace') {
      currentPath = '/workspace';
      return loadFileList('/workspace', { fallbackToRoot: false });
    }
    list.innerHTML = `<div class="file-panel-empty">${escapeHtml(payload.error)}</div>`;
    return false;
  }
  currentPath = payload.path || currentPath;
  renderList(payload);
  return true;
}

async function loadFilePreview(path) {
  if (!state.convId || !path) return;
  selectedPath = path;
  setPreviewOpen(true);

  const { body, title, meta, copy, download } = els();
  if (!body.children.length) {
    body.innerHTML = '<div class="file-panel-empty">Loading preview…</div>';
  }
  copy.disabled = true;
  copy.removeAttribute('data-content');
  download.disabled = true;
  download.removeAttribute('data-path');

  const data = await api.get(`/api/conversations/${encodeURIComponent(state.convId)}/files/content?path=${encodeURIComponent(path)}`);
  if (data.error) {
    if (isMissingWorkspacePath(data.error)) {
      closePreview();
      await loadFileList(currentPath);
      showToast('Previewed file is no longer available');
      return false;
    }
    setEmptyPreview(data.error);
    setPreviewOpen(true);
    return false;
  }

  title.textContent = data.name || 'File';
  meta.textContent = [formatBytes(data.size), formatDate(data.modified)].filter(Boolean).join(' · ');
  download.disabled = false;
  download.dataset.path = data.path;

  if (!data.previewable) {
    body.innerHTML = `
      <div class="file-panel-empty">
        This file cannot be previewed as text.<br />
        <span>Use Download to save it.</span>
      </div>`;
    return true;
  }

  copy.disabled = false;
  copy.dataset.content = data.content || '';

  const preview = document.createElement('div');
  preview.className = `file-preview-content msg-content${isMarkdown(data.name) ? '' : ' file-preview-code'}`;
  body.innerHTML = '';
  body.appendChild(preview);

  const language = languageFromName(data.name);
  const markdown = isMarkdown(data.name) ? data.content || '' : codeFenceFor(data.content || '', language);
  applyMarkdown(preview, markdown, { copyCodeButtons: false });
  return true;
}

function initPanelResize() {
  const { panel, resizer } = els();
  if (!panel || !resizer) return;

  loadSavedPanelWidth();
  window.addEventListener('resize', () => applyPanelWidth(localStorage.getItem(PANEL_WIDTH_KEY) || DEFAULT_PANEL_WIDTH));

  resizer.addEventListener('pointerdown', event => {
    if (window.innerWidth <= 1024) return;
    event.preventDefault();
    resizer.setPointerCapture?.(event.pointerId);
    panel.classList.add('resizing');
    document.body.classList.add('file-panel-resizing');

    const onMove = moveEvent => {
      const width = window.innerWidth - moveEvent.clientX;
      applyPanelWidth(width);
    };

    const onUp = upEvent => {
      resizer.releasePointerCapture?.(upEvent.pointerId);
      panel.classList.remove('resizing');
      document.body.classList.remove('file-panel-resizing');
      const raw = getComputedStyle(panel).getPropertyValue('--file-panel-w');
      savePanelWidth(parseInt(raw, 10));
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
    };

    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp, { once: true });
  });
}

export async function refreshFilePanel({ keepPreview = true } = {}) {
  const panel = document.getElementById('file-panel');
  if (!panel || !isOpen) return;

  try {
    await loadFileList(currentPath);
    if (keepPreview && selectedPath && panel.classList.contains('preview-open')) {
      await loadFilePreview(selectedPath);
    }
  } catch (err) {
    console.warn('Could not refresh workspace files', err);
  }
}

export function resetFilePanel() {
  currentPath = '/workspace';
  closePreview();
  // Preserve the open/closed panel state; only reset path and preview for the new chat.
}


export function initFilePanel() {
  const { toggle, close, refresh, previewRefresh, previewClose, back, copy, download } = els();
  initPanelResize();
  setPanelOpen(storage.get(STORAGE_KEYS.filePanelOpen, false), { persist: false });
  setEmptyPreview();
  setPreviewOpen(false);

  toggle?.addEventListener('click', () => setPanelOpen(!isOpen));
  const closePanel = () => setPanelOpen(false);
  const refreshPanel = () => refreshFilePanel({ keepPreview: Boolean(selectedPath) })
    .catch(err => showToast(err.message || 'Could not refresh files'));

  close?.addEventListener('click', closePanel);
  previewClose?.addEventListener('click', closePanel);
  back?.addEventListener('click', closePreview);
  refresh?.addEventListener('click', refreshPanel);
  previewRefresh?.addEventListener('click', refreshPanel);

  copy?.addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(copy.dataset.content || '');
      showToast('Copied file content');
    } catch {
      showToast('Copy failed');
    }
  });

  download?.addEventListener('click', () => {
    if (!state.convId || !download.dataset.path) return;

    const link = document.createElement('a');
    link.href = `/api/conversations/${encodeURIComponent(state.convId)}/files/download?path=${encodeURIComponent(download.dataset.path)}`;
    link.download = '';
    link.style.display = 'none';
    document.body.appendChild(link);
    link.click();
    link.remove();
  });

  document.addEventListener('lumen:open-workspace-file', e => {
    const path = e.detail?.path;
    if (!path) return;
    setPanelOpen(true);
    loadFilePreview(path).catch(() => {});
  });
}