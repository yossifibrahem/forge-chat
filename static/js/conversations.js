// Conversation management — talking to /api/conversations and updating the sidebar.

import { api }         from './api.js';
import { state, STORAGE_KEYS } from './state.js';
import { storage } from './storage.js';
import { clearMessages, renderAllMessages } from './renderer.js';
import { toggleSidebar } from './ui.js';
import { ICONS } from './icons.js';
import { escapeHtml } from './format.js';
import { refreshFilePanel, resetFilePanel } from './file_panel.js';

// ── Sidebar list ──────────────────────────────────────────────────────────────

export async function loadConversationList() {
  const list      = await api.get('/api/conversations');
  const container = document.getElementById('conv-list');
  container.innerHTML = '';

  // Re-apply search filter after reload if there's an active query
  const searchInput = document.getElementById('conv-search');
  const query = searchInput ? searchInput.value.trim().toLowerCase() : '';

  if (!list.length) {
    container.innerHTML = '<div class="conv-section-label conv-empty">No conversations yet</div>';
    return;
  }

  container.appendChild(
    Object.assign(document.createElement('div'), { className: 'conv-section-label', textContent: 'Recent' })
  );
  list.forEach(conv => {
    const item = _buildConvItem(conv);
    if (query) {
      const title = (conv.title || '').toLowerCase();
      item.style.display = title.includes(query) ? '' : 'none';
    }
    container.appendChild(item);
  });

  // Re-apply section label visibility
  if (query) {
    container.querySelectorAll('.conv-section-label').forEach(l => l.style.display = 'none');
  }
}

function _buildConvItem(conv) {
  const item   = document.createElement('div');
  item.className = `conv-item${conv.id === state.convId ? ' active' : ''}`;
  item.dataset.id = conv.id;

  const title = conv.title || 'Untitled';

  item.innerHTML = `
    <div class="conv-icon">
      ${ICONS.chat}
    </div>
    <div class="conv-info">
      <div class="conv-title">${escapeHtml(title)}</div>
    </div>
    <div class="conv-menu-wrap">
      <button class="conv-menu-btn" type="button" title="Conversation options" aria-label="Conversation options" aria-expanded="false">
        ${ICONS.moreVertical}
      </button>
      <div class="conv-menu" role="menu">
        <button class="conv-menu-item" type="button" role="menuitem" data-action="rename">
          ${ICONS.edit}
          <span>Rename</span>
        </button>
        <button class="conv-menu-item danger" type="button" role="menuitem" data-action="remove">
          ${ICONS.trash}
          <span>Remove</span>
        </button>
      </div>
    </div>`;

  item.addEventListener('click', e => {
    if (!e.target.closest('.conv-menu-wrap')) openConversation(conv.id);
  });

  const menuBtn = item.querySelector('.conv-menu-btn');
  menuBtn.addEventListener('click', e => {
    e.stopPropagation();
    toggleConversationMenu(item);
  });

  item.querySelector('[data-action="rename"]').addEventListener('click', e => {
    e.stopPropagation();
    closeConversationMenus();
    renameConversation(conv.id);
  });

  item.querySelector('[data-action="remove"]').addEventListener('click', e => {
    e.stopPropagation();
    closeConversationMenus();
    deleteConversation(conv.id);
  });

  return item;
}

function closeConversationMenus(exceptItem = null) {
  document.querySelectorAll('.conv-item.menu-open').forEach(item => {
    if (item === exceptItem) return;
    item.classList.remove('menu-open');
    item.querySelector('.conv-menu-btn')?.setAttribute('aria-expanded', 'false');
  });
}

function toggleConversationMenu(item) {
  const willOpen = !item.classList.contains('menu-open');
  closeConversationMenus(item);
  item.classList.toggle('menu-open', willOpen);
  item.querySelector('.conv-menu-btn')?.setAttribute('aria-expanded', String(willOpen));
}

document.addEventListener('click', e => {
  if (!e.target.closest('.conv-menu-wrap')) closeConversationMenus();
});

document.addEventListener('keydown', e => {
  if (e.key === 'Escape') closeConversationMenus();
});

// ── CRUD ──────────────────────────────────────────────────────────────────────

function updateTitleInput(title) {
  const titleInput = document.getElementById('chat-title-input');
  if (!titleInput || document.activeElement === titleInput) return;
  titleInput.value = title || '';
}

function updateConversationListTitle(convId, title) {
  if (!convId || !title) return;

  const item = document.querySelector(`.conv-item[data-id="${CSS.escape(convId)}"]`);
  const titleEl = item?.querySelector('.conv-title');
  if (!titleEl || titleEl.textContent === title) return;

  titleEl.textContent = title;

  const searchInput = document.getElementById('conv-search');
  const query = searchInput ? searchInput.value.trim().toLowerCase() : '';
  if (query) item.style.display = title.toLowerCase().includes(query) ? '' : 'none';
}

function setActiveConversationItem(convId) {
  document.querySelectorAll('.conv-item.active').forEach(item => item.classList.remove('active'));
  const item = document.querySelector(`.conv-item[data-id="${CSS.escape(convId)}"]`);
  item?.classList.add('active');
}

function upsertConversationListItem(conv) {
  const container = document.getElementById('conv-list');
  if (!container || !conv?.id) return;

  const existing = container.querySelector(`.conv-item[data-id="${CSS.escape(conv.id)}"]`);
  if (existing) {
    updateConversationListTitle(conv.id, conv.title || 'New Conversation');
    setActiveConversationItem(conv.id);
    return;
  }

  if (container.querySelector('.conv-empty')) container.innerHTML = '';
  if (!container.querySelector('.conv-section-label')) {
    container.appendChild(Object.assign(document.createElement('div'), {
      className: 'conv-section-label',
      textContent: 'Recent',
    }));
  }

  container.insertBefore(_buildConvItem({
    title: 'New Conversation',
    ...conv,
  }), container.querySelector('.conv-section-label')?.nextSibling || null);
  setActiveConversationItem(conv.id);
}

document.addEventListener('chat:conversation-title-updated', event => {
  const { convId, title } = event.detail || {};
  updateConversationListTitle(convId, title);
});

function applyConversationData(id, data, { render = true } = {}) {
  if (state.convId !== id) return;

  state.messages   = data.messages || [];
  state.displayLog = data.displayLog || [];

  updateTitleInput(data.title || '');
  updateConversationListTitle(id, data.title || '');
  if (render) renderAllMessages(state.displayLog);
}

export async function openConversation(id) {
  const data = await api.get(`/api/conversations/${id}`);
  state.convId = id;
  storage.set(STORAGE_KEYS.lastConv, id);
  const hasActiveStream = Boolean(data.active_stream_id);
  applyConversationData(id, data, { render: !hasActiveStream });
  resetFilePanel();
  refreshFilePanel();

  document.dispatchEvent(new CustomEvent('chat:conversation-opened', { detail: { convId: id, data } }));
  setActiveConversationItem(id);
  if (window.innerWidth <= 768) toggleSidebar(false);
}

// Resets the UI to an empty chat without touching the server.
// The actual conversation record is created lazily on the first send (chat.js).
export function startNewChat() {
  state.convId     = null;
  state.messages   = [];
  state.displayLog = [];
  storage.remove(STORAGE_KEYS.lastConv);
  document.getElementById('chat-title-input').value = '';
  clearMessages();
  resetFilePanel();
  refreshFilePanel();
  document.dispatchEvent(new CustomEvent('chat:conversation-opened', { detail: { convId: null, data: {} } }));
  document.querySelectorAll('.conv-item.active').forEach(el => el.classList.remove('active'));
  if (window.innerWidth <= 768) toggleSidebar(false);
}

// Creates a conversation record on the server. Called by chat.js before the first send.
export async function createNewConversation() {
  const data = await api.post('/api/conversations', { title: 'New Conversation' });
  state.convId     = data.id;
  state.messages   = [];
  state.displayLog = [];
  storage.set(STORAGE_KEYS.lastConv, data.id);
  document.getElementById('chat-title-input').value = 'New Conversation';
  resetFilePanel();
  refreshFilePanel();
  upsertConversationListItem(data);
}

export async function renameConversation(convId) {
  if (!convId) return;

  const currentTitle = document.querySelector(`.conv-item[data-id="${CSS.escape(convId)}"] .conv-title`)?.textContent || 'Untitled';
  const title = prompt('Rename conversation', currentTitle);
  if (title === null) return;

  const nextTitle = title.trim() || 'Untitled';
  await persistConversationFor(convId, { title: nextTitle });

  if (state.convId === convId) updateTitleInput(nextTitle);
}

export async function deleteConversation(convId) {
  if (!confirm('Delete this conversation?')) return;
  await api.delete(`/api/conversations/${convId}`);
  if (state.convId === convId) {
    // Reset the UI to an empty chat so the header/title clears.
    startNewChat();
  }
  await loadConversationList();
}

export async function persistConversationFor(convId, { title, messages, displayLog }) {
  if (!convId) return;

  const payload = {};
  if (title !== undefined) payload.title = title || 'Untitled';
  if (messages !== undefined) payload.messages = messages || [];
  if (displayLog !== undefined) payload.displayLog = displayLog || [];

  await api.put(`/api/conversations/${convId}`, payload);

  if (payload.title) updateConversationListTitle(convId, payload.title);
}

export async function renameConversationTitle() {
  if (!state.convId) return;

  const titleInput = document.getElementById('chat-title-input');
  const title = titleInput.value.trim() || 'Untitled';
  titleInput.value = title;

  await persistConversationFor(state.convId, { title });
}

