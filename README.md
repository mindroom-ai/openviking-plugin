# OpenViking Plugin

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Docs](https://img.shields.io/badge/docs-plugins-blue)](https://docs.mindroom.chat/plugins/)
[![Hooks](https://img.shields.io/badge/docs-hooks-blue)](https://docs.mindroom.chat/hooks/)

Long-term memory for [MindRoom](https://github.com/mindroom-ai/mindroom) agents via [OpenViking](https://github.com/volcengine/OpenViking) — an agent-native context database with tiered context loading, automatic session memory extraction, and directory-recursive retrieval.

Memories are automatically extracted from conversations (profile, preferences, entities, events, cases, patterns) and recalled when relevant. They survive context compaction and service restarts.

## Features

- Automatic memory recall — queries OpenViking before each prompt, injects relevant memories as context
- Session archiving — sends conversation turns after each response, commits at token threshold for async memory extraction
- Pre-compaction archive — saves messages synchronously before MindRoom compacts the context window
- Session initialization — creates an OpenViking session keyed by `room_id:thread_id` on new threads
- Agent memory tools — explicit search, store, and delete via toolkit
- Graceful degradation — if the server is unreachable, hooks warn once and pass through

## How It Works

1. On `session:started`, creates an OpenViking session keyed by `room_id:thread_id`.
2. On `message:enrich`, queries OpenViking for memories relevant to the incoming message and injects them as context.
3. On `message:after_response`, sends the conversation turn to OpenViking. When accumulated tokens exceed the commit threshold, triggers `commit()` which runs async memory extraction (8 categories: profile, preferences, entities, events, cases, patterns, tools, skills).
4. On `compaction:before`, synchronously commits all buffered messages before MindRoom compacts the context window.
5. Agents can explicitly search, store, or delete memories via the toolkit.

## Tools (toolkit: `openviking`)

| Tool | Description |
|------|-------------|
| `memory_recall(query)` | Search long-term memory for relevant context |
| `memory_store(content, category="general")` | Store a memory (creates session → adds message → commits) |
| `memory_forget(query)` | Find and delete memories matching a query |

## Hooks

| Hook | Event | Priority | Purpose |
|------|-------|----------|---------|
| `openviking-init-session` | `session:started` | 10 | Create OpenViking session for the thread |
| `openviking-recall` | `message:enrich` | 30 | Inject recalled memories into prompt context |
| `openviking-archive-turn` | `message:after_response` | 50 | Archive conversation turns, commit at token threshold |
| `openviking-pre-compaction` | `compaction:before` | 10 | Save messages before context compaction |

## Configuration

Plugin settings via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENVIKING_URL` | `http://localhost:1933` | OpenViking server URL |
| `OPENVIKING_RECALL_MAX_TOKENS` | `2000` | Max tokens for recalled memory context |
| `OPENVIKING_COMMIT_TOKEN_THRESHOLD` | `8000` | Token count that triggers session commit |

## Setup

### 1. Start the OpenViking server

⚠️ **Requires Python 3.13** — Python 3.14 has Pydantic V1 compatibility issues.

⚠️ **Use `uvicorn` CLI with `--factory`** — `openviking-server` and `uvicorn.run()` exit silently.

```bash
OPENAI_API_KEY=<your-key> \
  uvx --python 3.13 --with openviking --with litellm \
  uvicorn openviking.server.app:create_app --factory \
  --host 127.0.0.1 --port 1933
```

### 2. Configure the server

Create `~/.openviking/ov.conf`:

```json
{
  "server": {
    "host": "127.0.0.1",
    "port": 1933,
    "auth_mode": "trusted"
  },
  "embedding": {
    "dense": {
      "provider": "openai",
      "model": "text-embedding-3-small",
      "dimension": 1536,
      "api_key": "$OPENAI_API_KEY"
    }
  },
  "vlm": {
    "provider": "openai",
    "model": "gpt-4o-mini",
    "api_key": "$OPENAI_API_KEY",
    "temperature": 0.0,
    "max_concurrent": 10
  },
  "storage": {
    "workspace": "~/.openviking/data"
  }
}
```

- **`embedding`** — required for vector search. Any OpenAI-compatible embedding API works. Set `api_base` if using a proxy or non-OpenAI provider.
- **`vlm`** — required for automatic memory extraction. Without this, sessions commit but no memories are extracted. Any OpenAI-compatible chat completion API works. Set `api_base` if using a proxy or non-OpenAI provider.
- **`auth_mode: "trusted"`** — localhost auth via headers. The plugin sends `X-OpenViking-Account: default` and `X-OpenViking-User: mindroom` automatically.
- **`$OPENAI_API_KEY`** — env vars in the config are expanded at load time.

### 3. Install the plugin

```bash
cd ~/.mindroom/plugins/
git clone https://github.com/mindroom-ai/openviking-plugin.git openviking
```

### 4. Add to `config.yaml`

```yaml
plugins:
  - path: plugins/openviking

agents:
  my-agent:
    tools:
      - openviking
```

### 5. Restart MindRoom

## Architecture

The plugin communicates with OpenViking exclusively over HTTP. The OpenViking server (AGPL-3.0) runs as a separate process. This plugin (MIT) never imports or links OpenViking code — AGPL-clean via the service boundary.

```
MindRoom Agent
  ├── hooks.py       → lifecycle hooks (init, recall, archive, compaction)
  ├── tools.py       → agent tools (recall, store, forget)
  ├── client.py      → async HTTP client (httpx)
  └── config.py      → env var configuration
          │
          ▼  HTTP
  OpenViking Server (port 1933)
```