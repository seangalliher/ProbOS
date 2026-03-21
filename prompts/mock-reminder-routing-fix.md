# Build Prompt: Mock Reminder Routing Fix (AD-363)

## Context

GPT-5.4 code review found that `MockLLMClient` routes "remind me to..." phrases
to `TodoAgent` instead of `SchedulerAgent`. The mock's pattern table is
first-match-wins, and `manage_todo` is registered before `manage_schedule`. The
todo regex includes `remind me to` as a final alternative, so it captures
reminder phrases before the scheduler regex gets a chance.

This only affects `MockLLMClient` (tests, demos, local dev), not production LLM
routing. But it masks scheduler regressions by making reminder phrases appear
supported while hitting the wrong agent.

**Identified by:** GPT-5.4 code review (2026-03-21)

---

## Changes

### File: `src/probos/cognitive/llm_client.py`

**Change 1:** Remove `remind me to` from the `manage_todo` regex (line 557).

Before:
```python
r"todo|to-do|task list|add.* to (?:my )?list|remind me to"
```

After:
```python
r"todo|to-do|task list|add.* to (?:my )?list"
```

**Change 2:** Add `remind me` to the `manage_schedule` regex (line 569).

Before:
```python
r"(?:set|create) (?:a )?reminder|schedule|(?:my )?calendar|upcoming|what.s (?:coming )?up"
```

After:
```python
r"remind(?:er| me)|(?:set|create) (?:a )?reminder|schedule|(?:my )?calendar|upcoming|what.s (?:coming )?up"
```

The `remind(?:er| me)` alternative at the front catches both "remind me to..."
and "reminder" phrasing, routing them to the scheduler where they belong.

---

## Tests

### File: `tests/test_llm_client.py`

Add a test that verifies reminder routing. Find the existing `MockLLMClient`
test class and add:

```python
@pytest.mark.asyncio
async def test_remind_me_routes_to_scheduler():
    """'Remind me to...' should route to manage_schedule, not manage_todo."""
    client = MockLLMClient()
    response = await client.complete(LLMRequest(
        prompt="remind me to call the dentist at 3pm",
        system="You are a helpful assistant.",
    ))
    import json
    data = json.loads(response.content)
    assert data["intent"] == "manage_schedule", (
        f"Expected manage_schedule but got {data['intent']}"
    )
```

---

## Constraints

- Modify ONLY `src/probos/cognitive/llm_client.py` (two regex changes) and the
  test file
- Do NOT change pattern registration order — just fix the regexes
- Do NOT modify any other mock patterns
- Run `pytest tests/test_llm_client.py -x -q` to verify
