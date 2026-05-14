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
      ${streaming ? '<span class="thinking-pulse"></span>' : ''}
    </button>
    <pre class="thinking-body" style="display:${display}">${body}</pre>`;
}

export function createThinkingBlock() {
  const expanded = state.blocksDefaultExpanded;
  const row = prepareAssistantRow();
  const block = createElement('div', {
    className: `thinking-block thinking-streaming${expanded ? ' open' : ''}`,
    html: createThinkingMarkup({
      label:     'Thinking…',
      chevron:   expanded ? ICONS.chevronDown : ICONS.chevronRight,
      streaming: true,
      display:   expanded ? 'block' : 'none',
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
  block.querySelector('.thinking-pulse')?.remove();
  bodyEl.textContent = fullText;

  // Always collapse after streaming unless the user manually toggled it during streaming.
  if (!block.dataset.manualToggle) {
    block.classList.remove('open');
    block.querySelector('.thinking-chevron').innerHTML = ICONS.chevronRight;
    setVisible(bodyEl, false);
  }

  updateGroupLabel(block.closest('.block-group'));
}

export function appendThinkingBlock(reasoningText) {
  if (!reasoningText) return;

  const expanded = state.blocksDefaultExpanded;
  const row = prepareAssistantRow();
  const block = createElement('div', {
    className: `thinking-block${expanded ? ' open' : ''}`,
    html: createThinkingMarkup({
      label:   'Thought process',
      chevron: expanded ? ICONS.chevronDown : ICONS.chevronRight,
      body:    escapeHtml(reasoningText),
      display: expanded ? 'block' : 'none',
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
