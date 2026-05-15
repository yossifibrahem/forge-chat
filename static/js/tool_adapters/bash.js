/**
 * Adapter: bash_tool
 *
 * Shows the shell command as the strip meta-text so users can see at a glance
 * what is being executed without expanding the full arguments block.
 *
 * The `description` arg is already stripped globally by visibleToolArgs in
 * mcp_tool_ui.js, so we only need to handle the display extras here.
 */

import { registerAdapter } from './registry.js';

registerAdapter({
  tools: ['bash_tool'],

  usingLabel: 'Running command',

  /**
   * Show the command inline in the strip header.
   * @param {Object} args
   * @returns {string}
   */
  getMetaText(args) {
    return args.command ? String(args.command) : '';
  },
});