# Build Prompt: Red-Team Write Verification (AD-365)

## Context

GPT-5.4 code review found that `write_file` intents have no real red-team
verification. `RedTeamAgent.verify()` explicitly handles `read_file`,
`stat_file`, `run_command`, and `http_fetch`, but any other intent type
(including `write_file`) falls through to a default that returns
`verified=True` with `confidence=0.1` and the discrepancy message
"Cannot verify intent type: write_file".

In `runtime.submit_write_with_consensus()` (line 1229), only the boolean
`verified` field is checked — not confidence. So `write_file` always passes
"verification" without any real check. The governance path for writes is
weaker than it appears.

**Identified by:** GPT-5.4 code review (2026-03-21)

---

## Changes

### File: `src/probos/agents/red_team.py`

**Change 1:** Add a `write_file` handler to the `verify()` method dispatch
chain. Insert it between the `http_fetch` handler (line 82) and the `else`
fallback (line 84):

```python
elif intent_name == "write_file":
    return await self._verify_write(target_agent_id, intent, claimed_result, params)
```

**Change 2:** Add a `_verify_write` method. The red team cannot "re-execute"
a write to verify it (that would write twice). Instead, it independently
validates the proposed write:

```python
async def _verify_write(
    self,
    target_agent_id: str,
    intent: IntentMessage,
    claimed: IntentResult,
    params: dict[str, Any],
) -> VerificationResult:
    """Verify a write_file proposal by validating the path and content."""
    path = params.get("path", "")
    content = params.get("content")

    # Basic sanity checks
    issues: list[str] = []

    if not path:
        issues.append("Empty write path")
    if content is None:
        issues.append("No content provided")

    if path:
        p = Path(path)
        # Path traversal check
        try:
            resolved = p.resolve()
            # Check for suspicious path components
            if ".." in p.parts:
                issues.append(f"Path traversal detected: {path}")
        except (OSError, ValueError) as e:
            issues.append(f"Invalid path: {e}")

        # Forbidden paths — system-critical files
        forbidden = (".git/", ".env", "pyproject.toml", ".github/workflows/")
        normalized = path.replace("\\", "/")
        for f in forbidden:
            if normalized.startswith(f) or normalized == f.rstrip("/"):
                issues.append(f"Write to forbidden path: {path}")
                break

    if content is not None and len(content) > 1_000_000:
        issues.append(f"Content suspiciously large: {len(content)} bytes")

    if issues:
        self.update_confidence(True)
        return VerificationResult(
            verifier_id=self.id,
            target_agent_id=target_agent_id,
            intent_id=intent.id,
            verified=False,
            discrepancy="; ".join(issues),
            confidence=self.confidence,
        )

    # Write proposal looks safe
    self.update_confidence(True)
    return VerificationResult(
        verifier_id=self.id,
        target_agent_id=target_agent_id,
        intent_id=intent.id,
        verified=True,
        confidence=self.confidence,
    )
```

---

## Tests

### File: `tests/test_red_team.py`

Add tests for the new write verification. Find the existing test class for
`RedTeamAgent` and add:

```python
@pytest.mark.asyncio
async def test_verify_write_valid_path(red_team_agent):
    """Valid write proposals should pass verification."""
    intent = IntentMessage(intent="write_file", params={
        "path": "src/probos/agents/new_agent.py",
        "content": "class NewAgent: pass\n",
    })
    claimed = IntentResult(intent_id=intent.id, agent_id="writer-1", success=True)
    result = await red_team_agent.verify("writer-1", intent, claimed)
    assert result.verified is True
    assert result.confidence > 0.1  # Not the fallback confidence

@pytest.mark.asyncio
async def test_verify_write_path_traversal(red_team_agent):
    """Path traversal in write should fail verification."""
    intent = IntentMessage(intent="write_file", params={
        "path": "../../etc/passwd",
        "content": "malicious",
    })
    claimed = IntentResult(intent_id=intent.id, agent_id="writer-1", success=True)
    result = await red_team_agent.verify("writer-1", intent, claimed)
    assert result.verified is False
    assert "traversal" in result.discrepancy.lower()

@pytest.mark.asyncio
async def test_verify_write_forbidden_path(red_team_agent):
    """Writes to forbidden paths should fail verification."""
    intent = IntentMessage(intent="write_file", params={
        "path": ".git/config",
        "content": "bad",
    })
    claimed = IntentResult(intent_id=intent.id, agent_id="writer-1", success=True)
    result = await red_team_agent.verify("writer-1", intent, claimed)
    assert result.verified is False
    assert "forbidden" in result.discrepancy.lower()

@pytest.mark.asyncio
async def test_verify_write_empty_path(red_team_agent):
    """Empty path should fail verification."""
    intent = IntentMessage(intent="write_file", params={
        "path": "",
        "content": "data",
    })
    claimed = IntentResult(intent_id=intent.id, agent_id="writer-1", success=True)
    result = await red_team_agent.verify("writer-1", intent, claimed)
    assert result.verified is False
```

If `red_team_agent` is not an existing fixture, create one:
```python
@pytest.fixture
def red_team_agent():
    return RedTeamAgent(agent_id="rt-test", pool="red_team")
```

---

## Constraints

- Modify ONLY `src/probos/agents/red_team.py` and `tests/test_red_team.py`
- Follow the exact pattern of existing `_verify_*` methods in the same file
- Do NOT modify `runtime.py`, `file_writer.py`, or any other file
- The verification must NOT actually write anything — it only validates the proposal
- Run `pytest tests/test_red_team.py -x -q` to verify
