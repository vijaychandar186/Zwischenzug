---
name: compact
description: Summarize and compress the current conversation context
allowedTools: []
context: inline
---
Summarize the conversation so far into a concise context that preserves the essential information.

Create a summary that includes:
- **Task**: What was the user trying to accomplish?
- **Progress**: What has been done so far? What files were read or modified?
- **Key findings**: Important discoveries, decisions, or constraints
- **Current state**: Where things stand right now
- **Next steps**: What needs to happen next (if known)
- **User instructions**: Any explicit instructions the user gave that should be remembered

Format the summary as a brief document (aim for under 400 words). This summary will replace the conversation history.

{{{args}}}
