// Customization — UI preferences persisted to localStorage.

import { state, CUSTOMIZATION_DEFAULTS, STORAGE_KEYS } from './state.js';
import { storage } from './storage.js';
import { showToast } from './ui.js';

// ── Apply ─────────────────────────────────────────────────────────────────────
// Reads from `state` and pushes every setting into the live DOM.

export function applyCustomization() {
  // Theme (light/dark/auto)
  _applyTheme(state.theme || 'dark');

  // Font size
  const isMobile = window.innerWidth <= 768;
  const sizes = isMobile
    ? { small: '12px', medium: '14px', large: '16px' }
    : { small: '14px', medium: '16px', large: '18px' };
  document.documentElement.style.setProperty('--font-size-base', sizes[state.fontSize] || sizes.medium);

  // Font family
  _applyFontFamily(state.fontFamily || 'sora');

  // Accent color — custom hex overrides swatch if set
  const accent = (state.customAccentColor && /^#[0-9a-f]{6}$/i.test(state.customAccentColor))
    ? state.customAccentColor
    : (state.accentColor || CUSTOMIZATION_DEFAULTS.accentColor);
  _applyAccent(accent);

  // Timestamps visibility
  document.documentElement.classList.toggle('hide-timestamps',      !state.showTimestamps);

  // Suggestion chips visibility
  document.documentElement.classList.toggle('hide-suggestion-chips', !state.showSuggestionChips);


  // Char count
  document.documentElement.classList.toggle('hide-char-count', !state.showCharCount);
}

function _applyTheme(theme) {
  let effective = theme;
  if (theme === 'auto') {
    effective = window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
  }
  document.documentElement.setAttribute('data-theme', effective);
}

function _applyFontFamily(family) {
  const map = {
    sora:    "'Sora', sans-serif",
    tiempos: "'Tiempos Text', Georgia, serif",
    mono:    "'JetBrains Mono', monospace",
    system:  "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
  };
  document.documentElement.style.setProperty('--font-roman', map[family] || map.sora);
}

function _applyAccent(hex) {
  const rgb = hexToRgb(hex);
  if (!rgb) return;
  document.documentElement.style.setProperty('--accent',            hex);
  document.documentElement.style.setProperty('--accent-dim',        `rgba(${rgb},0.12)`);
  document.documentElement.style.setProperty('--accent-hover',      `rgba(${rgb},0.20)`);
  document.documentElement.style.setProperty('--accent-glow',       `rgba(${rgb},0.06)`);
  document.documentElement.style.setProperty('--accent-border',     `rgba(${rgb},0.4)`);
  document.documentElement.style.setProperty('--accent-border-dim', `rgba(${rgb},0.25)`);
  document.documentElement.style.setProperty('--accent-border-mid', `rgba(${rgb},0.50)`);
}

// ── Load ──────────────────────────────────────────────────────────────────────

export function loadCustomization() {
  const saved = storage.get(STORAGE_KEYS.customization, {});
  Object.assign(state, { ...CUSTOMIZATION_DEFAULTS, ...saved });
  applyCustomization();
  syncCustomizationUI();

  // If auto theme, re-apply when OS preference changes
  if (state.theme === 'auto') {
    window.matchMedia('(prefers-color-scheme: light)').addEventListener('change', () => {
      if (state.theme === 'auto') _applyTheme('auto');
    });
  }
}

// ── Save ──────────────────────────────────────────────────────────────────────

export function saveCustomization() {
  _readControlsIntoState();
  storage.set(STORAGE_KEYS.customization, {
    sidebarDefaultOpen:    state.sidebarDefaultOpen,
    showSuggestionChips:   state.showSuggestionChips,
    showTimestamps:        state.showTimestamps,
    blocksDefaultExpanded: state.blocksDefaultExpanded,
    groupSequentialBlocks: state.groupSequentialBlocks,
    showCharCount:         state.showCharCount,
    fontSize:              state.fontSize,
    fontFamily:            state.fontFamily,
    theme:                 state.theme,
    accentColor:           state.accentColor,
    customAccentColor:     state.customAccentColor,
  });
  applyCustomization();
  showToast('Appearance saved');
}

// ── Reset ─────────────────────────────────────────────────────────────────────

export function resetCustomization() {
  Object.assign(state, CUSTOMIZATION_DEFAULTS);
  storage.remove(STORAGE_KEYS.customization);
  applyCustomization();
  syncCustomizationUI();
  showToast('Appearance reset to defaults');
}

// ── Init listeners ────────────────────────────────────────────────────────────

export function initSwatchPicker() {
  // Colour swatches — only update active highlight
  document.querySelectorAll('.cust-swatch').forEach(sw => {
    sw.addEventListener('click', () => {
      document.querySelectorAll('.cust-swatch').forEach(s => s.classList.remove('active'));
      sw.classList.add('active');
      // Clear custom color when a preset swatch is selected
      const hexInput = document.getElementById('cust-accent-hex');
      const picker   = document.getElementById('cust-accent-picker');
      if (hexInput) hexInput.value = '';
      if (picker)   picker.value  = sw.dataset.color;
    });
  });

  // Custom color picker
  const picker   = document.getElementById('cust-accent-picker');
  const hexInput = document.getElementById('cust-accent-hex');

  if (picker && hexInput) {
    picker.addEventListener('input', () => {
      hexInput.value = picker.value;
      _deactivateSwatches();
    });
    hexInput.addEventListener('input', () => {
      const val = hexInput.value.trim();
      if (/^#[0-9a-f]{6}$/i.test(val)) {
        picker.value = val;
        _deactivateSwatches();
      }
    });
  }

  // Theme radio cards
  document.querySelectorAll('input[name="cust-theme"]').forEach(radio => {
    radio.addEventListener('change', () => {
      // live preview
      _applyTheme(radio.value);
    });
  });
}

function _deactivateSwatches() {
  document.querySelectorAll('.cust-swatch').forEach(s => s.classList.remove('active'));
}

// ── Sync UI controls → current state ─────────────────────────────────────────

export function syncCustomizationUI() {
  _setCheckbox('cust-sidebar-open',    state.sidebarDefaultOpen);
  _setCheckbox('cust-suggestion-chips',state.showSuggestionChips);
  _setCheckbox('cust-timestamps',      state.showTimestamps);
  _setCheckbox('cust-blocks-expanded',   state.blocksDefaultExpanded);
  _setCheckbox('cust-group-seq-blocks',  state.groupSequentialBlocks);
  _setCheckbox('cust-char-count',        state.showCharCount);

  const fs = document.getElementById('cust-font-size');
  if (fs) fs.value = state.fontSize;

  const ff = document.getElementById('cust-font-family');
  if (ff) ff.value = state.fontFamily;

  // Theme radio
  const themeRadio = document.querySelector(`input[name="cust-theme"][value="${state.theme || 'dark'}"]`);
  if (themeRadio) themeRadio.checked = true;

  // Swatches
  document.querySelectorAll('.cust-swatch').forEach(sw => {
    sw.classList.toggle('active', sw.dataset.color === state.accentColor && !state.customAccentColor);
  });

  // Custom color fields
  const hexInput = document.getElementById('cust-accent-hex');
  const picker   = document.getElementById('cust-accent-picker');
  if (hexInput) hexInput.value = state.customAccentColor || '';
  if (picker) {
    picker.value = state.customAccentColor || state.accentColor || CUSTOMIZATION_DEFAULTS.accentColor;
  }
}

// ── Read DOM controls → state ─────────────────────────────────────────────────

function _readControlsIntoState() {
  state.sidebarDefaultOpen    = document.getElementById('cust-sidebar-open')?.checked     ?? state.sidebarDefaultOpen;
  state.showSuggestionChips   = document.getElementById('cust-suggestion-chips')?.checked  ?? state.showSuggestionChips;
  state.showTimestamps        = document.getElementById('cust-timestamps')?.checked         ?? state.showTimestamps;
  state.blocksDefaultExpanded = document.getElementById('cust-blocks-expanded')?.checked   ?? state.blocksDefaultExpanded;
  state.groupSequentialBlocks = document.getElementById('cust-group-seq-blocks')?.checked  ?? state.groupSequentialBlocks;
  state.showCharCount         = document.getElementById('cust-char-count')?.checked        ?? state.showCharCount;
  state.fontSize              = document.getElementById('cust-font-size')?.value           ?? state.fontSize;
  state.fontFamily            = document.getElementById('cust-font-family')?.value         ?? state.fontFamily;

  const themeRadio = document.querySelector('input[name="cust-theme"]:checked');
  if (themeRadio) state.theme = themeRadio.value;

  // Accent: custom hex takes priority over swatch
  const hexInput = document.getElementById('cust-accent-hex');
  const customHex = hexInput?.value.trim() || '';
  if (customHex && /^#[0-9a-f]{6}$/i.test(customHex)) {
    state.customAccentColor = customHex;
  } else {
    state.customAccentColor = '';
    const activeSwatch = document.querySelector('.cust-swatch.active');
    if (activeSwatch) state.accentColor = activeSwatch.dataset.color;
  }
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function _setCheckbox(id, value) {
  const el = document.getElementById(id);
  if (el) el.checked = !!value;
}

function hexToRgb(hex) {
  const m = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
  return m ? `${parseInt(m[1],16)},${parseInt(m[2],16)},${parseInt(m[3],16)}` : null;
}
