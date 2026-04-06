# NotebookEdit Tool

## Overview

The notebook tool (`src/tools/notebook.py`) edits Jupyter notebook (.ipynb) cells. It supports reading notebook structure, inserting, replacing, and deleting cells.

---

## Tool: `notebook_edit`

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `path` | string | Yes | Path to the .ipynb file |
| `action` | string | Yes | `read`, `insert`, `replace`, `delete` |
| `cell_index` | integer | No | 0-based cell index |
| `cell_type` | string | No | `code`, `markdown`, or `raw` (default `code`) |
| `content` | string | No | Cell content for insert/replace |

---

## Actions

### `read`

Returns notebook structure: cell count, kernel info, and a preview of each cell with its type and output count.

### `insert`

Insert a new cell at the given index. If no index is given, appends to the end. If the file doesn't exist and the path ends with `.ipynb`, creates a new notebook.

### `replace`

Replace the content of a cell at the given index. Preserves the cell type unless `cell_type` is specified.

### `delete`

Remove a cell at the given index.

---

## Example

```
1. notebook_edit(path="analysis.ipynb", action="read")
   → Shows 5 cells: [0] code, [1] markdown, ...

2. notebook_edit(path="analysis.ipynb", action="insert",
     cell_index=2, cell_type="code", content="df.describe()")
   → Inserted code cell at index 2

3. notebook_edit(path="analysis.ipynb", action="replace",
     cell_index=0, content="import pandas as pd\nimport numpy as np")
   → Replaced cell 0

4. notebook_edit(path="analysis.ipynb", action="delete", cell_index=4)
   → Deleted cell 4
```
