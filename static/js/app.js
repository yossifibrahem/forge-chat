// App entry point — event binding and boot sequence.
//
// This module's only job is to wire UI events to domain functions.
// No business logic lives here.

import { STORAGE_KEYS, state } from './state.js';
import { storage }  from './storage.js';

import { openModal, closeModal, toggleSidebar, autoResize, updateCharCount, initMobileKeyboardHandling } from './ui.js';
import { loadSettings, saveSettings, saveChatSettings, fetchModels, initKeyToggle, initParameterSliders } from './settings.js';
import { loadConversationList, openConversation, renameConversationTitle, startNewChat } from './conversations.js';
import { loadMcpConfig, saveMcpConfig, reloadTools, loadCachedTools } from './mcp.js';
import { sendMessage, stopAssistantTurn, editAndResend, regenerateFrom, initImageAttachments } from './chat.js';
import { initVoiceInput } from './voice.js';
import { clearMessages } from './renderer.js';
import { ICONS, initIcons } from './icons.js';
import { loadCustomization, saveCustomization, resetCustomization, initSwatchPicker, syncCustomizationUI } from './customization.js';
import { initFilePanel } from './file_panel.js';

// ── Event binding ─────────────────────────────────────────────────────────────

function bindSidebarEvents() {
  document.getElementById('btn-toggle-sidebar').addEventListener('click', () => toggleSidebar());
  document.getElementById('btn-new-chat').addEventListener('click', startNewChat);

  // Conversation search
  const searchInput = document.getElementById('conv-search');
  searchInput.addEventListener('input', () => {
    const q = searchInput.value.trim().toLowerCase();
    const convList = document.getElementById('conv-list');
    const items    = convList.querySelectorAll('.conv-item');
    let visible    = 0;

    items.forEach(item => {
      const title = (item.querySelector('.conv-title')?.textContent || '').toLowerCase();
      const show  = !q || title.includes(q);
      item.style.display = show ? '' : 'none';
      if (show) visible++;
    });

    // Section label visibility
    convList.querySelectorAll('.conv-section-label').forEach(label => {
      label.style.display = q ? 'none' : '';
    });

    // No-results message
    let noResults = convList.querySelector('.conv-search-empty');
    if (!visible && q) {
      if (!noResults) {
        noResults = Object.assign(document.createElement('div'), { className: 'conv-search-empty' });
        convList.appendChild(noResults);
      }
      noResults.textContent = `No results for "${searchInput.value}"`;
      noResults.style.display = '';
    } else if (noResults) {
      noResults.style.display = 'none';
    }
  });
}

function bindModelPickerEvents() {
  const modelBadge   = document.getElementById('model-badge');
  const modelPopover = document.getElementById('model-popover');

  // Prepend the AI avatar icon from the single source of truth in icons.js
  modelBadge.insertAdjacentHTML('afterbegin', `<span class="model-icon">${ICONS.ai}</span>`);

  modelBadge.addEventListener('click', e => {
    e.stopPropagation();
    const isOpen = modelPopover.classList.toggle('open');
    modelBadge.classList.toggle('open', isOpen);
  });
  document.addEventListener('click', e => {
    if (!document.getElementById('model-picker-wrap').contains(e.target)) {
      modelPopover.classList.remove('open');
      modelBadge.classList.remove('open');
    }
  });
}

function bindModalEvents() {
  document.getElementById('btn-open-settings').addEventListener('click', () => openModal('settings-modal'));

  document.querySelectorAll('[data-close]').forEach(btn =>
    btn.addEventListener('click', () => {
      closeModal(btn.dataset.close);
      if (btn.dataset.close === 'settings-modal') syncCustomizationUI();
    })
  );
  document.querySelectorAll('.modal-overlay').forEach(overlay =>
    overlay.addEventListener('click', e => {
      if (e.target === overlay) {
        closeModal(overlay.id);
        if (overlay.id === 'settings-modal') syncCustomizationUI();
      }
    })
  );

  // Tab switching
  document.querySelectorAll('.modal-tab').forEach(tab => {
    tab.addEventListener('click', () => {
      const targetId = tab.dataset.tab;
      document.querySelectorAll('.modal-tab').forEach(t => t.classList.remove('active'));
      document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
      document.querySelectorAll('.tab-footer-btn').forEach(b => b.classList.remove('active'));
      tab.classList.add('active');
      document.getElementById(targetId).classList.add('active');
      document.querySelectorAll(`.tab-footer-btn[data-for-tab="${targetId}"]`).forEach(b => b.classList.add('active'));
    });
  });
  document.querySelectorAll('.tab-footer-btn[data-for-tab="tab-api"]').forEach(b => b.classList.add('active'));
}

function bindSettingsEvents() {
  document.getElementById('btn-save-settings').addEventListener('click', saveSettings);
  document.getElementById('btn-save-chat-settings').addEventListener('click', saveChatSettings);
  document.getElementById('btn-fetch-models').addEventListener('click', fetchModels);
  document.getElementById('btn-save-mcp').addEventListener('click', saveMcpConfig);
  document.getElementById('btn-reload-tools').addEventListener('click', reloadTools);
  document.getElementById('btn-save-customization').addEventListener('click', saveCustomization);
  document.getElementById('btn-reset-customization').addEventListener('click', resetCustomization);
  initSwatchPicker();
  initKeyToggle();
  initParameterSliders();
}

function bindInputEvents() {
  const userInput = document.getElementById('user-input');
  const sendBtn   = document.getElementById('send-btn');

  const updateSendButton = () => {
    if (!sendBtn) return;
    sendBtn.disabled = userInput.value.trim() === '';
  };

  const submitInput = () => {
    const text = userInput.value.trim();
    if (!text) return; // don't submit empty messages
    userInput.value = '';
    autoResize(userInput);
    updateCharCount();
    sendMessage(text);
    updateSendButton();
  };

  document.getElementById('send-btn').addEventListener('click', submitInput);
  userInput.addEventListener('input',   () => { autoResize(userInput); updateCharCount(); updateSendButton(); });
  userInput.addEventListener('keydown', e => {
    if (e.key !== 'Enter') return;
    const wantsSend = state.enterToSend ? !e.shiftKey : e.shiftKey;
    if (wantsSend) { e.preventDefault(); submitInput(); }
  });

  document.getElementById('stop-btn').addEventListener('click', stopAssistantTurn);

  initImageAttachments();
  initVoiceInput();

  // Chat title persistence
  const titleInput = document.getElementById('chat-title-input');
  titleInput.addEventListener('change', renameConversationTitle);
  titleInput.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); e.target.blur(); } });

  // Empty-state prompt clicks (event delegation)
  document.getElementById('messages').addEventListener('click', e => {
    const prompt = e.target.closest('.es-prompt');
    if (!prompt) return;
    userInput.value = prompt.dataset.prompt;
    autoResize(userInput);
    userInput.focus();
    updateSendButton();
  });

  // Edit & Resend — dispatched from renderer when user confirms an edit
  document.getElementById('messages').addEventListener('chat:edit-resend', e => {
    const { logIndex, newText, imageUrls, files, attachments } = e.detail;
    editAndResend(logIndex, newText, imageUrls, files, attachments);
  });

  // Regenerate — dispatched from renderer when user clicks regenerate
  document.getElementById('messages').addEventListener('chat:regenerate', e => {
    regenerateFrom(e.detail.logIndex);
  });
  // Initialize send button state
  updateSendButton();
}

function bindKeyboardEvents() {
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') {
      const openModals = document.querySelectorAll('.modal-overlay.open');
      openModals.forEach(m => {
        m.classList.remove('open');
        if (m.id === 'settings-modal') syncCustomizationUI();
      });
    }
    if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
      e.preventDefault();
      startNewChat();
    }
  });
}

function bindEvents() {
  bindSidebarEvents();
  bindModelPickerEvents();
  bindModalEvents();
  bindSettingsEvents();
  bindInputEvents();
  bindKeyboardEvents();
}

// ── Boot sequence ─────────────────────────────────────────────────────────────

(async () => {
  initIcons();
  initFilePanel();
  initMobileKeyboardHandling();   // must run early — sets --vvh before first paint
  bindEvents();
  loadSettings();
  loadCustomization();
  loadCachedTools();
  await loadConversationList();
  await loadMcpConfig();

  const lastConvId = storage.get(STORAGE_KEYS.lastConv);
  if (lastConvId) {
    try {
      await openConversation(lastConvId);
    } catch {
      storage.remove(STORAGE_KEYS.lastConv);
      clearMessages();
    }
  } else {
    clearMessages(); // Show empty state when no conversation exists
  }

  const sidebarOpen = state.sidebarDefaultOpen;
  // Always start collapsed on mobile — sidebar overlays content there
  const shouldOpen = window.innerWidth <= 768 ? false : sidebarOpen;
  // Remove the CSS pre-collapse class — JS takes over from here
  document.documentElement.classList.remove('sidebar-init-closed');
  if (!shouldOpen) toggleSidebar(false);
})();