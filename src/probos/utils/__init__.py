from __future__ import annotations


def format_duration(seconds: float) -> str:
    """Format seconds into human-readable duration string.

    Examples: "45s", "3m 12s", "2h 15m", "3d 5h"
    """
    seconds = max(0.0, seconds)
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        return f"{int(seconds // 60)}m {int(seconds % 60)}s"
    elif seconds < 86400:
        hours = int(seconds // 3600)
        mins = int((seconds % 3600) // 60)
        return f"{hours}h {mins}m"
    else:
        days = int(seconds // 86400)
        hours = int((seconds % 86400) // 3600)
        return f"{days}d {hours}h"
