// Chat edit flow — edit/resend and regenerate assistant turns.

import { state } from './state.js';
import { appendMessage, renderAllMessages } from './renderer.js';

// ── Index helpers ────────────────────────────────────────────────────────────

/** Maps a displayLog index to the corresponding state.messages index. */
function logIndexToMessagesIndex(logIndex) {
  let count = 0;
  for (let i = 0; i < logIndex; i++) {
    const entry = state.displayLog[i];
    if (entry && (entry.type === 'message' || entry.type === 'tool_result')) count++;
  }
  return count;
}

// ── Edit & Resend ─────────────────────────────────────────────────────────────

/**
 * Extract the image ref from a server image URL, e.g. "/api/images/<ref>" → "<ref>".
 * Returns null if the URL doesn't match the expected pattern.
 */
function imageUrlToRef(url) {
  const match = url && url.match(/\/api\/images\/([^/?#]+)/);
  return match ? match[1] : null;
}

export async function editAndResend(logIndex, newText, imageUrls = [], files = [], attachments = null, deps) {
  if (state.isStreaming) return;

  const normalizedAttachments = Array.isArray(attachments)
    ? attachments
    : [
        ...(files || []).map(file => ({ kind: 'file', ...file })),
        ...(imageUrls || []).map(url => ({ kind: 'image', url, ref: imageUrlToRef(url) })),
      ];

  if (!newText.trim() && !normalizedAttachments.length) return;
  if (!state.convId) await deps.createNewConversation();

  const messagesIndex = logIndexToMessagesIndex(logIndex);
  state.displayLog.splice(logIndex);
  state.messages.splice(messagesIndex);
  renderAllMessages(state.displayLog);

  // Rebuild the user turn with the original attachments so they are preserved.
  const textToSend = newText.trim();
  const fileAttachments = normalizedAttachments.filter(entry => entry.kind === 'file');
  const imageAttachments = normalizedAttachments.filter(entry => entry.kind === 'image');
  const refs = imageAttachments.map(entry => entry.ref || imageUrlToRef(entry.url)).filter(Boolean);

  let apiContent;
  if (refs.length) {
    apiContent = [];
    if (textToSend) apiContent.push({ type: 'text', text: textToSend });
    refs.forEach(ref => apiContent.push({ type: 'image_ref', ref }));
  } else {
    apiContent = textToSend;
  }

  const displayContent = normalizedAttachments.length
    ? {
        text: textToSend,
        attachments: normalizedAttachments,
        imageUrls: imageAttachments.map(entry => entry.url).filter(Boolean),
        files: fileAttachments,
      }
    : textToSend;

  const turn = deps.createTurnContext(state.convId);
  turn.messages.push({ role: 'user', content: apiContent, attachments: fileAttachments });
  turn.displayLog.push({ type: 'message', role: 'user', content: displayContent });
  deps.syncVisibleTurn(turn);
  if (deps.isTurnVisible(turn)) appendMessage('user', displayContent, turn.displayLog.length - 1);
  await deps.persistTurnConversation(turn);

  await deps.runAssistantTurnAndPersist(turn);
}

// ── Regenerate ────────────────────────────────────────────────────────────────

export async function regenerateFrom(logIndex, deps) {
  if (state.isStreaming) return;

  // Walk back to find the index right after the last user message — that's
  // where the whole assistant turn (thinking + tool calls + responses) begins.
  let turnStart = 0;
  for (let i = logIndex - 1; i >= 0; i--) {
    const entry = state.displayLog[i];
    if (entry.type === 'message' && entry.role === 'user') {
      turnStart = i + 1;
      break;
    }
  }

  const messagesIndex = logIndexToMessagesIndex(turnStart);
  state.displayLog.splice(turnStart);
  state.messages.splice(messagesIndex);
  renderAllMessages(state.displayLog);

  if (!state.convId) return;
  const turn = deps.createTurnContext(state.convId);
  await deps.persistTurnConversation(turn);
  await deps.runAssistantTurnAndPersist(turn);
}