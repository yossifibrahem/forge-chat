// Block grouping and collapsible helpers — thinking blocks and tool strips
// are collapsed into expandable groups when they appear sequentially.

import { createElement, setVisible } from './dom.js';
import { ICONS } from './icons.js';
import { state } from './state.js';
import { escapeHtml } from './format.js';
import { messagesEl, createMessageRow } from './renderer_core.js';

export function attachCollapsible(block, { headerSelector, bodySelector, chevronSelector, markManualToggle = false }) {
  const header = block.querySelector(headerSelector);
  const body = block.querySelector(bodySelector);
  const chevron = block.querySelector(chevronSelector);

  header?.addEventListener('click', () => {
    if (markManualToggle) block.dataset.manualToggle = '1';
    const isOpen = block.classList.toggle('open');
    if (chevron) chevron.innerHTML = isOpen ? ICONS.chevronDown : ICONS.chevronRight;
    setVisible(body, isOpen);
  });
}

export function getOrCreateAssistantRow() {
  const rows = [...messagesEl().children].filter(child => child.classList.contains('msg-row'));
  const last = rows.at(-1);
  return last && !last.classList.contains('user-row')
    ? last
    : createMessageRow({ avatarClass: 'ai-av', avatarIcon: ICONS.ai, roleLabel: 'Assistant', modelLabel: state.model || '' });
}

export function prepareAssistantRow() {
  const row = getOrCreateAssistantRow();
  row.querySelector('.msg-footer')?.remove();
  return row;
}

export function isGroupableBlock(el) {
  return !!el && (
    el.classList.contains('thinking-block') ||
    el.classList.contains('tool-strip')
  );
}

function makeGroupSummary(elements) {
  let thinks = 0, tools = 0;
  elements.forEach(el => {
    if (el.classList.contains('thinking-block')) thinks++;
    else if (el.classList.contains('tool-strip')) tools++;
  });
  const parts = [];
  if (thinks) parts.push(`${thinks} thinking`);
  if (tools) parts.push(`${tools} tool use`);
  return parts.join(' + ');
}

function getBlockLabel(el) {
  if (!el) return '';
  if (el.classList.contains('thinking-block')) {
    return el.querySelector('.thinking-label')?.textContent?.trim() || 'Thinking';
  }
  if (!el.classList.contains('tool-strip')) return '';
  const name = el.dataset.displayName || el.dataset.toolName || 'tool';
  if (el.classList.contains('tool-strip-using')) return name;
  if (el.classList.contains('tool-strip-running')) return name;
  if (el.classList.contains('tool-strip-approval')) return name;
  return el.querySelector('.tr-tool-name')?.textContent?.trim() || name;
}

function getLastBlockLabel(elements) {
  return getBlockLabel(elements[elements.length - 1]);
}

function isBlockActive(el) {
  if (el.classList.contains('thinking-block')) return el.classList.contains('thinking-streaming');
  if (el.classList.contains('tool-strip')) {
    return el.classList.contains('tool-strip-using') ||
           el.classList.contains('tool-strip-running') ||
           el.classList.contains('tool-strip-approval');
  }
  return false;
}

export function updateGroupLabel(group) {
  const body     = group?.querySelector('.group-body');
  const elements = body ? [...body.children].filter(isGroupableBlock) : [];
  const lbl = group?.querySelector('.group-label');
  if (lbl) lbl.textContent = getLastBlockLabel(elements);
  const active = elements.some(isBlockActive);
  group?.classList.toggle('group-active', active);
}

function createGroupBlock(elements) {
  const label   = getLastBlockLabel(elements);
  const expanded = !state.hideToolBlocks;

  const anyActive = elements.some(isBlockActive);
  const group = createElement('div', { className: `block-group${expanded ? ' open' : ''}${anyActive ? ' group-active' : ''}` });
  group.innerHTML = `
    <button class="group-header">
      <span class="group-chevron">${expanded ? ICONS.chevronDown : ICONS.chevronRight}</span>
      <span class="group-label">${escapeHtml(label)}</span>
    </button>
    <div class="group-body" style="${expanded ? '' : 'display:none'}"></div>`;

  const header  = group.querySelector('.group-header');
  const body    = group.querySelector('.group-body');
  const chevron = group.querySelector('.group-chevron');

  header.addEventListener('click', () => {
    const isOpen = group.classList.toggle('open');
    chevron.innerHTML = isOpen ? ICONS.chevronDown : ICONS.chevronRight;
    setVisible(body, isOpen);
  });

  return group;
}

function previousBlockSibling(el) {
  let prev = el.previousElementSibling;
  while (prev?.classList.contains('msg-content') && !prev.textContent.trim()) {
    prev = prev.previousElementSibling;
  }
  return prev;
}

export function tryGroupBlock(el) {
  if (!isGroupableBlock(el)) return;

  const row = el.parentElement;
  if (!row) return;

  if (row.classList.contains('group-body')) {
    updateGroupLabel(row.closest('.block-group'));
    return;
  }

  const prev = previousBlockSibling(el);

  if (prev?.classList.contains('block-group')) {
    prev.querySelector('.group-body')?.appendChild(el);
    updateGroupLabel(prev);
  } else if (prev && isGroupableBlock(prev)) {
    const group = createGroupBlock([prev, el]);
    row.insertBefore(group, prev);
    const body = group.querySelector('.group-body');
    body.appendChild(prev);
    body.appendChild(el);
  } else {
    const group = createGroupBlock([el]);
    row.insertBefore(group, el);
    group.querySelector('.group-body')?.appendChild(el);
  }
}
