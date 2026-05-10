// Chat payload builders — transform UI state/history into API-ready messages.

import { api } from './api.js';
import { state } from './state.js';
import { isServerEnabled, isServerAutoApprove } from './mcp.js';
import { buildMcpSystemPrompt as buildMcpPrompt } from './mcp_policy.js';


export function buildToolsPayload() {
  return state.mcpTools
    .filter(tool => isServerEnabled(tool.server))
    .map(tool => ({
      type: 'function',
      function: {
        name:        tool.name,
        description: tool.description,
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

/** Fetch a server-stored image and return it as a base64 data-URL. */
async function imageRefToDataUrl(ref) {
  const resp = await fetch(`/api/images/${ref}`);
  const blob = await resp.blob();
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload  = () => resolve(reader.result);
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
  const systemParts = [state.systemPrompt, buildMcpPrompt({ tools: state.mcpTools, isServerEnabled })].filter(Boolean);
  if (systemParts.length) messages.push({ role: 'system', content: systemParts.join('\n\n') });

  messages.push(...turnMessages.map(prepareMessageForApi));
  return expandImageRefs(messages);
}

