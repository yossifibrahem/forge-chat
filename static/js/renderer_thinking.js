// Thinking block creation, streaming updates, and finalization.

import { createElement, setVisible } from './dom.js';
import { ICONS } from './icons.js';
import { state } from './state.js';
import { escapeHtml } from './format.js';
import { scrollToBottom } from './renderer_core.js';
import { prepareAssistantRow, attachCollapsible, tryGroupBlock, updateGroupLabel } from './renderer_groups.js';

function createThinkingMarkup({ label, chevron, body = '', streaming = false, display = 'none' }) {
  return `
    <button class="thinking-header">
      <span class="thinking-chevron">${chevron}</span>
      <span class="thinking-icon">${ICONS.bulb}</span>
      <span class="thinking-label">${label}</span>
    </button>
    <pre class="thinking-body" style="display:${display}">${body}</pre>`;
}

export function createThinkingBlock() {
  const row = prepareAssistantRow();
  const startOpen = !state.hideThinkingTokens;
  const block = createElement('div', {
    className: `thinking-block thinking-streaming${startOpen ? ' open' : ''}`,
    html: createThinkingMarkup({
      label:     'Thinking…',
      chevron:   startOpen ? ICONS.chevronDown : ICONS.chevronRight,
      streaming: true,
      display:   startOpen ? 'block' : 'none',
    }),
  });

  attachCollapsible(block, {
    headerSelector:  '.thinking-header',
    bodySelector:    '.thinking-body',
    chevronSelector: '.thinking-chevron',
    markManualToggle: true,
  });

  row.appendChild(block);
  if (state.groupSequentialBlocks) tryGroupBlock(block);
  scrollToBottom();
  return block.querySelector('.thinking-body');
}

export function updateThinkingBlock(bodyEl, text) {
  bodyEl.textContent = text;
  scrollToBottom();
}

export function finalizeThinkingBlock(bodyEl, fullText) {
  const block = bodyEl.closest('.thinking-block');
  if (!block) return;

  block.classList.remove('thinking-streaming');
  block.querySelector('.thinking-label').textContent = 'Thought process';
  bodyEl.textContent = fullText;

  // Collapse when done unless the user manually toggled it open mid-stream.
  if (!block.dataset.manualToggle) {
    block.classList.remove('open');
    block.querySelector('.thinking-chevron').innerHTML = ICONS.chevronRight;
    setVisible(bodyEl, false);
  }

  updateGroupLabel(block.closest('.block-group'));
}

// ── Processing indicator ──────────────────────────────────────────────────────
// Shows a spinner + cycling dry-humor text while the model or a tool is working.

const _phrases = ['proceesing', 'thinking', 'pondering', 'ruminating', 'cogitating', 'mulling it over', 'chewing on it', 'cooking up a response', 'brewing ideas', 'hatching a plan'];

let _processingIndicatorEl = null;
let _processingIntervalId  = null;

export function createProcessingIndicator() {
  if (_processingIndicatorEl) return;
  const row = prepareAssistantRow();
  const el = createElement('div', { className: 'processing-indicator' });
  el.innerHTML = '<span></span><label></label>';
  row.appendChild(el);
  _processingIndicatorEl = el;

  let idx = Math.floor(Math.random() * _phrases.length);
  const label = el.querySelector('label');
  label.textContent = _phrases[idx];

  _processingIntervalId = setInterval(() => {
    idx = (idx + 1) % _phrases.length;
    if (label) label.textContent = _phrases[idx];
  }, 2500);

  scrollToBottom();
}

export function removeProcessingIndicator() {
  if (!_processingIndicatorEl) return;
  clearInterval(_processingIntervalId);
  _processingIntervalId = null;
  _processingIndicatorEl.remove();
  _processingIndicatorEl = null;
}

export function appendThinkingBlock(reasoningText) {
  if (!reasoningText) return;

  const row = prepareAssistantRow();
  const block = createElement('div', {
    className: 'thinking-block',
    html: createThinkingMarkup({
      label:   'Thought process',
      chevron: ICONS.chevronRight,
      body:    escapeHtml(reasoningText),
      display: 'none',
    }),
  });

  attachCollapsible(block, {
    headerSelector:  '.thinking-header',
    bodySelector:    '.thinking-body',
    chevronSelector: '.thinking-chevron',
  });

  row.appendChild(block);
  if (state.groupSequentialBlocks) tryGroupBlock(block);
  scrollToBottom();
}