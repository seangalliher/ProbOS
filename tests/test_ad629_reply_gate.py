"""AD-629: Post ID Context in Ward Room threads.

BF-201: check_and_increment_reply_cap and department gate removed.
Remaining tests: post IDs in thread context and proactive activity.
"""

from __future__ import annotations


# ══════════════════════════════════════════════════════════════════════
# TestPostIdInContext
# ══════════════════════════════════════════════════════════════════════


class TestPostIdInContext:
    """Post IDs in thread context and proactive activity."""

    def test_thread_context_includes_post_ids(self):
        """Thread context format: [id[:8]] callsign: body."""
        thread_detail = {
            "thread": {
                "title": "Test Thread",
                "body": "Root post body",
            },
            "posts": [
                {
                    "id": "abcdef12-3456-7890-abcd-ef1234567890",
                    "author_callsign": "Scotty",
                    "body": "Engines nominal",
                },
                {
                    "id": "12345678-abcd-ef12-3456-7890abcdef12",
                    "author_callsign": "LaForge",
                    "body": "Confirmed",
                },
            ],
        }

        posts = thread_detail["posts"]
        thread_context = f"Thread: {thread_detail['thread']['title']}\n{thread_detail['thread']['body']}"
        recent_posts = posts[-5:] if len(posts) > 5 else posts
        for p in recent_posts:
            p_id = p.get("id", "") if isinstance(p, dict) else getattr(p, "id", "")
            p_callsign = p.get("author_callsign", "") if isinstance(p, dict) else getattr(p, "author_callsign", "")
            p_body = p.get("body", "") if isinstance(p, dict) else getattr(p, "body", "")
            _id_prefix = f"[{p_id[:8]}] " if p_id else ""
            thread_context += f"\n{_id_prefix}{p_callsign}: {p_body}"

        assert "[abcdef12] Scotty: Engines nominal" in thread_context
        assert "[12345678] LaForge: Confirmed" in thread_context

    def test_proactive_activity_includes_post_ids(self):
        """Ward Room activity body field includes [post_id[:8]] prefix."""
        activity = [
            {
                "type": "post",
                "author": "Scotty",
                "title": "Status update",
                "body": "Engines nominal",
                "net_score": 2,
                "post_id": "abcdef12-3456-7890-abcd-ef1234567890",
                "thread_id": "thread-1",
                "created_at": 1000.0,
            },
        ]

        formatted = []
        for a in activity:
            pid = a.get("post_id", a.get("id", "")) or ""
            body = (f"[{pid[:8]}] " if pid else "") + (a.get("title", a.get("body", ""))[:500])
            formatted.append(body)

        assert formatted[0] == "[abcdef12] Status update"

    def test_activity_without_post_id_no_prefix(self):
        """Activity items without post_id get no prefix."""
        activity = [
            {
                "type": "post",
                "author": "Scotty",
                "body": "Engines nominal",
                "net_score": 0,
                "post_id": "",
                "thread_id": "thread-1",
                "created_at": 1000.0,
            },
        ]

        pid = activity[0].get("post_id", activity[0].get("id", "")) or ""
        body = (f"[{pid[:8]}] " if pid else "") + (activity[0].get("body", "")[:500])
        assert body == "Engines nominal"
