# HXI Slash Command Output Fix — Clean Text for Chat

## Problem

Slash commands (`/status`, `/agents`, `/model`, etc.) output Rich-formatted terminal panels with box-drawing characters (`│`, `─`, `┌`, `┘`) that render as broken characters in the HXI chat bubble. The chat is HTML, not a terminal.

## Fix

**File:** `src/probos/api.py` — in `_handle_slash_command()`

The current implementation captures Rich console output with `no_color=True` but Rich still emits box-drawing characters for panels and tables. Strip all box-drawing and Rich formatting to produce clean readable text.

After capturing the output from the shell, clean it:

```python
import re

def _strip_rich_formatting(text: str) -> str:
    """Strip Rich panel/table box-drawing characters for clean text output."""
    # Remove box-drawing characters
    text = re.sub(r'[─━│┃┌┐└┘├┤┬┴┼╭╮╰╯╋╸╹╺╻═║╔╗╚╝╠╣╦╩╬]', '', text)
    # Remove ANSI escape sequences (in case any slip through)
    text = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', text)
    # Collapse multiple spaces into one
    text = re.sub(r'  +', '  ', text)
    # Remove leading/trailing whitespace per line
    lines = [line.strip() for line in text.split('\n')]
    # Remove empty lines at start/end, collapse multiple blank lines
    cleaned: list[str] = []
    for line in lines:
        if line or (cleaned and cleaned[-1]):
            cleaned.append(line)
    return '\n'.join(cleaned).strip()
```

Apply this to the response before returning:

```python
response_text = _strip_rich_formatting(output.getvalue().strip())
```

## Future: Adaptive Cards

When the HXI matures, slash commands should return structured JSON that the frontend renders as styled cards:

```json
{
  "response": "",
  "card": {
    "type": "status",
    "title": "System Status",
    "fields": [
      {"label": "Version", "value": "0.1.0"},
      {"label": "Agents", "value": 55},
      {"label": "Health", "value": 0.82, "format": "percent"}
    ],
    "tables": [
      {
        "title": "Pools",
        "columns": ["Pool", "Size", "Type"],
        "rows": [["system", "2/2", "system_heartbeat"], ...]
      }
    ]
  }
}
```

The frontend would render these as styled HTML cards matching the HXI visual design. But that's a future phase — for now, clean text is sufficient.

## After fix

Restart `probos serve`. Type `/status` in the HXI chat — should show clean, readable text without box characters.

No frontend changes needed — the chat bubble already displays plain text fine.
