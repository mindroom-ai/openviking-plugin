# ISSUE-130: OpenViking MindRoom Plugin

## Overview
Build a MindRoom plugin that integrates with OpenViking (an external context database) over HTTP. The plugin provides:
1. **Auto-recall** — automatically injects relevant memories before each prompt
2. **Session archiving** — commits conversation turns to OpenViking after each response
3. **Pre-compaction archive** — saves messages to OpenViking before MindRoom compacts them away
4. **Memory tools** — `memory_recall`, `memory_store`, `memory_forget` for explicit agent use

## Plugin Location
`/home/basnijholt/.mindroom-chat/plugins/openviking/`

## Working Directory
You are working in: `/home/basnijholt/.mindroom-chat/plugins/openviking/`

## MindRoom Plugin System
MindRoom plugins are directories with a `mindroom.plugin.json` manifest pointing to hooks and tools modules.

### Manifest format (`mindroom.plugin.json`):
```json
{"name": "openviking", "hooks_module": "hooks.py", "tools_module": "tools.py"}
```

### Hook decorators
```python
from mindroom.hooks import hook, EnrichmentItem, MessageEnrichContext

@hook(event="message:enrich", name="openviking-recall", priority=30, timeout_ms=5000)
async def recall_memories(ctx: MessageEnrichContext) -> list[EnrichmentItem]:
    # Return list of EnrichmentItem(key=..., text=..., cache_policy="volatile")
    ...
```

### Available hook events for this plugin:
- `message:enrich` — inject context before each prompt. Return `list[EnrichmentItem]`.
- `message:after_response` — fires after agent responds. Context has `ctx.messages`, `ctx.room_id`, `ctx.thread_id`.
- `compaction:before` — fires before compaction. Context: `CompactionHookContext` with `ctx.messages`, `ctx.session_id`, `ctx.token_count_before`.
- `session:started` — fires when new session begins. Context: `SessionHookContext` with `ctx.session_id`, `ctx.room_id`, `ctx.thread_id`.

### Tool registration
```python
from mindroom.hooks import tool

@tool(name="memory_recall", description="Search long-term memory for relevant information")
async def memory_recall(query: str) -> str:
    ...
```

## Reference: Existing Plugin (thread-goal)
Look at `/home/basnijholt/.mindroom-chat/plugins/thread-goal/` for the pattern:
- `hooks.py` — hook functions with `@hook` decorator
- `tools.py` — tool functions with `@tool` decorator  
- `state.py` — shared state/helper code
- `mindroom.plugin.json` — manifest
- `tests/` — tests directory

## OpenViking HTTP API
OpenViking runs as a standalone server on `http://localhost:1933`. Key endpoints:

### Session management
```
POST /api/v1/sessions
  body: {"session_id": "...", "auto_create": true}
  
POST /api/v1/sessions/{session_id}/messages
  body: {"role": "user"|"assistant", "parts": [{"type": "text", "text": "..."}]}

POST /api/v1/sessions/{session_id}/commit
  → Archives messages, triggers async memory extraction
```

### Memory operations  
```
POST /api/v1/find
  body: {"query": "...", "namespaces": ["user", "agent"], "limit": 10}
  → Returns matching memories with URIs and content

POST /api/v1/resources
  body: {"uri": "viking://user/memories/...", "content": "..."}
  → Stores a memory

DELETE /api/v1/resources/{uri}
  → Deletes a memory

POST /api/v1/ls
  body: {"uri": "viking://user/memories/"}
  → Lists contents
```

### Health
```
GET /health → 200 OK
```

## Files to Create

### 1. `mindroom.plugin.json`
```json
{"name": "openviking", "hooks_module": "hooks.py", "tools_module": "tools.py"}
```

### 2. `client.py` — HTTP client wrapper
- Async HTTP client using `httpx` (or `aiohttp`) to talk to OpenViking
- Class `OpenVikingClient` with methods: `find()`, `add_message()`, `commit_session()`, `store_memory()`, `delete_memory()`, `ls()`, `health()`
- Base URL configurable, default `http://localhost:1933`
- Timeout handling, error logging
- Singleton/cached client instance

### 3. `hooks.py` — Hook functions
Four hooks:

**a) `recall_memories` (message:enrich, priority=30)**
- Extract latest user text from `ctx.messages`
- Call OpenViking `find()` with the user's message as query
- Filter/rerank results, respect token budget (~2000 tokens max)
- Return as `EnrichmentItem(key="openviking_memories", text=formatted_memories, cache_policy="volatile")`

**b) `archive_turn` (message:after_response, priority=50)**
- Take user message + assistant response from context
- POST them to OpenViking session
- If accumulated tokens exceed threshold (8000), trigger `commit()`

**c) `pre_compaction_archive` (compaction:before, priority=10)**
- Archive all messages being compacted to OpenViking session
- Trigger synchronous `commit(wait=true)` to ensure nothing is lost

**d) `init_session` (session:started, priority=10)**
- Initialize OpenViking session for this thread
- Create session with `auto_create=true`

### 4. `tools.py` — Agent-facing tools
Three tools:

**a) `memory_recall(query: str) -> str`**
- Explicit memory search — agent calls this when it wants to look something up
- Calls `find()`, formats results

**b) `memory_store(content: str, category: str = "general") -> str`**  
- Agent explicitly stores a memory
- Stores to `viking://user/memories/{category}/`

**c) `memory_forget(query: str) -> str`**
- Search for matching memories, delete them
- Returns what was deleted

### 5. `config.py` — Configuration
- `OPENVIKING_URL` — env var or default `http://localhost:1933`
- `RECALL_MAX_TOKENS` — max tokens for injected memories (default 2000)
- `COMMIT_TOKEN_THRESHOLD` — tokens before triggering commit (default 8000)

### 6. `LICENSE` — MIT license

### 7. `README.md` — Documentation

### 8. `tests/` — Unit tests with mocked HTTP

## Important Notes
- Use `httpx.AsyncClient` for async HTTP (it's already available in MindRoom's environment)
- The OpenViking server may not be running — handle connection errors gracefully (log warning, return empty results, don't crash)
- All hook functions must be async
- Keep the code functional style — no unnecessary classes beyond the HTTP client
- Type hints on everything
- The plugin must work standalone — no imports from MindRoom core except `mindroom.hooks`
- Don't import from other plugins

## Commit
When done, commit with: `git add -A && git commit -m "feat: OpenViking MindRoom plugin (ISSUE-130)"`
Write `.claude/REPORT.md` summarizing what you built.