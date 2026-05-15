// Chat payload builders — transform UI state/history into API-ready messages.

import { api } from './api.js';
import { state } from './state.js';
import { isServerEnabled, isServerAutoApprove } from './mcp.js';
import { buildAppSystemPrompt } from './app_policy.js';

export function buildToolsPayload() {
  return state.mcpTools
    .filter(tool => isServerEnabled(tool.server))
    .map(tool => ({
      type: 'function',
      function: {
        name:        tool.name,
        description: tool.description || tool.name,
        parameters:  tool.inputSchema || { type: 'object', properties: {} },
      },
    }));
}

export function buildMcpToolMetaPayload() {
  return state.mcpTools
    .filter(tool => isServerEnabled(tool.server))
    .map(tool => ({
      name: tool.name,
      server: tool.server,
      autoApprove: isServerAutoApprove(tool.server),
    }));
}

/** Fetch a server-stored image and return it as a base64 data-URL.
 *
 * Uses a simple LRU cache (insertion-order Map, evict oldest when over cap)
 * to avoid accumulating unbounded base64 blobs in long sessions.
 */
const IMAGE_CACHE_MAX = 50;
const imageDataUrlCache = new Map();

function _cacheGet(ref) {
  if (!imageDataUrlCache.has(ref)) return undefined;
  // Re-insert to mark as most-recently-used.
  const val = imageDataUrlCache.get(ref);
  imageDataUrlCache.delete(ref);
  imageDataUrlCache.set(ref, val);
  return val;
}

function _cacheSet(ref, url) {
  if (imageDataUrlCache.has(ref)) imageDataUrlCache.delete(ref);
  imageDataUrlCache.set(ref, url);
  if (imageDataUrlCache.size > IMAGE_CACHE_MAX) {
    // Evict the oldest entry (first key in insertion order).
    imageDataUrlCache.delete(imageDataUrlCache.keys().next().value);
  }
}

async function imageRefToDataUrl(ref) {
  const cached = _cacheGet(ref);
  if (cached !== undefined) return cached;

  const resp = await fetch(`/api/images/${ref}`);
  if (!resp.ok) {
    throw new Error(`Image fetch failed for ${ref}: HTTP ${resp.status}`);
  }

  const blob = await resp.blob();
  if (!blob.type || !blob.type.startsWith('image/')) {
    throw new Error(`Image fetch failed for ${ref}: response was not an image`);
  }

  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload  = () => {
      _cacheSet(ref, reader.result);
      resolve(reader.result);
    };
    reader.onerror = reject;
    reader.readAsDataURL(blob);
  });
}

/** Expand image_ref content blocks into image_url blocks the OpenAI API understands. */
async function expandImageRefs(messages) {
  return Promise.all(messages.map(async msg => {
    if (!Array.isArray(msg.content)) return msg;
    const expanded = await Promise.all(msg.content.map(async part => {
      if (part.type !== 'image_ref') return part;
      try {
        const url = await imageRefToDataUrl(part.ref);
        return { type: 'image_url', image_url: { url } };
      } catch {
        return null; // skip unresolvable refs rather than crashing
      }
    }));
    return { ...msg, content: expanded.filter(Boolean) };
  }));
}

function formatAttachmentContext(files = []) {
  const validFiles = files.filter(file => file?.path);
  if (!validFiles.length) return '';
  return [
    'Attached file(s) available in the chat workspace:',
    ...validFiles.map(file => `- ${file.name || 'file'}: ${file.path}`),
  ].join('\n');
}

function appendTextToContent(content, extraText) {
  if (!extraText) return content;
  if (typeof content === 'string') return [content, extraText].filter(Boolean).join('\n\n');

  if (Array.isArray(content)) {
    const parts = content.map(part => ({ ...part }));
    const textPart = parts.find(part => part.type === 'text');
    if (textPart) textPart.text = [textPart.text || '', extraText].filter(Boolean).join('\n\n');
    else parts.unshift({ type: 'text', text: extraText });
    return parts;
  }

  return extraText;
}

function prepareMessageForApi(message) {
  const { attachments, ...cleanMessage } = message;
  const fileContext = message.role === 'user' ? formatAttachmentContext(attachments || []) : '';
  return fileContext
    ? { ...cleanMessage, content: appendTextToContent(cleanMessage.content, fileContext) }
    : cleanMessage;
}

export async function buildApiMessages(turnMessages) {
  const messages = [];
  const systemParts = [state.systemPrompt, buildAppSystemPrompt()].filter(Boolean);
  if (systemParts.length) messages.push({ role: 'system', content: systemParts.join('\n\n') });

  messages.push(...turnMessages.map(prepareMessageForApi));
  return expandImageRefs(messages);
}

