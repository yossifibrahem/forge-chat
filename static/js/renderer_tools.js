// Tool strip rendering: using → approval → running → result states.

import { createElement, setVisible } from './dom.js';
import { ICONS } from './icons.js';
import { state } from './state.js';
import { escapeHtml } from './format.js';
import {
  getToolDisplayLabel, getToolUsingLabel, formatArgsHtml, renderToolResultHtml, visibleToolArgs,
} from './mcp_tool_ui.js';
import { scrollToBottom } from './renderer_core.js';
import { prepareAssistantRow, attachCollapsible, tryGroupBlock, updateGroupLabel } from './renderer_groups.js';

// Canceller functions for any strips currently awaiting user approval
const activeApprovalCancellers = new Set();

function getToolIconSvg(toolName) {
  const tool = state.mcpTools.find(t => t.name === toolName);
  if (!tool) return ICONS.tabMcp;
  const serverSettings = state.mcpServerSettings[tool.server] || {};
  const toolSettings   = serverSettings.tools?.[toolName] || {};
  const iconKey = toolSettings.icon || serverSettings.icon || 'tabMcp';
  return ICONS[iconKey] || ICONS.tabMcp;
}

function createToolResultBody(toolName, args, result) {
  const displayArgs = visibleToolArgs(toolName, args);
  const sections = [];

  if (Object.keys(displayArgs).length) {
    sections.push(`
      <div class="tr-section">
        <div class="tr-section-label">Arguments</div>
        <div class="tr-args">${formatArgsHtml(displayArgs)}</div>
      </div>`);
  }

  sections.push(`
    <div class="tr-section">
      <div class="tr-section-label">Result</div>
      ${renderToolResultHtml(result, toolName, args)}
    </div>`);

  return sections.join('');
}

function applyToolResultStrip(strip, toolName, args, result, displayName = '') {
  const expanded = !state.hideToolBlocks;
  const label = getToolDisplayLabel(toolName, args) || displayName;

  strip.className = `tool-strip tool-strip-result tool-inline${expanded ? ' open' : ''}`;
  strip.innerHTML = `
    <button class="tr-summary">
      <span class="tr-chevron">${expanded ? ICONS.chevronDown : ICONS.chevronRight}</span>
      <span class="tool-icon">${getToolIconSvg(toolName)}</span>
      <span class="tr-tool-name">${escapeHtml(label)}</span>
    </button>
    <div class="tr-body" style="${expanded ? '' : 'display:none'}">${createToolResultBody(toolName, args, result)}</div>`;

  attachCollapsible(strip, {
    headerSelector:  '.tr-summary',
    bodySelector:    '.tr-body',
    chevronSelector: '.tr-chevron',
  });
}

function popApprovalOutOfGroup(strip) {
  const group = strip.closest('.block-group');
  const body = group?.querySelector('.group-body');
  if (!group || !body) return;

  const placeholder = createElement('span', { className: 'group-popout-placeholder' });
  placeholder.hidden = true;
  body.insertBefore(placeholder, strip);
  group.after(strip);

  strip._groupPlaceholder = placeholder;
  updateGroupLabel(group);
}

function restorePoppedApproval(strip) {
  const placeholder = strip._groupPlaceholder;
  if (!placeholder?.parentNode) return;

  const group = placeholder.closest('.block-group');
  placeholder.parentNode.replaceChild(strip, placeholder);
  delete strip._groupPlaceholder;
  updateGroupLabel(group);
}

function regroupToolStrip(strip) {
  if (strip.closest('.block-group')) {
    updateGroupLabel(strip.closest('.block-group'));
  } else if (state.groupSequentialBlocks) {
    tryGroupBlock(strip);
  }
}

/** Creates the strip in "using" state and appends it to the current assistant row. */
export function createToolStrip(toolName, displayName = '') {
  const row = prepareAssistantRow();
  const strip = createElement('div', { className: 'tool-strip tool-strip-using' });
  strip.dataset.toolName = toolName;
  const usingLabel = getToolUsingLabel(toolName) || displayName || toolName;
  strip.dataset.displayName = usingLabel;
  strip.innerHTML = `
    <span class="tool-icon">${getToolIconSvg(toolName)}</span>
    <span class="tui-name">${escapeHtml(usingLabel)}</span>`;
  row.appendChild(strip);
  if (state.groupSequentialBlocks) tryGroupBlock(strip);
  scrollToBottom();
  return strip;
}

/** Morphs strip into approval state. Returns a Promise<boolean> that resolves when the user decides. */
export function toolStripSetApproval(strip, call) {
  return new Promise(resolve => {
    let args = {};
    try { args = JSON.parse(call.function.arguments || '{}'); } catch {}
    const hasArgs = Object.keys(args).length > 0;
    const displayName = getToolDisplayLabel(call.function.name, args);
    strip.dataset.toolName = call.function.name;
    strip.dataset.displayName = displayName;

    strip.className = 'tool-strip tool-strip-approval tc-item open';
    strip.innerHTML = `
      <div class="tc-item-row">
        <button class="tc-item-header">
          <span class="tc-item-chevron">${ICONS.chevronDown}</span>
          <span class="tool-icon">${getToolIconSvg(call.function.name)}</span>
          <span class="tc-item-name">${escapeHtml(displayName)}</span>
          ${!hasArgs ? '<span class="tc-item-noargs">no arguments</span>' : ''}
        </button>
        <span class="tc-actions">
          <button class="tc-allow">${ICONS.check} allow</button>
          <button class="tc-deny">${ICONS.close} deny</button>
        </span>
        <span class="tc-status" aria-live="polite"></span>
      </div>
      ${hasArgs ? `<div class="tc-item-args" style="display:block">${formatArgsHtml(args)}</div>` : ''}`;

    if (hasArgs) {
      attachCollapsible(strip, {
        headerSelector: '.tc-item-header',
        bodySelector: '.tc-item-args',
        chevronSelector: '.tc-item-chevron',
      });
    }

    popApprovalOutOfGroup(strip);

    let settled = false;
    const decide = allowed => {
      if (settled) return;
      settled = true;
      activeApprovalCancellers.delete(cancel);

      strip.querySelectorAll('.tc-allow, .tc-deny').forEach(btn => {
        btn.disabled = true;
        setVisible(btn, false);
      });
      const status = strip.querySelector('.tc-status');
      if (status) {
        status.className = `tc-status ${allowed ? 'allowed' : 'denied'}`;
        status.innerHTML = allowed ? `${ICONS.check} allowed` : `${ICONS.close} denied`;
      }

      resolve(allowed);
    };

    const cancel = () => decide(false);
    activeApprovalCancellers.add(cancel);

    strip.querySelector('.tc-allow')?.addEventListener('click', () => decide(true));
    strip.querySelector('.tc-deny')?.addEventListener('click',  () => decide(false));
    scrollToBottom();
  });
}

/** Morphs strip from approval → running state. */
export function toolStripSetRunning(strip, args = {}) {
  restorePoppedApproval(strip);
  const name = strip.dataset.toolName || '';
  const displayName = getToolDisplayLabel(name, args);
  strip.dataset.displayName = displayName;
  const hasArgs = Object.keys(args).length > 0;
  strip.className = 'tool-strip tool-strip-running';
  strip.innerHTML = `
    <div class="tool-strip-running-row">
      <span class="tool-icon">${getToolIconSvg(name)}</span>
      <span class="tui-name">${escapeHtml(displayName)}</span>
    </div>
    ${hasArgs ? `<div class="tc-item-args" style="display:none">${formatArgsHtml(args)}</div>` : ''}`;

  updateGroupLabel(strip.closest('.block-group'));
  scrollToBottom();
}

export function toolStripFinalize(strip, toolName, args, result, displayName = '') {
  restorePoppedApproval(strip);
  applyToolResultStrip(strip, toolName, args, result, displayName);
  regroupToolStrip(strip);
  scrollToBottom();
}

/** Appends a finalized tool result to the current assistant row (history replay). */
export function appendToolResultInline(toolName, args, result, displayName = '') {
  const row = prepareAssistantRow();
  const strip = createElement('div');
  applyToolResultStrip(strip, toolName, args, result, displayName);
  row.appendChild(strip);
  regroupToolStrip(strip);
  scrollToBottom();
}

/** Cancels all strips currently waiting for user approval (called on stop). */
export function cancelAllToolApprovals() {
  activeApprovalCancellers.forEach(cancel => cancel());
  activeApprovalCancellers.clear();
}