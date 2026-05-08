/**
 * Adapter: Exa MCP server tools
 *
 * Covers the active tools exposed by @exa-ai/mcp-server:
 *   • web_search_exa          — semantic web search, returns highlights
 *   • web_fetch_exa           — full-page crawl of one or more URLs
 *   • web_search_advanced_exa — search with full filter/date/domain control
 *   • get_code_context_exa    — code-focused search across docs and repos
 *
 * Deprecated tools are also listed so the strip still shows a sensible
 * label if an older server config calls them:
 *   • deep_search_exa, company_research_exa, people_search_exa,
 *     linkedin_search_exa, deep_researcher_start, deep_researcher_check
 */

import { registerAdapter } from './registry.js';

// ── Helpers ───────────────────────────────────────────────────────────────────

/** Return the first URL from urls array (string or pre-parsed array). */
function firstUrl(urls) {
  const list = Array.isArray(urls)
    ? urls
    : (typeof urls === 'string' ? tryParseJson(urls) : null);
  if (!Array.isArray(list) || !list.length) return '';
  return list.length === 1
    ? String(list[0])
    : `${list[0]}  +${list.length - 1} more`;
}

function tryParseJson(str) {
  try { return JSON.parse(str); } catch { return null; }
}

// ── Query-based tools (web_search_exa, web_search_advanced_exa, get_code_context_exa) ──

registerAdapter({
  tools: [
    'web_search_exa',
    'web_search_advanced_exa',
    'get_code_context_exa',
    // deprecated variants — same primary arg
    'deep_search_exa',
    'company_research_exa',
    'people_search_exa',
    'linkedin_search_exa',
  ],

  /**
   * Show the search query inline in the strip header.
   * @param {Object} args
   * @returns {string}
   */
  getMetaText(args) {
    return args.query ? String(args.query) : '';
  },
});

// ── Fetch tool (web_fetch_exa) ────────────────────────────────────────────────

registerAdapter({
  tools: ['web_fetch_exa'],

  /**
   * Show the target URL(s) inline in the strip header.
   * @param {Object} args
   * @returns {string}
   */
  getMetaText(args) {
    return firstUrl(args.urls);
  },
});

// ── Async research tools ──────────────────────────────────────────────────────

registerAdapter({
  tools: ['deep_researcher_start'],

  getMetaText(args) {
    return args.query ? String(args.query) : '';
  },
});

registerAdapter({
  tools: ['deep_researcher_check'],

  getMetaText(args) {
    return args.jobId ? `job ${args.jobId}` : '';
  },
});
