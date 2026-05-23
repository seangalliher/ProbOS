"""AD-812: tests for natural-language schedule parser."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest

from probos.cognitive.schedule_parser import ScheduleSpec, parse_nl_schedule


@dataclass
class _FakeResponse:
    content: str = ""


class _FakeLLM:
    """Stub LLM client returning a pre-canned string."""

    def __init__(self, output: str) -> None:
        self.output = output
        self.calls = 0

    async def complete(self, req):
        self.calls += 1
        return _FakeResponse(content=self.output)


@pytest.mark.asyncio
async def test_regex_fast_path_in_minutes() -> None:
    now = 1_700_000_000.0
    llm = _FakeLLM("")
    spec = await parse_nl_schedule(
        "in 5 minutes pick up groceries", llm_client=llm, now=now
    )
    assert spec.kind == "once"
    assert spec.execute_at == pytest.approx(now + 300, abs=1)
    assert "pick up groceries" in spec.intent_text
    assert llm.calls == 0  # regex short-circuited


@pytest.mark.asyncio
async def test_regex_fast_path_in_hours() -> None:
    now = 1_700_000_000.0
    spec = await parse_nl_schedule(
        "in 2 hours check the agent fleet", llm_client=None, now=now
    )
    assert spec.kind == "once"
    assert spec.execute_at == pytest.approx(now + 7200, abs=1)
    assert "check the agent fleet" in spec.intent_text


@pytest.mark.asyncio
async def test_llm_once_tomorrow_9am() -> None:
    now = time.time()
    tomorrow_9 = datetime.fromtimestamp(now, tz=timezone.utc) + timedelta(days=1)
    tomorrow_9 = tomorrow_9.replace(hour=9, minute=0, second=0, microsecond=0)
    iso = tomorrow_9.isoformat()
    llm = _FakeLLM(
        json.dumps(
            {
                "kind": "once",
                "execute_at_iso": iso,
                "intent_text": "send a status report",
                "channel": None,
                "interval_seconds": None,
                "cron_expr": None,
                "max_runs": None,
            }
        )
    )
    spec = await parse_nl_schedule(
        "tomorrow at 9am send a status report", llm_client=llm, now=now
    )
    assert spec.kind == "once"
    assert spec.intent_text == "send a status report"
    assert spec.execute_at == pytest.approx(tomorrow_9.timestamp(), abs=1)
    assert spec.channel_id is None


@pytest.mark.asyncio
async def test_llm_cron_weekly_monday() -> None:
    llm = _FakeLLM(
        json.dumps(
            {
                "kind": "cron",
                "cron_expr": "0 9 * * 1",
                "intent_text": "send weekly summary",
                "channel": None,
            }
        )
    )
    spec = await parse_nl_schedule(
        "every Monday at 9am send weekly summary", llm_client=llm
    )
    assert spec.kind == "cron"
    assert spec.cron_expr == "0 9 * * 1"
    assert spec.intent_text == "send weekly summary"
    assert spec.channel_id is None


@pytest.mark.asyncio
async def test_llm_cron_with_channel_telegram() -> None:
    llm = _FakeLLM(
        json.dumps(
            {
                "kind": "cron",
                "cron_expr": "0 7 * * 1-5",
                "intent_text": "send my LinkedIn metrics",
                "channel": "telegram",
            }
        )
    )
    spec = await parse_nl_schedule(
        "every weekday at 7am send my LinkedIn metrics to Telegram",
        llm_client=llm,
    )
    assert spec.kind == "cron"
    assert spec.cron_expr == "0 7 * * 1-5"
    assert spec.channel_id == "telegram:default"


@pytest.mark.asyncio
async def test_llm_unavailable_no_regex_match_errors_honestly() -> None:
    spec = await parse_nl_schedule(
        "every Monday at 9am send weekly summary", llm_client=None
    )
    assert spec.kind == "error"
    assert "LLM unavailable" in spec.reason


@pytest.mark.asyncio
async def test_llm_returns_non_json_errors_honestly() -> None:
    llm = _FakeLLM("sure thing!")
    spec = await parse_nl_schedule(
        "every Monday at 9am send weekly summary", llm_client=llm
    )
    assert spec.kind == "error"
    assert spec.reason == "LLM returned non-JSON output"


@pytest.mark.asyncio
async def test_llm_returns_invalid_cron_errors_honestly() -> None:
    llm = _FakeLLM(
        json.dumps(
            {
                "kind": "cron",
                "cron_expr": "NOT VALID",
                "intent_text": "x",
                "channel": None,
            }
        )
    )
    spec = await parse_nl_schedule("every banana send x", llm_client=llm)
    assert spec.kind == "error"
    assert "invalid cron_expr" in spec.reason


@pytest.mark.asyncio
async def test_past_execute_at_rejected() -> None:
    now = 1_700_000_000.0
    past = datetime.fromtimestamp(now - 3600, tz=timezone.utc).isoformat()
    llm = _FakeLLM(
        json.dumps(
            {
                "kind": "once",
                "execute_at_iso": past,
                "intent_text": "do thing",
                "channel": None,
            }
        )
    )
    spec = await parse_nl_schedule("an hour ago do thing", llm_client=llm, now=now)
    assert spec.kind == "error"
    assert "past" in spec.reason
