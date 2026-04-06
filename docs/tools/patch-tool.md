# Apply Patch Tool

## Overview

The `apply_patch` tool (`src/tools/patch.py`) applies unified diff patches to one or more files. It supports the standard format produced by `git diff` or `diff -u`, with context matching and per-hunk success/failure reporting.

---

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `patch` | string | Yes | Unified diff content |

---

## Supported Features

- **Multi-file patches**: A single patch can modify multiple files
- **New file creation**: `--- /dev/null` patches create new files
- **Context matching**: Uses ±3 line fuzzy matching for hunk placement
- **Per-hunk reporting**: Reports success/failure for each hunk independently
- **Relative paths**: Paths are resolved relative to the session's working directory
- **Strip a/b prefixes**: Automatically strips `a/` and `b/` from diff paths

---

## Example

```diff
--- a/src/foo.py
+++ b/src/foo.py
@@ -10,3 +10,4 @@
 context line
-old line
+new line
+added line
 context line
```

---

## Error Handling

- Returns error if patch content is empty
- Returns error if diff cannot be parsed
- Reports per-hunk failures when context doesn't match
- Partial success: if some hunks apply and others fail, applied hunks are written and the error is reported
