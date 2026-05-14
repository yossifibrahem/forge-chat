// Attachment card rendering and multi-part content helpers.

import { createElement } from './dom.js';
import { applyMarkdown } from './markdown.js';
import { escapeHtml, formatBytes, fileExtensionLabel } from './format.js';

export function normalizeContentAttachments(content = {}) {
  if (!content || typeof content !== 'object' || Array.isArray(content)) return [];
  if (Array.isArray(content.attachments)) {
    return content.attachments
      .map(entry => entry?.kind ? entry : null)
      .filter(Boolean);
  }
  return [
    ...(Array.isArray(content.files) ? content.files.map(file => ({ kind: 'file', ...file })) : []),
    ...(Array.isArray(content.imageUrls) ? content.imageUrls.map(url => ({ kind: 'image', url })) : []),
  ];
}

export function renderAttachmentCard(attachment, { edit = false } = {}) {
  if (attachment.kind === 'image') {
    const card = createElement('div', {
      className: `attachment-card attachment-card--image${edit ? ' msg-edit-image-card' : ''}`,
      html: `<img class="attachment-card-thumb${edit ? ' msg-edit-image-thumb' : ''}" alt="" />
             <div class="attachment-card-overlay">
               <span class="attachment-card-name"></span>
             </div>`,
    });
    const img = card.querySelector('img');
    img.src = attachment.url || '';
    img.alt = attachment.name || 'image';
    card.querySelector('.attachment-card-name').textContent = attachment.name || 'image';
    card.title = attachment.name ? `Open ${attachment.name}` : 'Open image';
    card.style.cursor = 'zoom-in';
    card.addEventListener('click', () => {
      if (attachment.url) window.open(attachment.url, '_blank');
    });
    return card;
  }

  const card = createElement('div', { className: `attachment-card attachment-card--file${edit ? ' msg-edit-file-card' : ''}` });
  card.title = attachment.path ? `Available to tools at ${attachment.path}` : '';
  const badge = fileExtensionLabel(attachment.name || 'file');
  const size = formatBytes(attachment.size || 0, { emptyZero: true });
  card.innerHTML = `
    <div class="attachment-card-body">
      <div class="attachment-card-name"></div>
      <div class="attachment-card-footer">
        <span class="attachment-card-badge">${escapeHtml(badge)}</span>
        ${size ? `<span class="attachment-card-size">${size}</span>` : ''}
      </div>
    </div>`;
  card.querySelector('.attachment-card-name').textContent = attachment.name || 'file';
  return card;
}

export function getRawText(content) {
  if (typeof content === 'string') return content;
  if (content && typeof content === 'object' && !Array.isArray(content)) return content.text || '';
  if (Array.isArray(content)) return content.filter(p => p.type === 'text').map(p => p.text).join('\n');
  return '';
}

export function appendContentParts(contentEl, content) {
  if (content && typeof content === 'object' && !Array.isArray(content) && ('attachments' in content || 'imageUrls' in content || 'files' in content)) {
    const attachments = normalizeContentAttachments(content);

    if (attachments.length) {
      const attachmentsWrap = createElement('div', { className: 'msg-attachments-grid' });
      attachments.forEach(attachment => attachmentsWrap.appendChild(renderAttachmentCard(attachment)));
      contentEl.appendChild(attachmentsWrap);
    }

    if (content.text) {
      const textChunk = createElement('div');
      applyMarkdown(textChunk, content.text);
      contentEl.appendChild(textChunk);
    }
    return;
  }

  if (typeof content === 'string') {
    applyMarkdown(contentEl, content);
    return;
  }

  if (!Array.isArray(content)) return;
  const textParts = content.filter(p => p.type === 'text').map(p => p.text).join('\n');
  applyMarkdown(contentEl, textParts);
}
