# 0004. MCP instead of a custom chat app

- Status: accepted
- Date: 2026-10-10

## Context

The owner wants to ask questions about their life from the phone and laptop. Building a chat app
means building UI, model hosting, conversation history and mobile clients.

## Decision

Expose the journal as an MCP server (official Python SDK) with tools `search`, `get_day`,
`query_facts`, `on_this_day` and `feedback`. Any MCP-capable AI app (Claude, others) is the UI.
Streamable HTTP with OAuth for phone apps; stdio for local use.

## Consequences

- Far less to build and maintain; better models arrive for free.
- Journal excerpts are sent to the AI app's provider when used; the owner must turn off "use my
  chats for training" there.
- Tool descriptions are the "prompt" for answer quality and must insist on citing dates and only
  using the entries.
- A custom app (calendar, mood colours) remains possible later on the same index.
