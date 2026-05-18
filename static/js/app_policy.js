// App model prompt policy — Lumen app behavior and workspace semantics.
// Add/remove app-level model guidance here instead of editing chat payload assembly.
//
// Scope: app-level behavior only.
// - Identity: what app the model is running in and what the environment provides.
// - Variables: variables the model can use in responses, like current time.
// - Rendering: what the UI can display so the model formats output appropriately.
// - Formatting: how to structure responses in this context.
// - Files: how uploads arrive, how to present workspace files after tool writes.
//
// Do NOT add tool-specific instructions here — those belong in MCP tool schemas.
// Do NOT add per-user instructions here — those belong in the user system prompt.

// variables available to the system prompt:
const now = new Date();


export function buildAppSystemPrompt() {
  return [
    '',

  ].join('\n');
}