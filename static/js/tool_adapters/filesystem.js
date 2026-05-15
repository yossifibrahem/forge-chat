/**
 * Adapter: filesystem tools
 *
 * Covers the three core @modelcontextprotocol/server-filesystem tools:
 *   • view        — read a file or directory listing
 *   • create_file — write a new file with given content
 *   • str_replace — replace a unique string inside a file
 *
 * The file path is shown as the strip meta-text so the active file is
 * immediately visible without expanding the arguments block.
 * Each tool gets its own usingLabel to reflect what it is actually doing.
 */

import { registerAdapter } from './registry.js';

const pathMetaText = {
  getMetaText(args) {
    return args.path ? String(args.path) : '';
  },
};

registerAdapter({
  tools: ['view'],
  usingLabel: 'Reading file',
  ...pathMetaText,
});

registerAdapter({
  tools: ['create_file'],
  usingLabel: 'Creating file',
  ...pathMetaText,
});

registerAdapter({
  tools: ['str_replace'],
  usingLabel: 'Editing file',
  ...pathMetaText,
});