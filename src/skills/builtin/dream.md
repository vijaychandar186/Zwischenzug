---
name: dream
description: Consolidate and clean up memory files to reduce redundancy and improve organization
allowedTools: [read_file, write_file, glob]
context: inline
---
Review and consolidate the memory files in the memory directory.

Steps:
1. List all memory files (glob `~/.zwis/memory/*.md`).
2. Read MEMORY.md index and each individual memory file.
3. Identify:
   - Duplicate or near-duplicate memories (merge them)
   - Stale memories (information that no longer applies — remove them)
   - Memories that reference code/files that may have changed (flag for verification)
   - Memories that could be organized better (split or rename)
4. Update memory files: merge redundant entries, remove outdated ones, improve descriptions.
5. Rebuild the MEMORY.md index to reflect changes.

Keep entries concise and actionable. The index should be under 200 lines.
Memory content should be specific enough to be useful but not so detailed it becomes noise.

{{{args}}}
