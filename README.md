# 🧠 OpenViking Plugin for MindRoom

> Long-term memory for MindRoom agents via [OpenViking](https://github.com/volcengine/OpenViking) — an agent-native context database with tiered context loading, automatic session memory extraction, and directory-recursive retrieval.

**License:** MIT (plugin) · AGPL-3.0 (OpenViking server, communicated via HTTP service boundary)

## What It Does

Gives MindRoom agents persistent memory that survives context compaction and service restarts. Memories are automatically extracted from conversations (profile, preferences, entities, events, cases, patterns) and recalled when relevant.

## How It Works

| Hook | Event | Priority | Description |
|------|-------|----------|-------------|
| `openviking-init-session` | `session:started` | 10 | Creates an OpenViking session keyed by `room_id:thread_id` |
| `openviking-recall` | `message:enrich` | 30 | Queries OpenViking before each prompt, injects relevant memories as context |
| `openviking-archive-turn` | `message:after_response` | 50 | Sends conversation turns after each response; triggers `commit()` at token threshold for async memory extraction |
| `openviking-pre-compaction` | `compaction:before` | 10 | Saves messages synchronously before MindRoom compacts the context window |

## Agent Tools

| Tool | Description |
|------|-------------|
| `memory_recall(query)` | Search long-term memory for relevant context |
| `memory_store(content, category="general")` | Explicitly store a memory (creates session → adds message → commits) |
| `memory_forget(query)` | Find and delete memories matching a query |

## Setup

### 1. Install the Plugin

```bash
cd ~/.mindroom-chat/plugins/
git clone https://git.nijho.lt/basnijholt/openviking-plugin.git openviking
```

### 2. Configure MindRoom

Add to your `config.yaml`:

```yaml
plugins:
  - path: ~/.mindroom-chat/plugins/openviking

agents:
  my-agent:
    tools:
      - openviking   # adds memory_recall, memory_store, memory_forget
```

### 3. Start the OpenViking Server

⚠️ **Python 3.14 is not supported** — OpenViking has Pydantic V1 compatibility issues. Use Python 3.13.

⚠️ **`openviking-server` and `uvicorn.run()` exit silently** — you must use `uvicorn` CLI with the `--factory` flag.

```bash
OPENAI_API_KEY=<your-litellm-proxy-key> \
  uvx --python 3.13 --with openviking --with litellm \
  uvicorn openviking.server.app:create_app --factory \
  --host 127.0.0.1 --port 1933
```

Run this in a tmux session or systemd service so it stays up.

### 4. Configure OpenViking

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
      "model": "your-embedding-model",
      "dimension": 768,
      "api_base": "http://your-litellm-proxy:4000/v1",
      "api_key": "$OPENAI_API_KEY"
    }
  },
  "vlm": {
    "provider": "openai",
    "model": "your-llm-model",
    "api_base": "http://your-litellm-proxy:4000/v1",
    "api_key": "$OPENAI_API_KEY",
    "temperature": 0.0,
    "max_concurrent": 10
  },
  "storage": {
    "workspace": "/home/you/.openviking/data"
  }
}
```

**Key points:**
- **`embedding`** — required for vector search. Any OpenAI-compatible embedding API works.
- **`vlm`** — required for automatic memory extraction from sessions. Without this, sessions commit but no memories are extracted ("LLM not available, skipping memory extraction"). Any OpenAI-compatible chat completion API works (routed via LiteLLM).
- **`auth_mode: "trusted"`** — localhost auth via HTTP headers. The plugin sends `X-OpenViking-Account: default` and `X-OpenViking-User: mindroom` headers automatically.
- **`$OPENAI_API_KEY`** — environment variables in the config are expanded at load time. Set the env var when starting the server.

### 5. Verify

```bash
# Check server health
curl http://127.0.0.1:1933/api/v1/health

# Test memory store + recall
curl -X POST http://127.0.0.1:1933/api/v1/sessions \
  -H 'Content-Type: application/json' \
  -H 'X-OpenViking-Account: default' \
  -H 'X-OpenViking-User: mindroom' \
  -d '{"session_id": "test-session"}'
```

## Plugin Configuration

Environment variables (override defaults):

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENVIKING_URL` | `http://localhost:1933` | OpenViking server URL |
| `OPENVIKING_RECALL_MAX_TOKENS` | `2000` | Max tokens for recalled memory context |
| `OPENVIKING_COMMIT_TOKEN_THRESHOLD` | `8000` | Token count that triggers session commit |

## Architecture

```
MindRoom Agent
  ├── hooks.py      → lifecycle hooks (session init, recall, archive, compaction)
  ├── tools.py      → agent-callable tools (recall, store, forget)
  ├── client.py     → async HTTP client (httpx → OpenViking API)
  ├── config.py     → env var configuration
  └── mindroom.plugin.json
          │
          ▼ HTTP (service boundary — AGPL-clean)
  OpenViking Server (port 1933)
  ├── Session management (create → messages → commit → extract)
  ├── Memory extraction (8 categories via LLM)
  ├── Vector search (embeddings)
  └── Filesystem storage (~/.openviking/data/)
```

The plugin communicates with OpenViking exclusively over HTTP. The OpenViking server (AGPL-3.0) runs as a separate process. This plugin (MIT) never imports or links OpenViking code.

## Memory Categories

OpenViking automatically extracts memories into 8 categories:

| Category | Type | Description |
|----------|------|-------------|
| Profile | User | Bio, role, background |
| Preferences | User | Settings, habits, style |
| Entities | User | Projects, people, concepts |
| Events | User | Decisions, milestones |
| Cases | Agent | Problem → solution pairs |
| Patterns | Agent | Reusable processes |
| Tools | Skill | Tool usage and optimization |
| Skills | Skill | Workflow and strategy |