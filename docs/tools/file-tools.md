# File Tools

## Overview

File tools (`src/tools/files.py` and `src/tools/search.py`) provide the agent with file system read and write capabilities.

---

## FileRead

Reads a file and returns its contents with line numbers.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `file_path` | string | Yes | — | Absolute path to the file |
| `offset` | int | No | 0 | Line number to start reading from |
| `limit` | int | No | 2000 | Maximum number of lines to read |

**Read-only**: Yes

Returns file contents in `cat -n` format (line numbers + content).

---

## FileWrite

Writes content to a file, creating it if it doesn't exist or overwriting if it does.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `file_path` | string | Yes | — | Absolute path to the file |
| `content` | string | Yes | — | The content to write |

**Read-only**: No

---

## FileEdit

Performs exact string replacement in a file.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `file_path` | string | Yes | — | Absolute path to the file |
| `old_string` | string | Yes | — | The text to find and replace |
| `new_string` | string | Yes | — | The replacement text |

**Read-only**: No

The edit fails if `old_string` is not found or is not unique in the file. This ensures precise, unambiguous edits.

---

## Glob

Finds files matching a glob pattern.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `pattern` | string | Yes | — | Glob pattern (e.g., `**/*.py`, `src/**/*.md`) |
| `path` | string | No | CWD | Directory to search in |

**Read-only**: Yes

Returns matching file paths sorted by modification time (newest first).

---

## Grep

Searches file contents using regex patterns.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `pattern` | string | Yes | — | Regex pattern to search for |
| `path` | string | No | CWD | Directory to search in |
| `include` | string | No | — | Glob pattern to filter files |

**Read-only**: Yes

Returns matching lines with file paths and line numbers. Supports context lines (lines before/after matches).
