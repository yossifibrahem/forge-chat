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
  moreVertical: icon('<circle cx="12" cy="5" r="1.8"/><circle cx="12" cy="12" r="1.8"/><circle cx="12" cy="19" r="1.8"/>', 'fill="currentColor" stroke="none"'),
  trash:   icon('<polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/>'),
  copy:    icon('<rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>'),
  download: icon('<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>'),
  edit:    icon(_penBody),
  refresh: icon('<polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>'),

  // ── Navigation / chrome ────────────────────────────────────────────────────
  chevronLeft:  icon('<polyline points="15 18 9 12 15 6"/>',   'width="10" height="10" stroke-width="2.5"'),
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
  file:      icon('<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/>'),

  // ── Conversation list ──────────────────────────────────────────────────────
  chat: icon('<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>'),
  search: icon('<circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>', 'stroke-width="2.2"'),

  // ── Decorative / small ─────────────────────────────────────────────────────
  bulb:   icon('<path d="M9 18h6"/><path d="M10 22h4"/><path d="M12 2a7 7 0 0 0-4 12c0 1.5.5 2 1 3h6c.5-1 1-1.5 1-3a7 7 0 0 0-4-12z"/>', 'width="13" height="13"'),
  layers: icon('<polygon points="12 2 22 8.5 12 15 2 8.5"/><polyline points="2 13 12 19.5 22 13"/><polyline points="2 17.5 12 24 22 17.5"/>', 'width="13" height="13"'),

  // ── Suggestion chip icons (sized by CSS) ───────────────────────────────────
  chipCode:    icon('<polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/>'),
  chipPencil:  icon(_penBody),
  chipInfo:    icon('<circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>'),
  chipBox:     icon('<path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/>'),
  chipHelp:    icon('<circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><line x1="12" y1="17" x2="12.01" y2="17"/>'),


  // ── Tab icons (modal navigation) ──────────────────────────────────────────
  tabApi: `<svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><rect x="1" y="4.5" width="14" height="8.5" rx="2"/><path d="M5.5 4.5V3.5a2.5 2.5 0 0 1 5 0v1"/><circle cx="8" cy="8.5" r="1.2" fill="currentColor" stroke="none"/></svg>`,
  tabChat: `<svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><path d="M14 2H2a1 1 0 0 0-1 1v8a1 1 0 0 0 1 1h3l3 3 3-3h3a1 1 0 0 0 1-1V3a1 1 0 0 0-1-1z"/></svg>`,
  tabAppearance: `<svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><circle cx="8" cy="8" r="2.5"/><path d="M8 1v2M8 13v2M1 8h2M13 8h2M3.05 3.05l1.42 1.42M11.53 11.53l1.42 1.42M3.05 12.95l1.42-1.42M11.53 4.47l1.42-1.42"/></svg>`,
  tabMcp: `<svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><rect x="2" y="2" width="5" height="5" rx="1"/><rect x="9" y="2" width="5" height="5" rx="1"/><rect x="2" y="9" width="5" height="5" rx="1"/><path d="M11.5 9v3M9 11.5h3"/></svg>`,

  // ── API key visibility toggle ──────────────────────────────────────────────
  eyeShow: `<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><path d="M1 8s3-5.5 7-5.5S15 8 15 8s-3 5.5-7 5.5S1 8 1 8z"/><circle cx="8" cy="8" r="2"/></svg>`,
  eyeHide: `<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><path d="M1 8s3-5.5 7-5.5S15 8 15 8s-3 5.5-7 5.5S1 8 1 8z"/><circle cx="8" cy="8" r="2"/><line x1="2" y1="2" x2="14" y2="14"/></svg>`,

  // ── Sync / fetch (used for Fetch Models and Reload Tools buttons) ──────────
  syncIcon: `<svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M14 8A6 6 0 1 1 9.7 2.5"/><path d="M14 2v4h-4"/></svg>`,

  // ── MCP server icons (used in tool strips & the per-server icon picker) ────
  mcpWebSearch:  icon('<circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>', 'width="13" height="13"'),
  mcpBash:       icon('<polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/>', 'width="13" height="13"'),
  mcpFileSystem: icon('<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>', 'width="13" height="13"'),
  mcpMemory:     icon('<rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/><line x1="9" y1="1" x2="9" y2="4"/><line x1="15" y1="1" x2="15" y2="4"/><line x1="9" y1="20" x2="9" y2="23"/><line x1="15" y1="20" x2="15" y2="23"/><line x1="20" y1="9" x2="23" y2="9"/><line x1="20" y1="14" x2="23" y2="14"/><line x1="1" y1="9" x2="4" y2="9"/><line x1="1" y1="14" x2="4" y2="14"/>', 'width="13" height="13"'),
  mcpDatabase:   icon('<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/>', 'width="13" height="13"'),
  mcpGit:        icon('<line x1="6" y1="3" x2="6" y2="15"/><circle cx="18" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M18 9a9 9 0 0 1-9 9"/>', 'width="13" height="13"'),
};

// ── MCP icon picker options ────────────────────────────────────────────────────
// Ordered list of icons users can assign to MCP servers.
export const MCP_ICON_OPTIONS = [
  { key: 'mcpWebSearch',  label: 'Web Search' },
  { key: 'mcpBash',       label: 'Terminal'   },
  { key: 'mcpFileSystem', label: 'Files'      },
  { key: 'mcpMemory',     label: 'Memory'     },
  { key: 'mcpDatabase',   label: 'Database'   },
  { key: 'mcpGit',        label: 'Git'        },
];

// ── HTML hydration ─────────────────────────────────────────────────────────────
// Call once at boot. Finds every [data-icon] element in the document and sets
// its innerHTML to the matching ICONS entry.
export function initIcons() {
  document.querySelectorAll('[data-icon]').forEach(el => {
    const key = el.dataset.icon;
    if (ICONS[key] !== undefined) el.innerHTML = ICONS[key];
  });
}