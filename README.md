# OpenViking

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Docs](https://img.shields.io/badge/docs-plugins-blue)](https://docs.mindroom.chat/plugins/)
[![Hooks](https://img.shields.io/badge/docs-hooks-blue)](https://docs.mindroom.chat/hooks/)

<img src="https://media.githubusercontent.com/media/mindroom-ai/mindroom/refs/heads/main/frontend/public/logo.png" alt="MindRoom Logo" align="right" width="120" />

Long-term memory for [MindRoom](https://github.com/mindroom-ai/mindroom) agents via [OpenViking](https://github.com/volcengine/OpenViking).

OpenViking is a context database that provides tiered context loading (L0/L1/L2), automatic session memory extraction, and directory-recursive retrieval. This plugin connects MindRoom to an OpenViking server over HTTP, giving agents persistent memory that survives context compaction and service restarts.

## Features

- **Auto-recall** — automatically injects relevant memories into each prompt via `message:enrich`
- **Session archiving** — commits conversation turns to OpenViking after each response, triggering async memory extraction at configurable token thresholds
- **Pre-compaction archive** — saves messages to OpenViking before MindRoom compacts them away, ensuring no conversation history is permanently lost
- **Session initialization** — creates an OpenViking session for each thread on first interaction
- **Memory tools** — explicit `memory_recall`, `memory_store`, and `memory_forget` tools for agent-driven memory management
- **Graceful degradation** — if the OpenViking server is unreachable, hooks return empty results and tools return error messages without crashing

## How It Works

1. When a new thread starts, `init_session` creates an OpenViking session keyed by `room_id:thread_id`.
2. Before each prompt, `recall_memories` queries OpenViking for memories relevant to the user's latest message and injects them as context.
3. After each response, `archive_turn` sends the conversation turn to OpenViking. When accumulated tokens cross the commit threshold, it triggers `commit()` which archives messages and runs async memory extraction (profile, preferences, entities, events, cases, patterns).
4. Before MindRoom compacts conversation history, `pre_compaction_archive` saves all messages being compacted to OpenViking with a synchronous commit, ensuring nothing is lost.
5. Agents can also explicitly search, store, and delete memories using the provided tools.

## Agent Tools

| Tool | Purpose |
|------|---------|
| `memory_recall(query)` | Search long-term memory for information relevant to the query |
| `memory_store(content, category="general")` | Store a new memory in the specified category |
| `memory_forget(query)` | Find and delete memories matching the query |

## Hooks

| Hook | Event | Priority | Purpose |
|------|-------|----------|---------|
| `openviking-init-session` | `session:started` | 10 | Initialize OpenViking session for the thread |
| `openviking-recall` | `message:enrich` | 30 | Auto-inject relevant memories before each prompt |
| `openviking-archive-turn` | `message:after_response` | 50 | Archive conversation turns, auto-commit at token threshold |
| `openviking-pre-compaction` | `compaction:before` | 10 | Save messages to OpenViking before compaction discards them |

## Configuration

Plugin settings in `config.yaml`:

| Setting | Default | Description |
|---------|---------|-------------|
| `url` | `http://localhost:1933` | OpenViking server URL |
| `recall_max_tokens` | `2000` | Maximum tokens for injected memories per prompt |
| `commit_token_threshold` | `8000` | Accumulated tokens before triggering async commit |

Environment variable overrides:

| Variable | Description |
|----------|-------------|
| `OPENVIKING_URL` | Override the server URL |
| `OPENVIKING_RECALL_MAX_TOKENS` | Override the recall token budget |
| `OPENVIKING_COMMIT_TOKEN_THRESHOLD` | Override the commit threshold |

Example:

```yaml
plugins:
  - path: plugins/openviking
    settings:
      url: http://localhost:1933
      recall_max_tokens: 2000
      commit_token_threshold: 8000
```

## Prerequisites

An [OpenViking](https://github.com/volcengine/OpenViking) server must be running and accessible at the configured URL. Quick start:

```bash
pip install openviking
openviking-server --port 1933
```

Configure OpenViking's VLM and embedding providers in `~/.openviking/ov.conf`.

## Setup

1. Copy this plugin to `~/.mindroom/plugins/openviking`.
2. Add the plugin to `config.yaml`:
   ```yaml
   plugins:
     - path: plugins/openviking
   ```
3. Add `openviking` tools to the agent's tools list:
   ```yaml
   tools:
     - memory_recall
     - memory_store
     - memory_forget
   ```
4. Ensure the OpenViking server is running at the configured URL.
5. Restart MindRoom.

## License

[MIT](LICENSE)