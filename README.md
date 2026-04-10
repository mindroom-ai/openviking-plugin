# OpenViking MindRoom Plugin

A MindRoom plugin that integrates with [OpenViking](http://localhost:1933), an external context database, to provide long-term memory capabilities.

## Features

- **Auto-recall** — automatically injects relevant memories before each prompt
- **Session archiving** — commits conversation turns to OpenViking after each response
- **Pre-compaction archive** — saves messages to OpenViking before MindRoom compacts them
- **Memory tools** — `memory_recall`, `memory_store`, `memory_forget` for explicit agent use

## Configuration

Environment variables:

| Variable | Default | Description |
|---|---|---|
| `OPENVIKING_URL` | `http://localhost:1933` | OpenViking server URL |
| `OPENVIKING_RECALL_MAX_TOKENS` | `2000` | Max tokens for injected memories |
| `OPENVIKING_COMMIT_TOKEN_THRESHOLD` | `8000` | Token threshold before triggering commit |

## Installation

Place this directory at `~/.mindroom-chat/plugins/openviking/` and ensure OpenViking is running.

## Testing

```bash
cd ~/.mindroom-chat/plugins/openviking
pytest tests/
```

## License

MIT
