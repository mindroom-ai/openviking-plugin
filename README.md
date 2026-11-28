# OpenViking

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![CI](https://github.com/mindroom-ai/openviking-plugin/actions/workflows/plugin-ci.yml/badge.svg)](https://github.com/mindroom-ai/openviking-plugin/actions/workflows/plugin-ci.yml)
[![Docs](https://img.shields.io/badge/docs-plugins-blue)](https://docs.mindroom.chat/plugins/)
[![Tools](https://img.shields.io/badge/docs-tools-blue)](https://docs.mindroom.chat/tools/)
[![Hooks](https://img.shields.io/badge/docs-hooks-blue)](https://docs.mindroom.chat/hooks/)

<picture>
  <source media="(prefers-reduced-motion: no-preference)" srcset="https://raw.githubusercontent.com/mindroom-ai/mindroom/main/assets/logo/logo-mark-animated.svg" />
  <img src="https://raw.githubusercontent.com/mindroom-ai/mindroom/main/assets/logo/logo-mark.svg" alt="MindRoom Logo" align="right" width="120" />
</picture>

A [MindRoom](https://github.com/mindroom-ai/mindroom) tool and hook plugin for persistent long-term memory backed by [OpenViking](https://github.com/volcengine/OpenViking).

OpenViking extracts memories from conversations across `user` and `agent` namespaces (profile, preferences, entities, events, cases, patterns, tools, and skills) and recalls relevant items before each turn, surviving context compaction and restarts:

```text
Relevant memories from long-term storage:
- [viking://user/memories/preferences/editor] Prefers concise diffs and pytest over unittest.
- [viking://agent/memories/patterns/deploys] Run database migrations before restarting workers.
```

- **Automatic recall:** queries OpenViking before each turn and injects matching memories up to the recall token budget.
- **Session archiving & pre-compaction flush:** archives turns per `room_id:thread_id` (or `room_id:default` outside threads), commits asynchronously at the token threshold, and commits synchronously before MindRoom compacts context.
- **Explicit memory tool:** lets agents recall, store, or forget memories directly via the `openviking` tool.
- **Graceful degradation:** if the OpenViking server is unreachable or returns errors, hooks log warnings and pass through without breaking turns.

## Quick start

```bash
mindroom plugins install openviking-plugin
```

Start an OpenViking server (see **Running the OpenViking server** below; defaults to `http://localhost:1933`), then enable the plugin and attach the `openviking` toolkit in `config.yaml`:

```yaml
plugins:
  - path: plugins/openviking-plugin

agents:
  my-agent:
    tools:
      - openviking
```

Update later with `mindroom plugins update openviking-plugin`.
Needs MindRoom v2026.11.187 or later (plugin API 1.2).

## Tools

Toolkit name: `openviking` (single action-based tool: `openviking(action, query=None, content=None, category=None)`).

| Action | Parameters | Purpose |
|--------|------------|---------|
| `recall` | `query` | Search `user` and `agent` namespaces (up to 10 results) for relevant long-term memories. |
| `store` | `content`, optional `category` (default `"general"`) | Store a memory by creating a one-off OpenViking session, adding the content, and committing it. `category` is currently ignored by OpenViking's session-commit storage. |
| `forget` | `query` | Search `user` and `agent` namespaces (up to 10 matches) and delete each matching memory URI. |

## Hooks

| Hook | Event | Priority | Purpose |
|------|-------|----------|---------|
| `openviking-init-session` | `session:started` | 10 | Create an OpenViking session keyed by `room_id:thread_id` (or `room_id:default` outside threads). |
| `openviking-recall` | `message:enrich` | 30 | Query `user` and `agent` namespaces and inject formatted memories up to `OPENVIKING_RECALL_MAX_TOKENS`. |
| `openviking-archive-turn` | `message:after_response` | 50 | Append the user and assistant messages and trigger an async commit at `OPENVIKING_COMMIT_TOKEN_THRESHOLD`. |
| `openviking-pre-compaction` | `compaction:before` | 10 | Archive compacted transcript lines (`Display Name (@user:server): text`) and commit synchronously (`wait=true`). |

## Settings

Configured via **process environment variables read at startup** (not `plugins[].settings` in `config.yaml`):

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENVIKING_URL` | `http://localhost:1933` | Base URL of the OpenViking HTTP server. |
| `OPENVIKING_RECALL_MAX_TOKENS` | `2000` | Approximate token budget (`~4` chars/token) for recalled memories injected per turn. |
| `OPENVIKING_COMMIT_TOKEN_THRESHOLD` | `8000` | Accumulated turn tokens per session before triggering an async session commit. |

<details>
<summary><b>Running the OpenViking server</b></summary>

### 1. Create `~/.openviking/ov.conf` first

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

- **`embedding`:** required for vector search (any OpenAI-compatible embedding endpoint works; set `api_base` for proxies or other providers).
- **`vlm`:** required for automatic memory extraction (without it, sessions commit without extracting memories).
- **`auth_mode: "trusted"`:** localhost header auth; the plugin sends `X-OpenViking-Account: default` and `X-OpenViking-User: mindroom` automatically.
- **`$OPENAI_API_KEY`:** environment variables in `ov.conf` are expanded when the server loads.

### 2. Start the server with `uvicorn`

- **Requires Python 3.13** — Python 3.14 has Pydantic V1 compatibility issues.
- **Use `uvicorn` CLI with `--factory`** — `openviking-server` and `uvicorn.run()` exit silently.

```bash
OPENAI_API_KEY=<your-key> \
  uvx --python 3.13 --with openviking --with litellm \
  uvicorn openviking.server.app:create_app --factory \
  --host 127.0.0.1 --port 1933
```

</details>

<details>
<summary><b>How it works &amp; compaction</b></summary>

1. **Session start (`session:started`):** probes server reachability (logging a startup warning once if unreachable) and creates an OpenViking session keyed by `room_id:thread_id` (or `room_id:default` for room-level sessions).
2. **Recall (`message:enrich`):** searches OpenViking (`namespaces=["user", "agent"]`, up to 10 hits) using the incoming message body and injects matching lines as a volatile enrichment item within `OPENVIKING_RECALL_MAX_TOKENS`.
3. **Turn archiving (`message:after_response`):** appends the user message and assistant reply to the session and increments an in-memory token counter (`len(text) // 4`). Once the counter reaches `OPENVIKING_COMMIT_TOKEN_THRESHOLD`, it triggers an async `commit()` for server-side memory extraction.
4. **Pre-compaction flush (`compaction:before`):** sends each compacted transcript line to the session—prefixing sender-attributed lines as `Display Name (@user:server): text` (or `@user:server: text` when no display name is present)—then calls `commit(wait=true)` synchronously so buffered turns are saved before compaction.
   - Transcript lines omit MindRoom-attached prompt enrichments, so recalled memories are not re-archived during compaction, while preserving other agents' messages and MindRoom thread notes (such as omitted-message notices).
   - Automation prompts and replies, job/media follow-up prompts, and replies of stopped turns are absent from compaction transcripts, though step 3 still archives every completed turn (including automation and job follow-ups).
5. **Explicit operations:** agents can recall, store, or forget memories directly via `openviking(action="recall" | "store" | "forget", ...)`.

</details>

<details>
<summary><b>Architecture and AGPL boundary</b></summary>

The plugin talks to OpenViking strictly over HTTP (`httpx`). The OpenViking server (AGPL-3.0) runs as a separate process, and this MIT-licensed plugin never imports or links OpenViking code.

```text
MindRoom Agent
  ├── hooks.py   → lifecycle hooks (init, recall, archive, compaction)
  ├── tools.py   → agent tool (openviking: recall, store, forget)
  ├── client.py  → async HTTP client (httpx)
  └── config.py  → process env var configuration
          │
          ▼  HTTP
  OpenViking Server (port 1933)
```

</details>
