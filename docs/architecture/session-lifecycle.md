# Session Lifecycle

## Session States

A session progresses through these states:

```
Not started
    ↓ CLI invoked
Initializing (config load, provider setup)
    ↓ all setup complete
Active (REPL accepting input)
    ↓ user submits message
Processing (waiting for model response)
    ↓ model responds
Executing tools (tool calls in progress)
    ↓ all tools complete
Active (back to waiting for input)
    ↓ user types /exit or Ctrl+D
Ending (final cleanup)
    ↓ session saved, resources released
Ended
```

Sessions can also transition:
- From **Active** → **Compacting** (manual `/compact`) → **Active**
- From any state → **Error** (unrecoverable error)

---

## Session Storage

Sessions are stored as JSON files in `.zwis/sessions/`:

```
.zwis/sessions/
├── session-1734567890123.json
├── session-1734567891234.json
└── ...
```

Each session file contains:
- Session ID (timestamp-based)
- Conversation history (messages array)
- Token usage statistics
- Session metadata (provider, model, start time)

---

## Session Resume

### Continue Last Session

```bash
zwis chat --continue
```

Loads the most recent session from `.zwis/sessions/` and restores the conversation history. The REPL continues from where the last session ended.

### Resume Specific Session

```bash
zwis chat --resume session-1734567890123
```

Loads a specific session by ID.

### Save Current Session

```bash
# Inside the REPL:
/save
```

Saves the current session to `.zwis/sessions/`. Sessions are also auto-saved on clean exit.

### List Sessions

```bash
zwis sessions
```

Lists all saved sessions with their IDs, timestamps, and turn counts.

---

## Session State Object

`src/core/session.py` defines `SessionState`:

- `session_id`: Unique identifier (timestamp-based)
- `messages`: List of conversation messages
- `turn_count`: Number of completed turns
- `total_input_tokens`: Cumulative input token count
- `total_output_tokens`: Cumulative output token count
- `provider`: LLM provider name
- `model`: Model name/alias
- `created_at`: Session creation timestamp

### Serialization

`SessionState` supports:
- `to_dict()` → JSON-serializable dictionary
- `from_dict()` → Restore from saved session
- `save(path)` → Write to `.zwis/sessions/`
