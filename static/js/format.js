// Small shared formatting helpers used by chat, renderer, and file panel.

export function formatBytes(bytes = 0, { emptyZero = false } = {}) {
  if (emptyZero && !bytes) return '';
  if (bytes === null || bytes === undefined) return '';
  if (bytes < 1024) return `${bytes} B`;

  const units = ['KB', 'MB', 'GB'];
  let value = bytes / 1024;
  let unit = units.shift();
  while (value >= 1024 && units.length) {
    value /= 1024;
    unit = units.shift();
  }
  return `${value.toFixed(value >= 10 ? 0 : 1)} ${unit}`;
}

export function fileExtensionLabel(name = '') {
  const ext = (name.split('.').pop() || '').trim();
  return ext ? ext.toUpperCase().slice(0, 6) : 'FILE';
}

export function fileExtension(name = '') {
  return (name.split('.').pop() || '').toLowerCase();
}


export function escapeHtml(value) {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
