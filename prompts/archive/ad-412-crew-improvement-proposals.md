# AD-412: Crew Improvement Proposals Channel

## Context

The proactive cognitive loop generates crew observations that naturally evolve into actionable improvement recommendations. Currently these appear as organic Ward Room posts in department channels with no structured capture. AD-412 creates a dedicated `#improvement-proposals` channel with structured proposal format and Captain endorsement workflow.

This closes the collaborative improvement loop: crew observes → crew proposes → Captain approves → builder executes → crew observes the result.

## Changes

### Step 1: Seed the `#Improvement Proposals` channel

**File:** `src/probos/ward_room.py`

**1a. Add the channel in `_ensure_default_channels()`** (after the department channels loop, before `await self._db.commit()`):

```python
        # AD-412: Crew Improvement Proposals channel
        if "Improvement Proposals" not in existing:
            await self._db.execute(
                "INSERT INTO channels (id, name, channel_type, department, created_by, created_at, description) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), "Improvement Proposals", "ship", "", system_id, now,
                 "Structured crew improvement proposals — endorse to approve, downvote to shelve"),
            )
```

Use `channel_type="ship"` so all crew can see it (ship-wide visibility). Not a department channel.

### Step 2: Auto-subscribe all crew to the new channel

**File:** `src/probos/runtime.py`

In the startup block that subscribes crew to channels (search for `subscribe` near line 1231-1249 where crew auto-subscription happens), add the `#Improvement Proposals` channel to the subscription list alongside `All Hands`.

Find the loop that subscribes agents. After the existing All Hands + department subscription logic, add:

```python
            # AD-412: Subscribe all crew to Improvement Proposals
            proposals_ch = None
            for ch in channels:
                if ch.name == "Improvement Proposals":
                    proposals_ch = ch
                    break
            if proposals_ch:
                for agent_type in _WARD_ROOM_CREW:
                    pool = self.pool_manager.get_pool(agent_type)
                    if pool and pool.agents:
                        agent = pool.agents[0]
                        try:
                            await self.ward_room.subscribe(proposals_ch.id, agent.id)
                        except Exception:
                            pass
```

### Step 3: Add `propose_improvement` intent handler

**File:** `src/probos/runtime.py`

**3a. Add `propose_improvement` to the intent routing** in `handle_intent()` (search for the intent dispatch block — the large `if/elif` chain that matches `intent_type`). Add a new branch:

```python
        elif intent_type == "propose_improvement":
            return await self._handle_propose_improvement(intent, agent)
```

**3b. Add the handler method** on `ProbOSRuntime`:

```python
    async def _handle_propose_improvement(
        self, intent: Any, agent: Any,
    ) -> dict[str, Any]:
        """AD-412: Handle a crew improvement proposal — post to #Improvement Proposals."""
        if not self.ward_room:
            return {"success": False, "error": "Ward Room not available"}

        params = intent.params if hasattr(intent, "params") else intent.get("params", {})
        title = params.get("title", "Untitled Proposal")
        rationale = params.get("rationale", "")
        affected_systems = params.get("affected_systems", [])
        priority = params.get("priority_suggestion", "medium")

        # Validate required fields
        if not rationale:
            return {"success": False, "error": "Proposal requires a rationale"}

        # Find #Improvement Proposals channel
        channels = await self.ward_room.list_channels()
        proposals_ch = None
        for ch in channels:
            if ch.name == "Improvement Proposals":
                proposals_ch = ch
                break

        if not proposals_ch:
            return {"success": False, "error": "Improvement Proposals channel not found"}

        # Get callsign for attribution
        callsign = ""
        if hasattr(self, "callsign_registry"):
            callsign = self.callsign_registry.get_callsign(
                getattr(agent, "agent_type", "unknown")
            )

        # Format structured proposal body
        systems_str = ", ".join(affected_systems) if affected_systems else "Not specified"
        body = (
            f"**Proposed by:** {callsign or getattr(agent, 'agent_type', 'unknown')}\n"
            f"**Priority:** {priority}\n"
            f"**Affected Systems:** {systems_str}\n\n"
            f"**Rationale:**\n{rationale}"
        )

        # Create thread in proposals channel (DISCUSS mode — Captain can endorse/downvote)
        thread = await self.ward_room.create_thread(
            channel_id=proposals_ch.id,
            author_id=agent.id if hasattr(agent, "id") else "unknown",
            title=f"[Proposal] {title}",
            body=body,
            author_callsign=callsign,
            thread_mode="discuss",
        )

        return {
            "success": True,
            "thread_id": thread.id,
            "channel": "Improvement Proposals",
            "title": title,
        }
```

### Step 4: Add `propose_improvement` as a recognized skill for cognitive agents

**File:** `src/probos/cognitive/cognitive_agent.py`

**4a.** Find where `ward_room_reply` or other intents are listed in the system prompt or perceive() formatting. In the proactive think prompt section (where agents are told what they can do), add awareness of the proposal ability.

Search for the prompt section that describes proactive capabilities or Ward Room interaction. Add to the agent's system prompt instructions (the section in `perceive()` or `_build_system_prompt()` that describes what the agent can do):

After the existing Ward Room instructions, add:

```
If you identify a concrete, actionable improvement to the ship's systems, you may propose it by responding with a structured block:
[PROPOSAL]
Title: <short descriptive title>
Rationale: <why this improvement matters>
Affected Systems: <comma-separated list of affected subsystems>
Priority: <low|medium|high>
[/PROPOSAL]
```

**4b.** In the `act()` method or the response post-processing, detect the `[PROPOSAL]` block and extract it into a `propose_improvement` intent. Add this as a post-processing step after the LLM response is received.

Search for where the LLM response is processed in the proactive flow (in `proactive.py`, after receiving `response_text`). Add proposal extraction:

**File:** `src/probos/proactive.py`

After the response is received from the agent's think cycle (after line ~258, before `_post_to_ward_room`), add:

```python
        # AD-412: Check for structured improvement proposals
        await self._extract_and_post_proposal(agent, response_text)
```

Add the extraction method to `ProactiveCognitiveLoop`:

```python
    async def _extract_and_post_proposal(self, agent: Any, text: str) -> None:
        """AD-412: Extract [PROPOSAL] blocks and submit as improvement proposals."""
        import re
        pattern = r'\[PROPOSAL\]\s*\n(.*?)\n\[/PROPOSAL\]'
        match = re.search(pattern, text, re.DOTALL)
        if not match:
            return

        block = match.group(1)

        # Parse structured fields
        title = ""
        rationale = ""
        affected = []
        priority = "medium"

        for line in block.split('\n'):
            line = line.strip()
            if line.lower().startswith("title:"):
                title = line[6:].strip()
            elif line.lower().startswith("rationale:"):
                rationale = line[10:].strip()
            elif line.lower().startswith("affected systems:"):
                raw = line[17:].strip()
                affected = [s.strip() for s in raw.split(",") if s.strip()]
            elif line.lower().startswith("priority:"):
                p = line[9:].strip().lower()
                if p in ("low", "medium", "high"):
                    priority = p

        # Rationale may span multiple lines — capture everything after "Rationale:" that isn't another field
        if not rationale:
            in_rationale = False
            rationale_lines = []
            for line in block.split('\n'):
                stripped = line.strip()
                if stripped.lower().startswith("rationale:"):
                    rest = stripped[10:].strip()
                    if rest:
                        rationale_lines.append(rest)
                    in_rationale = True
                elif in_rationale:
                    if any(stripped.lower().startswith(f) for f in ("title:", "affected systems:", "priority:")):
                        in_rationale = False
                    else:
                        rationale_lines.append(stripped)
            rationale = "\n".join(rationale_lines).strip()

        if not title or not rationale:
            return  # Incomplete proposal — skip silently

        rt = self._runtime
        try:
            from probos.types import IntentMessage
            intent = IntentMessage(
                intent="propose_improvement",
                params={
                    "title": title,
                    "rationale": rationale,
                    "affected_systems": affected,
                    "priority_suggestion": priority,
                },
                context=f"Proactive proposal from {getattr(agent, 'agent_type', 'unknown')}",
            )
            await rt._handle_propose_improvement(intent, agent)
        except Exception:
            logger.debug("Failed to post improvement proposal from %s", getattr(agent, 'agent_type', 'unknown'), exc_info=True)
```

### Step 5: Add REST API endpoint for Captain to endorse proposals

The endorsement endpoints already exist (`POST /api/wardroom/threads/{id}/endorse`). No new endpoint needed for endorsement.

**Add a convenience endpoint to list proposals:**

**File:** `src/probos/api.py`

After the existing Ward Room endpoints, add:

```python
    @app.get("/api/wardroom/proposals")
    async def list_improvement_proposals(
        status: str | None = None, limit: int = 20,
    ) -> dict[str, Any]:
        """AD-412: List improvement proposals from the #Improvement Proposals channel."""
        if not runtime.ward_room:
            return {"proposals": []}

        # Find the Improvement Proposals channel
        channels = await runtime.ward_room.list_channels()
        proposals_ch = None
        for ch in channels:
            if ch.name == "Improvement Proposals":
                proposals_ch = ch
                break

        if not proposals_ch:
            return {"proposals": []}

        threads = await runtime.ward_room.list_threads(
            proposals_ch.id, limit=min(limit, 100),
        )

        proposals = []
        for t in threads:
            proposal = {
                "thread_id": t.id,
                "title": t.title,
                "body": t.body,
                "author": t.author_callsign or t.author_id,
                "created_at": t.created_at,
                "net_score": t.net_score,
                "reply_count": t.reply_count,
                "status": "approved" if t.net_score > 0 else "shelved" if t.net_score < 0 else "pending",
            }
            proposals.append(proposal)

        # Optional status filter
        if status:
            proposals = [p for p in proposals if p["status"] == status]

        return {"channel_id": proposals_ch.id, "proposals": proposals}
```

### Step 6: Add proactive prompt instruction

**File:** `src/probos/proactive.py`

In `_format_observation()` (the method that builds the proactive think prompt), add a line to the system-level instructions mentioning the proposal capability. Find the section where the think prompt is assembled (search for the prompt template or instructions).

Add to the instructions section:

```
If you identify a concrete, actionable improvement to the ship's systems (not a vague observation), propose it using:
[PROPOSAL]
Title: <short title>
Rationale: <why this matters and what it would improve>
Affected Systems: <comma-separated subsystems>
Priority: low|medium|high
[/PROPOSAL]
Only propose improvements you have evidence for — not speculation. Reserve proposals for genuine insights.
```

This should be appended to the existing think prompt, not replace it.

## Tests

**File:** `tests/test_ward_room.py` — Add new test class `TestImprovementProposals`.

### Test 1: Improvement Proposals channel is seeded at startup
```
Create a WardRoomService, start() it.
List channels.
Assert "Improvement Proposals" channel exists with channel_type="ship".
```

### Test 2: Improvement Proposals channel is idempotent
```
Create a WardRoomService, start() it.
Stop it. Start again.
Assert only ONE "Improvement Proposals" channel exists (not duplicated).
```

### Test 3: Thread can be created in proposals channel
```
Start WardRoomService.
Find the Improvement Proposals channel.
Create a thread with title="[Proposal] Better routing", body="Structured body".
Assert thread is created successfully in the correct channel.
```

**File:** `tests/test_proactive.py` — Add test class `TestProposalExtraction` (or add to existing).

### Test 4: _extract_and_post_proposal parses complete proposal block
```
Create a ProactiveCognitiveLoop with mock runtime that has ward_room.
Call _extract_and_post_proposal with text containing:
"Some observation.\n[PROPOSAL]\nTitle: Better routing\nRationale: Edge weights are stale after reset\nAffected Systems: HebbianRouter, TrustNetwork\nPriority: high\n[/PROPOSAL]\nMore text."
Assert _handle_propose_improvement was called with correct params.
```

### Test 5: _extract_and_post_proposal ignores text without proposal block
```
Call _extract_and_post_proposal with text "Just a normal observation, nothing special."
Assert _handle_propose_improvement was NOT called.
```

### Test 6: _extract_and_post_proposal skips incomplete proposals (no title)
```
Call _extract_and_post_proposal with "[PROPOSAL]\nRationale: something\n[/PROPOSAL]"
Assert _handle_propose_improvement was NOT called (title missing).
```

### Test 7: _extract_and_post_proposal skips incomplete proposals (no rationale)
```
Call _extract_and_post_proposal with "[PROPOSAL]\nTitle: stuff\n[/PROPOSAL]"
Assert _handle_propose_improvement was NOT called (rationale missing).
```

### Test 8: _extract_and_post_proposal handles multiline rationale
```
Call with "[PROPOSAL]\nTitle: Better routing\nRationale: Line one\nLine two\nLine three\nAffected Systems: Router\nPriority: medium\n[/PROPOSAL]"
Assert rationale captured as "Line one\nLine two\nLine three".
```

**File:** `tests/test_runtime_intents.py` or whichever file tests `handle_intent()` — add to existing.

### Test 9: _handle_propose_improvement creates thread in proposals channel
```
Set up runtime with ward_room running.
Call _handle_propose_improvement with intent params {title, rationale, affected_systems, priority_suggestion}.
Assert thread created in "Improvement Proposals" channel.
Assert thread title starts with "[Proposal]".
Assert body contains all structured fields.
```

### Test 10: _handle_propose_improvement returns error if rationale missing
```
Call with params {title: "something", rationale: ""}.
Assert response has success=False and error about rationale.
```

### Test 11: _handle_propose_improvement returns error if ward room unavailable
```
Set runtime.ward_room = None.
Call _handle_propose_improvement.
Assert response has success=False.
```

### Test 12: proposals API returns threads from proposals channel
```
Start runtime with ward_room.
Post 2 threads to Improvement Proposals channel: one with net_score=1, one with net_score=-1.
GET /api/wardroom/proposals.
Assert 2 proposals returned with correct status (approved/shelved).
```

### Test 13: proposals API filters by status
```
Same setup as Test 12.
GET /api/wardroom/proposals?status=approved.
Assert only the approved proposal returned.
```

## Constraints

- **Channel type is `"ship"`** — ship-wide visibility, all crew subscribed. Not a department channel.
- **Thread mode is `"discuss"`** — other agents can comment on proposals, Captain can endorse/downvote.
- **Endorsement reuse** — No new endorsement mechanics. Existing `endorse()` on threads handles approve (upvote) and shelve (downvote). The `net_score` field naturally produces approved (>0) / pending (0) / shelved (<0) status.
- **[PROPOSAL] block extraction** is regex-based, no LLM call. Fast and deterministic.
- **Conservative proposal gating** — agents must include both title AND rationale. Incomplete proposals are silently skipped (no error, no noise).
- **No new config** needed — the channel is always seeded when Ward Room is enabled. Proposals are an organic capability, not a toggleable feature.
- **Attribution** — Proposals are tagged with the originating agent's callsign for credit/trust tracking via existing endorsement→credibility pipeline.
- **`_handle_propose_improvement` is called directly** from the proactive loop (not through `handle_intent` routing). This avoids HebbianRouter/consensus overhead for what is essentially an internal Ward Room post. The `handle_intent` branch exists for future external callers (HXI, scheduled tasks).

## Run

```bash
cd d:\ProbOS && uv run pytest tests/test_ward_room.py -x -v -k "improvement" 2>&1 | tail -30
```

```bash
cd d:\ProbOS && uv run pytest tests/test_proactive.py -x -v -k "proposal" 2>&1 | tail -30
```

Broader validation:
```bash
cd d:\ProbOS && uv run pytest tests/test_ward_room.py tests/test_proactive.py tests/test_ward_room_agents.py -x -v 2>&1 | tail -40
```
