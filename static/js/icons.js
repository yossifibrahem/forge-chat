// Single source of truth for every icon in the app.
// JS files import ICONS directly; HTML elements use data-icon="key" and
// are hydrated at boot by calling initIcons().

const icon = (body, attrs = '') =>
  `<svg ${attrs} viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${body}</svg>`;

// Shared SVG bodies reused by multiple icons to avoid duplicate paths.
const _xBody   = '<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>';
const _penBody = '<path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>';

export const ICONS = {
  // ── Avatars ────────────────────────────────────────────────────────────────
  user: icon('<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>'),
  ai:   icon('<rect x="7" y="7" width="10" height="10" rx="1"/><line x1="9" y1="7" x2="9" y2="3"/><line x1="12" y1="7" x2="12" y2="3"/><line x1="15" y1="7" x2="15" y2="3"/><line x1="9" y1="17" x2="9" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/><line x1="15" y1="17" x2="15" y2="21"/><line x1="7" y1="9" x2="3" y2="9"/><line x1="7" y1="12" x2="3" y2="12"/><line x1="7" y1="15" x2="3" y2="15"/><line x1="17" y1="9" x2="21" y2="9"/><line x1="17" y1="12" x2="21" y2="12"/><line x1="17" y1="15" x2="21" y2="15"/>'),

  // ── Actions ────────────────────────────────────────────────────────────────
  check:   icon('<polyline points="20 6 9 17 4 12"/>', 'stroke-width="2.5"'),
  close:   icon(_xBody, 'stroke-width="2.5"'),
  copy:    icon('<rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>'),
  edit:    icon(_penBody),
  refresh: icon('<polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>'),

  // ── Navigation / chrome ────────────────────────────────────────────────────
  chevronRight: icon('<polyline points="9 18 15 12 9 6"/>',   'width="10" height="10" stroke-width="2.5"'),
  chevronDown:  icon('<polyline points="6 9 12 15 18 9"/>',   'width="10" height="10" stroke-width="2.5"'),
  menu:         icon('<rect x="3" y="4" width="18" height="16" rx="3"/><line x1="9" y1="4" x2="9" y2="20"/>'),
  settings:     icon('<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>'),
  plus: icon('<line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>',              'stroke-width="2.2"'),

  // ── Brand / logo ───────────────────────────────────────────────────────────
  logo: icon('<path d="M12 1l2.7 7.9L23 12l-8.3 3.1L12 23l-2.7-7.9L1 12l8.3-3.1L12 1z"/>'),

  // ── Input toolbar ──────────────────────────────────────────────────────────
  send:      icon('<line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/>', 'stroke-width="2.5"'),
  stop: `<svg viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>`,
  mic:       icon('<path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/>'),

  // ── Conversation list ──────────────────────────────────────────────────────
  chat: icon('<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>'),
  search: icon('<circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>', 'stroke-width="2.2"'),

  // ── Decorative / small ─────────────────────────────────────────────────────
  bulb:   icon('<path d="M9 18h6"/><path d="M10 22h4"/><path d="M12 2a7 7 0 0 0-4 12c0 1.5.5 2 1 3h6c.5-1 1-1.5 1-3a7 7 0 0 0-4-12z"/>', 'width="13" height="13"'),
  cursor: icon('<path d="M4 4l7.07 17 2.51-7.39L21 11.07z"/>',                                                                               'width="13" height="13"'),
  layers: icon('<polygon points="12 2 22 8.5 12 15 2 8.5"/><polyline points="2 13 12 19.5 22 13"/><polyline points="2 17.5 12 24 22 17.5"/>', 'width="13" height="13"'),

  // ── Suggestion chip icons (sized by CSS) ───────────────────────────────────
  chipCode:    icon('<polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/>'),
  chipPencil:  icon(_penBody),
  chipInfo:    icon('<circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>'),
  chipBox:     icon('<path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/>'),
  chipHelp:    icon('<circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><line x1="12" y1="17" x2="12.01" y2="17"/>'),
};

// ── HTML hydration ─────────────────────────────────────────────────────────────
// Call once at boot. Finds every [data-icon] element in the document and sets
// its innerHTML to the matching ICONS entry.
export function initIcons() {
  document.querySelectorAll('[data-icon]').forEach(el => {
    const key = el.dataset.icon;
    if (ICONS[key] !== undefined) el.innerHTML = ICONS[key];
  });
}