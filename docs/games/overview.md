# Games

## Overview

Zwischenzug includes lightweight built-in terminal games that run locally inside the CLI. Games are not part of the agent loop and do not call the model. They are simple interactive extras exposed through both the top-level CLI and the REPL slash-command surface.

---

## Available Commands

| Surface | Command | Description |
|---------|---------|-------------|
| CLI | `zwis game flappy-bird` | Launch Flappy Bird from the terminal |
| REPL | `/game/flappy-bird` | Launch Flappy Bird without leaving the REPL |

---

## Flappy Bird

The built-in Flappy Bird implementation lives in `src/games/flappy_bird.py`.

### Behavior

- Shows a start screen and waits for `Space` before the round begins
- Uses `Space`, `W`, or `Up Arrow` to flap
- Uses `Q` to exit
- After a crash, offers restart or exit without dropping back to the REPL immediately

### Persistence

High scores are stored in:

```text
.zwis/games/flappy_bird.json
```

The file is reused if it already exists and created when the game first saves a score.

---

## Design Notes

- Uses the Python standard library for non-blocking terminal input
- Avoids external keyboard-hook dependencies
- Keeps all runtime data under `.zwis/`
- Keeps game logic separate from CLI and REPL wiring
