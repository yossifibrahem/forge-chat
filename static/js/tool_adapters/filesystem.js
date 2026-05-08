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
 */

import { registerAdapter } from './registry.js';

registerAdapter({
  tools: ['view', 'create_file', 'str_replace'],

  /**
   * Show the file path inline in the strip header.
   * @param {Object} args
   * @returns {string}
   */
  getMetaText(args) {
    return args.path ? String(args.path) : '';
  },
});
