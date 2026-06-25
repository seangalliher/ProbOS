# AD-843c-2 — Consensus gate for sensitive device intents (completes #818)

**Makes `device.location` / `device.camera` / `device.screen` reachable AND consensus-gated** by mirroring the AD-1019c propose-only-pool + commit-on-APPROVED pattern: a `DeviceConsensusProposer` voter pool + a `submit_device_actuate_with_consensus` runtime method that commits `adapter.actuate` ONLY on `ConsensusOutcome.APPROVED` with no failed verifications.

- **Status:** Ready for Builder
- **Dependencies:** AD-843a (device_node), AD-843b (Ed25519 pairing + trust prior), AD-843c-1 (`device.notify` loop + runtime wire) — all shipped at HEAD `69865d6c`. Mirrors AD-1019c (`submit_mcp_invoke_with_consensus` + `McpConsensusProposer`).
- **Estimated tests:** ~12 (5 proposer-unit + 6 consensus-path + 1 honest-degrade)
- **AD numbering:** AD-843c-2 is a **PRE-RESERVED #818 sub-number**. Current highest landed top-level = **AD-1052**. **NO new top-level AD is minted.** This is the LAST #818 sub-piece; #818 completes when this lands (do NOT close #818 in tracker text — the architect closes it after merge; note only "completes #818").

---

## Decomposition note (architect judgement)

**Verdict: ONE AD.** Build the proposer + the runtime method + the dispatch + the wiring + tests as a single cohesive AD-843c-2. Yardstick: AD-1019c shipped the proposer (`mcp_consensus_proposer.py`, ~165 lines), the `submit_mcp_invoke_with_consensus` method (~95 lines), the episode helper (~60 lines), and the finalize pool wiring (~8 lines) **as one AD**. The device equivalent is the same footprint (~280 new lines + tests). The pieces are tightly coupled — the method needs the proposer pool for voters; the dispatch needs the method; the pool needs the proposer. Splitting (e.g. c-2 = pool+method, c-3 = wire intents) would leave a half-wired dead method with no callers. No split.

**Where the sensitive-intent dispatch lives: RUNTIME, not the service.** The dispatch path (the three sensitive intents → consensus) is a **runtime-owned handler** (`ProbOSRuntime._dispatch_device_consensus_intent`) subscribed alongside `device.notify`. It is NOT folded into `DeviceNodeService.handle_intent`. Justification against the layer rule: `device_service.py` is **substrate** and at HEAD imports ONLY `probos.substrate.device_node` + `probos.types` + stdlib (verified — see its module docstring). The commit-on-APPROVED mechanism is `submit_intent_with_consensus` → `quorum_engine.evaluate` → `adapter.actuate`, which lives in `runtime.py` (which legitimately imports `consensus`/`types`). Routing the sensitive path through the service would force either a `consensus` import into the layer-clean service (a layer violation) or a callback injection that splits the actuation logic across two layers. Keeping the entire sensitive path in `runtime.py` keeps `device_service.py` byte-identical and matches the MCP precedent (the MCP consensus method + its callers live in `runtime.py`/`finalize.py`, never in a substrate service). **`device_service.py` is UNTOUCHED by this AD.**

**The proposer mirrors `McpConsensusProposer`'s propose-only stance EXACTLY — no real voting logic.** Verified (`agents/mcp_consensus_proposer.py`): `McpConsensusProposer.handle_intent` runs `perceive → decide → act → report`; `decide` validates the request *shape* only (`server_url` + `tool` present); `act` returns `{"success": True, "data": {..., "requires_consensus": True}}` and **NEVER calls `MCPBridge.invoke`**. It is a *voter population* whose only job is to make quorum reachable (a bare `mcp_invoke` broadcast with no subscribers → zero voters → `INSUFFICIENT` → always blocked). `DeviceConsensusProposer` is a faithful mirror: validate `device_id` + `intent_name` present, return `success=True` with `requires_consensus=True`, **NEVER call `adapter.actuate`** (the proposer holds no adapter). No per-device trust check, no policy logic — the runtime method owns the commit gate.

**Key design driver — the proposal intent MUST be a NEW internal name (`device_actuate`), distinct from the three external intents.** The device delivers sensitive intents on the bus (mirror c-1, where `device.notify` arrives via `intent_bus.broadcast`). `IntentBus.subscribe(agent_id, handler, intent_names=[...])` indexes the handler under each name; `broadcast(msg)` routes to handlers indexed under `msg.intent`. If `submit_device_actuate_with_consensus` re-broadcast the SAME external name (e.g. `device.location`), the dispatch handler — itself subscribed to `device.location` — would receive the re-broadcast and call the method again → **infinite loop**. Therefore the method broadcasts a generic internal `device_actuate` (params carry `device_id` + `intent_name` + the original `params`), the `DeviceConsensusProposer` subscribes to `device_actuate`, and the dispatch handler subscribes to the three external sensitive intents. This is the faithful analogue of MCP's generic `mcp_invoke` (the tool/server live in params). `device_actuate` is declared ONLY on the proposer — it does NOT go in `DEVICE_INTENT_DESCRIPTORS` (`device_node.py` stays UNTOUCHED).

**Deliberate divergence from MCP (toward the c-1 device learning loop):** the MCP tier is *recorded-not-scored* (episode on commit only, no trust write for the tool). The device tier records **episode + trust on BOTH the approved-and-actuated AND the rejected paths** (the device IS a trust-bearing peer — `device.trust_record_id`, AD-843b). An unpaired/ungranted device is refused BEFORE consensus (episode `authorized=False`, **no** trust write, zero votes) — this mirrors c-1's `handle_intent`, where the unauthorized branch stores an episode but does NOT call `record_outcome`.

---

## Problem

AD-843c-1 shipped the NON-consensus `device.notify` loop and **deliberately left the three sensitive intents unreachable** (`DeviceNodeService.handle_intent` returns `None` for everything except `device.notify`; nothing is subscribed to `device.location`/`device.camera`/`device.screen`) so there would be no governance bypass. `DEVICE_INTENT_DESCRIPTORS` already marks all three `requires_consensus=True` (verified, `device_node.py` L60-78), but no consensus path exists to honour that flag. #818 is incomplete until the sensitive intents are reachable through a real consensus gate.

The REAL consensus mechanism (verified) is **propose-only pool + commit-on-APPROVED runtime method** (`submit_mcp_invoke_with_consensus`), **not** a direct `QuorumEngine.evaluate(...)` call. Hand-rolling votes into `evaluate` (which only scores already-collected votes) is the governance bypass this AD must NOT reintroduce.

---

## Solution overview

```
device sends device.location  ──bus──►  runtime._dispatch_device_consensus_intent   (subscribed when config.device.enabled)
                                              │
                                              ▼
                          runtime.submit_device_actuate_with_consensus(device_id, "device.location", params)
                                              │
              authorize FIRST (c-1 parity) ───┤── unpaired/ungranted ─► episode(authorized=False), NO trust, NO vote, return
                                              │
                broadcast intent="device_actuate" ─► DeviceConsensusProposer pool (propose-only voters)
                                              │
                       quorum_engine.evaluate + red-team verification (via submit_intent_with_consensus)
                                              │
        APPROVED && no failed verifications ──┤── else (REJECTED / INSUFFICIENT / failed-verify) ─► committed=False
                                              ▼
              COMMIT: adapter.actuate(device, IntentMessage(intent_name, params))   ◄── ONLY place actuate fires
                                              │
                   episode(success=committed) + trust.record_outcome(device.trust_record_id, success=committed)  [BOTH paths]
```

Default-OFF (`config.device.enabled = False`, the existing c-1 gate): the proposer pool is not created and the sensitive-intent subscription is not added ⇒ the three intents stay unreachable ⇒ **byte-identical to AD-843c-1**. The `submit_device_actuate_with_consensus` / `_dispatch_device_consensus_intent` / `_store_device_consensus_episode` method defs are always present but inert (nothing calls them when off).

---

## Section 0 — The internal proposal intent (`device_actuate`)

No file edit here — this section names the contract the rest depends on:

- **`device_actuate`** is a NEW internal CONSENSUS proposal intent. It is declared ONLY on `DeviceConsensusProposer` (its `intent_descriptors` + `default_capabilities` + `_handled_intents`). It is the intent `submit_device_actuate_with_consensus` broadcasts. It is NOT added to `DEVICE_INTENT_DESCRIPTORS` and the device never sends it directly.
- The proposer's declared intent name **MUST** equal `"device_actuate"` (the string the runtime method broadcasts) — otherwise `create_pool` auto-subscribes the voters to a different name, the broadcast reaches zero voters, and every actuation is `INSUFFICIENT` (always blocked). See the STOP-flag list.

---

## Section 1 — `DeviceConsensusProposer` (NEW file)

**NEW** `src/probos/agents/device_consensus_proposer.py` — a faithful mirror of `agents/mcp_consensus_proposer.py` (propose-only; `tier="utility"`; never actuates). Full file:

```python
"""AD-843c-2: device consensus proposer — the voter population for ``device_actuate``.

A ``CONSENSUS``-tier sensitive device actuation (``device.location`` /
``device.camera`` / ``device.screen``) is routed through the existing quorum via
``runtime.submit_device_actuate_with_consensus`` (which mirrors
``submit_mcp_invoke_with_consensus``). That broadcasts the internal
``device_actuate`` proposal intent and collects votes — but no existing pool
answers ``device_actuate`` (it is a new intent), so a bare broadcast would yield
**zero voters → INSUFFICIENT → always blocked**. This minimal utility agent is
the voting population: it responds to ``device_actuate`` with a **proposal only**
— it validates the request shape and sets ``requires_consensus=True`` on its
result, and it **NEVER actuates the device**. The runtime performs the
``DeviceNodeAdapter.actuate`` *commit* only on ``APPROVED`` (the era-4 / AD-362
guard).

Exact ``McpConsensusProposer`` parity (propose-only + a runtime-side commit),
one pool, ``tier="utility"`` (it operates on the governance system, not for the
user).

Layer discipline: imports ONLY ``probos.substrate.agent`` + ``probos.types``.
NO consensus/mesh/cognitive/runtime imports — the commit gate is the runtime's.
"""

from __future__ import annotations

import logging
from typing import Any

from probos.substrate.agent import BaseAgent
from probos.types import (
    CapabilityDescriptor,
    IntentDescriptor,
    IntentMessage,
    IntentResult,
)

logger = logging.getLogger(__name__)


class DeviceConsensusProposer(BaseAgent):
    """Propose-only voter for ``device_actuate`` consensus (AD-843c-2).

    The actuation is NOT executed here. The agent proposes the actuation and sets
    ``requires_consensus=True`` on its result; the runtime's consensus layer must
    approve before ``DeviceNodeAdapter.actuate`` commits. Mirrors
    :class:`~probos.agents.mcp_consensus_proposer.McpConsensusProposer`.

    Capabilities: ``device_actuate``.
    """

    agent_type: str = "device_consensus_proposer"
    tier = "utility"
    default_capabilities = [
        CapabilityDescriptor(
            can="device_actuate",
            detail="Propose a consensus-gated sensitive device actuation (does not execute)",
            formats=["json"],
        ),
    ]
    initial_confidence: float = 0.8
    intent_descriptors = [
        IntentDescriptor(
            name="device_actuate",
            params={
                "device_id": "<paired device id>",
                "intent_name": "device.location|device.camera|device.screen",
                "params": "{...}",
            },
            description="Actuate a sensitive intent on a paired device (consensus-gated)",
            requires_consensus=True,
        ),
    ]

    _handled_intents = {"device_actuate"}

    async def handle_intent(self, intent: IntentMessage) -> IntentResult | None:
        """Full lifecycle: perceive -> decide -> act -> report.

        The act phase proposes the actuation but does NOT commit it. The runtime
        consensus layer calls ``DeviceNodeAdapter.actuate`` only if approved.
        """
        observation = await self.perceive(intent.__dict__)
        if observation is None:
            return None

        plan = await self.decide(observation)
        if plan is None:
            return None

        result = await self.act(plan)
        report = await self.report(result)

        success = report.get("success", False)
        self.update_confidence(success)

        return IntentResult(
            intent_id=intent.id,
            agent_id=self.id,
            success=success,
            result=report.get("data"),
            error=report.get("error"),
            confidence=self.confidence,
        )

    async def perceive(self, intent: dict[str, Any]) -> Any:
        """Check if this intent is something we handle."""
        intent_name = intent.get("intent", "")
        if intent_name not in self._handled_intents:
            return None
        return {
            "intent": intent_name,
            "params": intent.get("params", {}),
        }

    async def decide(self, observation: Any) -> Any:
        """Validate the proposed actuation shape (no side effects)."""
        params = observation["params"]
        device_id = params.get("device_id")
        target_intent = params.get("intent_name")

        if not device_id:
            return {"action": "error", "error": "No device_id specified"}
        if not target_intent:
            return {"action": "error", "error": "No intent_name specified"}

        return {
            "action": "propose",
            "device_id": device_id,
            "intent_name": target_intent,
            "params": params.get("params") or {},
        }

    async def act(self, plan: Any) -> Any:
        """Return a proposal — the actuation is NEVER executed here.

        The actual ``DeviceNodeAdapter.actuate`` happens in the runtime after
        consensus approval (``submit_device_actuate_with_consensus``).
        """
        action = plan.get("action")

        if action == "error":
            return {"success": False, "error": plan["error"]}

        if action == "propose":
            return {
                "success": True,
                "data": {
                    "device_id": plan["device_id"],
                    "intent_name": plan["intent_name"],
                    "params": plan["params"],
                    "requires_consensus": True,
                },
            }

        return {"success": False, "error": f"Unknown action: {action}"}

    async def report(self, result: Any) -> dict[str, Any]:
        """Package the result for the mesh."""
        return result
```

---

## Section 2 — Runtime: the consensus method, the episode helper, and the dispatch handler (3 new methods)

**EDIT** `src/probos/runtime.py`. Insert the three new methods immediately AFTER `_store_mcp_invoke_episode` ends and BEFORE `_build_system_self_model`. SEARCH anchor (the tail of `_store_mcp_invoke_episode` verified at L3398-3409):

```python
        except Exception:
            logger.debug(
                "AD-1019c: failed to store MCP invoke episode (server=%s tool=%s)",
                server_url,
                tool,
                exc_info=True,
            )

    def _build_system_self_model(self) -> SystemSelfModel:
        """Build structured self-knowledge snapshot (AD-318)."""
```

REPLACE with (the same two lines, with the three new methods inserted between):

```python
        except Exception:
            logger.debug(
                "AD-1019c: failed to store MCP invoke episode (server=%s tool=%s)",
                server_url,
                tool,
                exc_info=True,
            )

    async def submit_device_actuate_with_consensus(
        self,
        device_id: str,
        intent_name: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
        policy: QuorumPolicy | None = None,
    ) -> dict[str, Any]:
        """Actuate a sensitive device intent through the consensus pipeline (AD-843c-2).

        The CONSENSUS-tier "two keys" gate for ``device.location`` /
        ``device.camera`` / ``device.screen``. Mirrors
        :meth:`submit_mcp_invoke_with_consensus`: authorize the per-device grant
        FIRST (c-1 parity), then broadcast a ``device_actuate`` proposal (the
        :class:`~probos.agents.device_consensus_proposer.DeviceConsensusProposer`
        pool answers with a proposal only), evaluate quorum + red-team
        verification, and perform ``DeviceNodeAdapter.actuate`` **commit only on
        APPROVED with no failed verifications**.

        Unlike the recorded-not-scored MCP tier, the device tier records an
        **episode + trust outcome on BOTH** the approved-and-actuated AND the
        rejected paths (the device is a trust-bearing peer, AD-843b). An
        unpaired/ungranted device is refused BEFORE consensus (episode
        ``authorized=False``, NO trust, zero votes) — mirroring c-1.

        ⚠️ era-4 / AD-362 guard: an ``IntentResult(success=True)`` from the
        broadcast is only a *proposal* — ``actuate`` is NEVER performed on the
        vote. A rejected / insufficient vote performs **zero** ``actuate`` calls.
        """
        request_params = dict(params or {})

        # Gate 0: per-device capability grant (c-1 parity — authorize FIRST).
        authorized, reason = self.device_node_registry.authorize(device_id, intent_name)
        if not authorized:
            await self._store_device_consensus_episode(
                device_id=device_id,
                intent_name=intent_name,
                authorized=False,
                committed=False,
                reason=reason,
            )
            return {
                "authorized": False,
                "committed": False,
                "consensus": None,
                "actuate_result": None,
                "reason": reason,
            }

        device = self.device_node_registry.get_device(device_id)
        # authorize() returning True guarantees the device is paired/present.
        assert device is not None

        result = await self.submit_intent_with_consensus(
            intent="device_actuate",
            params={
                "device_id": device_id,
                "intent_name": intent_name,
                "params": request_params,
            },
            timeout=timeout,
            policy=policy,
        )

        consensus = result["consensus"]
        committed = False
        actuate_result: Any = None

        if consensus.outcome == ConsensusOutcome.APPROVED:
            # Check if any verification flagged issues.
            failed_verifications = [
                v for v in result["verifications"] if not v.verified
            ]
            if not failed_verifications:
                # Commit the actuation — the ONLY place adapter.actuate is called
                # for the sensitive tier, gated on APPROVED (the era-4 guard).
                actuate_msg = IntentMessage(intent=intent_name, params=request_params)
                try:
                    actuate_result = await self.device_node_adapter.actuate(
                        device, actuate_msg
                    )
                    committed = bool(getattr(actuate_result, "success", False))
                except Exception:
                    logger.warning(
                        "AD-843c-2: device actuate commit failed after approval "
                        "(device=%s intent=%s); reporting not-committed",
                        device_id,
                        intent_name,
                        exc_info=True,
                    )
                    committed = False

                await self.event_log.log(
                    category="consensus",
                    event="device_actuate_committed" if committed else "device_actuate_failed",
                    detail=f"device={device_id} intent={intent_name}",
                )
            else:
                await self.event_log.log(
                    category="consensus",
                    event="device_actuate_blocked",
                    detail=(
                        f"device={device_id} intent={intent_name} "
                        f"failed_verifications={len(failed_verifications)}"
                    ),
                )

        # Trust + episode on BOTH paths (the device learning loop, AD-843c-1 parity).
        if self.trust_network is not None and device.trust_record_id:
            try:
                self.trust_network.record_outcome(
                    device.trust_record_id,
                    success=committed,
                    intent_type=intent_name,
                    source="device",
                )
            except Exception:
                logger.warning(
                    "AD-843c-2: trust record_outcome failed for %s",
                    device.trust_record_id,
                    exc_info=True,
                )

        await self._store_device_consensus_episode(
            device_id=device_id,
            intent_name=intent_name,
            authorized=True,
            committed=committed,
            reason="" if committed else "consensus_rejected",
        )

        result["authorized"] = True
        result["committed"] = committed
        result["actuate_result"] = actuate_result
        return result

    async def _store_device_consensus_episode(
        self,
        *,
        device_id: str,
        intent_name: str,
        authorized: bool,
        committed: bool,
        reason: str,
    ) -> None:
        """Persist an episode for one consensus-gated device actuation (AD-843c-2).

        Episodic completeness: every sensitive actuation attempt
        (approved-and-actuated, rejected, or refused-at-grant) is recorded.
        Mirrors the AD-843c-1 device episode shape (channel="device") and the
        ``_store_mcp_invoke_episode`` honest-degrade: no episodic memory → no-op;
        a store failure is logged at debug and swallowed.
        """
        if self.episodic_memory is None:
            return
        try:
            import time as _time

            episode = Episode(
                user_input=f"[device] {intent_name} -> {device_id}",
                timestamp=_time.time(),
                agent_ids=[f"device:{device_id}"] if device_id else [],
                outcomes=[
                    {
                        "kind": "device_actuate",
                        "intent": intent_name,
                        "device_id": device_id,
                        "authorized": authorized,
                        "success": committed,
                        "reason": reason,
                    }
                ],
                dag_summary={},
                anchors=AnchorFrame(channel="device", trigger_type=intent_name),
            )
            await self.episodic_memory.store(episode)
        except Exception:
            logger.debug(
                "AD-843c-2: failed to store device consensus episode (%s)",
                device_id,
                exc_info=True,
            )

    async def _dispatch_device_consensus_intent(
        self, intent: IntentMessage
    ) -> IntentResult | None:
        """AD-843c-2: route a sensitive device intent through the consensus gate.

        Subscribed (only when ``config.device.enabled``) to ``device.location`` /
        ``device.camera`` / ``device.screen``. Extracts the ``device_id`` and
        routes to :meth:`submit_device_actuate_with_consensus`, which performs the
        authorize → quorum → ``actuate`` commit. Returns an ``IntentResult``
        reflecting whether the actuation committed.
        """
        device_id = str(intent.params.get("device_id", ""))
        outcome = await self.submit_device_actuate_with_consensus(
            device_id, intent.intent, dict(intent.params)
        )
        committed = bool(outcome.get("committed", False))
        actuate = outcome.get("actuate_result")
        return IntentResult(
            intent_id=intent.id,
            agent_id=f"device:{device_id}",
            success=committed,
            result=actuate.result if (committed and actuate is not None) else None,
            error=None if committed else str(outcome.get("reason") or "consensus_rejected"),
            confidence=1.0 if committed else 0.0,
        )

    def _build_system_self_model(self) -> SystemSelfModel:
        """Build structured self-knowledge snapshot (AD-318)."""
```

**Import note:** `ConsensusOutcome` (runtime.py L126), `QuorumPolicy` (L133), `Episode`/`AnchorFrame`/`IntentMessage`/`IntentResult` are ALL already imported in `runtime.py` — verified. No new imports needed for these methods.

---

## Section 3 — Runtime `__init__`: name the shared adapter (1-line extraction)

The consensus commit calls `self.device_node_adapter.actuate(...)`. At HEAD the NoOp adapter is constructed inline inside the `DeviceNodeService(...)` call (verified, `__init__` L905-911) and is not reachable as a runtime attr. Extract it to a named attr so the same instance backs BOTH the c-1 `device.notify` service path AND the c-2 consensus path (when a real OS-backed adapter replaces NoOp later, both paths share it).

SEARCH (verified `__init__` L897-911):

```python
        from probos.substrate.device_node import DeviceNodeRegistry, NoOpDeviceNodeAdapter
        from probos.substrate.device_service import DeviceNodeService, DEVICE_NODE_SERVICE_ID
        self.device_node_registry: DeviceNodeRegistry = DeviceNodeRegistry(
            trust_network=self.trust_network,
            probationary_alpha=self.config.device.probationary_alpha,
            probationary_beta=self.config.device.probationary_beta,
        )
        self.device_node_service: DeviceNodeService = DeviceNodeService(
            registry=self.device_node_registry,
            adapter=NoOpDeviceNodeAdapter(),
            trust_network=self.trust_network,
            episodic_provider=lambda: self.episodic_memory,
        )
```

REPLACE:

```python
        from probos.substrate.device_node import (
            DeviceNodeAdapter,
            DeviceNodeRegistry,
            NoOpDeviceNodeAdapter,
        )
        from probos.substrate.device_service import DeviceNodeService, DEVICE_NODE_SERVICE_ID
        self.device_node_registry: DeviceNodeRegistry = DeviceNodeRegistry(
            trust_network=self.trust_network,
            probationary_alpha=self.config.device.probationary_alpha,
            probationary_beta=self.config.device.probationary_beta,
        )
        # AD-843c-2: the actuation adapter is shared by the c-1 device.notify
        # service AND the c-2 consensus commit (submit_device_actuate_with_consensus).
        self.device_node_adapter: DeviceNodeAdapter = NoOpDeviceNodeAdapter()
        self.device_node_service: DeviceNodeService = DeviceNodeService(
            registry=self.device_node_registry,
            adapter=self.device_node_adapter,
            trust_network=self.trust_network,
            episodic_provider=lambda: self.episodic_memory,
        )
```

> This is behaviourally byte-identical (same `NoOpDeviceNodeAdapter` instance, just named). The c-1 `if self.config.device.enabled:` `device.notify` subscription block immediately below is **UNCHANGED**.

---

## Section 4 — Finalize wiring: the proposer pool + the sensitive-intent subscription (gated)

**EDIT** `src/probos/startup/finalize.py`. Two changes.

**4a — NEW helper** (mirror the `async def _wire_desktop_ux` pattern, L80). Insert near the other `_wire_*` helpers (e.g. directly after `_wire_desktop_ux` ends, ~L128):

```python
async def _wire_device_consensus(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-843c-2: wire the consensus gate for sensitive device intents (#818).

    Default-OFF (``config.device.enabled``): no proposer pool, no sensitive-intent
    subscription ⇒ ``device.location`` / ``device.camera`` / ``device.screen`` stay
    UNREACHABLE — byte-identical to AD-843c-1, no governance bypass. When enabled:
    create the ``DeviceConsensusProposer`` voter pool (so ``device_actuate`` can
    reach quorum) and subscribe the three ``requires_consensus`` device intents to
    the runtime's consensus dispatch handler.
    """
    if not config.device.enabled:
        return False

    from probos.agents.device_consensus_proposer import DeviceConsensusProposer
    from probos.substrate.device_node import DEVICE_INTENT_DESCRIPTORS

    # The device_actuate voter population (propose-only; never actuates). Sized to
    # the default QuorumPolicy.min_votes so a CONSENSUS-tier actuation reaches quorum.
    runtime.spawner.register_template(
        "device_consensus_proposer", DeviceConsensusProposer
    )
    await runtime.create_pool(
        "device_consensus", "device_consensus_proposer", target_size=3
    )

    # Subscribe the runtime consensus dispatch to the requires_consensus device
    # intents (single source of truth — the names come from the descriptor list).
    sensitive_intents = [
        d.name for d in DEVICE_INTENT_DESCRIPTORS if d.requires_consensus
    ]
    runtime.intent_bus.subscribe(
        "device_consensus_dispatch",
        runtime._dispatch_device_consensus_intent,
        intent_names=sensitive_intents,
    )
    return True
```

**4b — CALL the helper** from `finalize_startup`. SEARCH anchor (verified L2602-2606):

```python
    if await _wire_desktop_ux(runtime=runtime, config=config):
        logger.info("AD-751: Desktop UX Surface wired during finalization")

    if await _wire_self_distillation(runtime=runtime, config=config):
```

REPLACE:

```python
    if await _wire_desktop_ux(runtime=runtime, config=config):
        logger.info("AD-751: Desktop UX Surface wired during finalization")

    if await _wire_device_consensus(runtime=runtime, config=config):
        logger.info("AD-843c-2: device consensus gate wired during finalization")

    if await _wire_self_distillation(runtime=runtime, config=config):
```

> The subscriber id `"device_consensus_dispatch"` MUST differ from `DEVICE_NODE_SERVICE_ID` (`"device_node_service"`, the c-1 `device.notify` subscriber) — `IntentBus.subscribe` stores ONE handler per `agent_id`; reusing the id would overwrite the c-1 handler. Verified distinct.

---

## Section 5 — Config

**NO config change.** `DeviceConfig.enabled: bool = False` already exists (verified, `config.py` L5880, added by c-1). The whole c-2 surface reuses that single gate. **Do NOT touch `config/system.yaml`.**

---

## Tests

**NEW** `tests/test_ad843c2_device_consensus.py`. BF-287 discipline — real fixtures only. Mirror `tests/test_ad1019c_consensus.py` (real `ProbOSRuntime` + `start()` + `create_pool` + a real proposer pool) and `tests/test_ad1019c_proposer.py` (propose-only unit), plus the c-1 `_pair` / `_CountingAdapter` / `_CapturingEpisodic` helpers from `tests/test_ad843c1_device_actuation.py`.

**Shared fixtures (mirror the verified templates):**
- `runtime` fixture: `ProbOSRuntime(data_dir=tmp_path / "data", config=SystemConfig())`, then `rt.spawner.register_template("device_consensus_proposer", DeviceConsensusProposer)`, then `await rt.start()`, `yield rt`, `await rt.stop()`. (Default `SystemConfig()` keeps `device.enabled=False`, but the consensus-path tests call `submit_device_actuate_with_consensus` DIRECTLY and create the pool explicitly — the gate only governs the bus dispatch wiring, not the method. The `device_node_registry` is constructed eagerly in `__init__` regardless of the flag — verified — so devices can be paired without enabling.)
- `_pair(registry, device_id, caps)` — Ed25519 `generate_keypair` + `sign_challenge` + `registry.pair_device(...)` (copy from the c-1 test).
- `_CountingAdapter` — real wrapper delegating to `NoOpDeviceNodeAdapter`, counting `actuate` calls (copy from the c-1 test). Swap onto the runtime: `runtime.device_node_adapter = _CountingAdapter()`.

**Proposer-unit tests (no runtime — mirror `test_ad1019c_proposer.py`):**
1. `test_proposer_proposes_valid_actuate_with_consensus_flag` — `IntentMessage("device_actuate", {"device_id":"phone-1","intent_name":"device.location","params":{}})` → `success=True`, `result["requires_consensus"] is True`, `result["device_id"]=="phone-1"`, `result["intent_name"]=="device.location"`.
2. `test_proposer_rejects_missing_device_id` → `success=False`, `"device_id" in error`.
3. `test_proposer_rejects_missing_intent_name` → `success=False`, `"intent_name" in error`.
4. `test_proposer_ignores_unhandled_intent` — `IntentMessage("device.notify", ...)` (or `write_file`) → `None`.
5. `test_proposer_descriptor_consensus_and_utility_tier` — `device_actuate` descriptor `requires_consensus is True` AND `DeviceConsensusProposer.tier == "utility"`.

**Consensus-path tests (real runtime — mirror `test_ad1019c_consensus.py`):**
6. `test_approved_commits_single_actuate` — `await runtime.create_pool("device_consensus","device_consensus_proposer",target_size=3)`; swap `_CountingAdapter`; `_pair(runtime.device_node_registry,"phone-1",frozenset({"device.location"}))`; `result = await runtime.submit_device_actuate_with_consensus("phone-1","device.location",{},timeout=5.0)` → `result["consensus"].outcome == ConsensusOutcome.APPROVED`, `result["committed"] is True`, `len(adapter.calls)==1`; assert an episode stored with `outcomes[0]["success"] is True` and `anchors.channel=="device"`; assert `runtime.trust_network` recorded an outcome on `"device:phone-1"`.
7. `test_rejected_vote_performs_zero_actuate` — pool of 3 + `policy=QuorumPolicy(min_votes=3, approval_threshold=1.1)` → `outcome == ConsensusOutcome.REJECTED`, `committed is False`, `len(adapter.calls)==0`; episode stored with `success is False`, `reason=="consensus_rejected"`; trust recorded with `success=False` (score moved down / event present). **The era-4 regression guard: zero actuate on a non-APPROVED vote.**
8. `test_insufficient_votes_performs_zero_actuate` — do NOT create the pool → `outcome == ConsensusOutcome.INSUFFICIENT`, `committed is False`, `len(adapter.calls)==0`, episode+trust still recorded (`success=False`).
9. `test_unauthorized_device_refused_before_consensus` — call `submit_device_actuate_with_consensus("ghost-1","device.location",{})` with `ghost-1` UNPAIRED → returns `{"authorized": False, "committed": False, "consensus": None, ...}`; `len(adapter.calls)==0`; episode stored with `authorized is False`; assert NO trust outcome recorded for `"device:ghost-1"` (c-1 parity — grant-gate refusal is not a scored outcome).
10. `test_store_device_consensus_episode_honest_degrade_when_no_memory` — `runtime.episodic_memory = None`; `await runtime._store_device_consensus_episode(device_id="phone-1", intent_name="device.location", authorized=True, committed=True, reason="")` must not raise.

**Wiring + c-1 regression tests:**
11. `test_wire_device_consensus_off_is_noop` — real runtime + `SystemConfig()` (device OFF); `assert await _wire_device_consensus(runtime=rt, config=cfg) is False`; `"device_consensus" not in rt.pools`; the three sensitive intents have NO bus subscriber (the helper is the sole subscription site — assert via the bus's index for `device.location` being absent/empty, OR assert no `device_consensus_dispatch` subscriber). Proves default-OFF byte-identical.
12. `test_device_notify_path_unchanged` (c-1 regression) — construct a runtime with `config.device.enabled=True`, pair a device granting `device.notify`, drive `device.notify` (via `device_node_service.handle_intent` directly OR `intent_bus.broadcast` like c-1 test 8) → still actuates through `device_node_service` (NON-consensus), `device_node_service` UNCHANGED, NOT routed through `device_actuate`.

**Gate command:**
```
$env:PROBOS_DATA_DIR="$env:TEMP\probos_ad843c2_$(Get-Random)"; New-Item -ItemType Directory -Force -Path $env:PROBOS_DATA_DIR | Out-Null
& 'd:\ProbOS\.venv\Scripts\pytest.exe' tests/test_ad843c2_device_consensus.py tests/test_ad843c1_device_actuation.py tests/test_ad1019c_consensus.py tests/test_ad1019c_proposer.py -q -n 0
Remove-Item $env:PROBOS_DATA_DIR -Recurse -Force; Remove-Item Env:\PROBOS_DATA_DIR
```
Expect: AD-843c-2 (~12) + AD-843c-1 (8) + AD-1019c consensus/proposer (unchanged) all green, **0 regressions**. Then a blast-radius run on `-k "device or consensus or quorum"` to confirm no collateral.

---

## What this does NOT change

- `src/probos/substrate/device_service.py` — UNTOUCHED (the sensitive path lives in runtime, layer discipline).
- `src/probos/substrate/device_node.py` — UNTOUCHED (`DEVICE_INTENT_DESCRIPTORS` already marks the three `requires_consensus=True`; `device_actuate` is declared only on the proposer).
- `src/probos/config.py` — UNTOUCHED (`DeviceConfig.enabled` already exists).
- `config/system.yaml` — UNTOUCHED.
- The c-1 `device.notify` loop, the `__init__` `device.notify` subscription block, `submit_mcp_invoke_with_consensus`, `McpConsensusProposer`, `submit_intent_with_consensus`, `QuorumEngine`.
- **Do NOT build:** the OS-native actuation backend (NoOp only), the AD-844 mobile client, fleet pairing (commercial), decomposer `device.*` teaching, HXI device events, any `QuorumEngine.evaluate(...)` direct-vote construction.

---

## Tracking

- `PROGRESS.md` — add an AD-843c-2 entry (mirror the c-1 entry's shape). Note "completes #818" — **do NOT mark #818 closed** (the architect closes it after merge).
- `DECISIONS.md` — append AD-843c-2 (the consensus gate; the `device_actuate` internal proposal intent; the trust+episode-on-both divergence from the recorded-not-scored MCP tier).
- `docs/development/roadmap.md` — update the #818 device-tier line to reflect the sensitive intents are now consensus-reachable (if a clean anchor exists; skip if none).

---

## Acceptance criteria

- [ ] `DeviceConsensusProposer` is a faithful propose-only mirror of `McpConsensusProposer` — validates shape, sets `requires_consensus=True`, NEVER calls `actuate`. `tier="utility"`. Declares `device_actuate` on `default_capabilities` + `intent_descriptors` + `_handled_intents`.
- [ ] `submit_device_actuate_with_consensus` commits `adapter.actuate` ONLY when `consensus.outcome == ConsensusOutcome.APPROVED` AND `not [v for v in result["verifications"] if not v.verified]` — the exact predicate from `submit_mcp_invoke_with_consensus`. NO `QuorumEngine.evaluate` direct-vote construction.
- [ ] Authorize-first: unpaired/ungranted device → episode `authorized=False`, NO trust write, zero votes, early return.
- [ ] Episode stored on approved-and-actuated, rejected, AND refused paths; trust `record_outcome(device.trust_record_id, success=committed, intent_type=intent_name, source="device")` on the approved+rejected (post-consensus) paths. Honest-degrade when `episodic_memory is None` and on any store/trust failure.
- [ ] Default-OFF (`config.device.enabled=False`): no `device_consensus` pool, no `device_consensus_dispatch` subscription, the three sensitive intents unreachable ⇒ byte-identical to AD-843c-1. The proposer class is imported only inside the gated helper.
- [ ] The proposal intent is the internal `device_actuate` (distinct from the three external intents) — no dispatch re-broadcast loop.
- [ ] `device_service.py`, `device_node.py`, `config.py`, `config/system.yaml` all UNTOUCHED. The c-1 `device.notify` path is regression-tested unchanged.
- [ ] Full type annotations on all new public methods/attrs; structured log messages; `create_task` not used (none needed); layer discipline (proposer imports only `substrate.agent` + `types`).
- [ ] Gate green: AD-843c-2 (~12) + AD-843c-1 (8) + AD-1019c (unchanged), 0 regressions; blast-radius clean; `get_errors` clean on all touched files; `ast.parse`/import smoke OK.
- [ ] **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## Verified Against Codebase (2026-06-24, HEAD 69865d6c)

```
git rev-parse --short HEAD
  69865d6c  (AD-843c-1: device actuation governance loop (device.notify) + runtime wire (#818))

# AD-1019c reference method — the commit-on-APPROVED template
runtime.py L3258  async def submit_mcp_invoke_with_consensus(self, server_url, tool, arguments=None, *, timeout=None, policy=None) -> dict
runtime.py L3293    result = await self.submit_intent_with_consensus(intent="mcp_invoke", params={...}, timeout=..., policy=...)
runtime.py L3297    if consensus.outcome == ConsensusOutcome.APPROVED:
runtime.py L3299      failed_verifications = [v for v in result["verifications"] if not v.verified]
runtime.py L3301      if not failed_verifications:               # commit predicate
runtime.py L3306        invoke_result = await self.mcp_bridge.invoke(...)   # the ONLY commit site (try/except log-degrade)
runtime.py L3358  async def _store_mcp_invoke_episode(self, *, server_url, tool, tier, success, agent_id="") -> None  (honest-degrade if episodic_memory is None; try/except debug)

# the underlying consensus primitive — returns dict{intent,results,consensus,verifications}
runtime.py L3018  async def submit_intent_with_consensus(self, intent, params=None, urgency=0.5, context="", timeout=None, policy=None) -> dict
runtime.py L3075    consensus = self.quorum_engine.evaluate(results, policy=policy)
runtime.py L3201    return {"intent": msg, "results": results, "consensus": consensus, "verifications": verification_results}

# enums / policy — already imported in runtime.py
types.py   L151  class ConsensusOutcome(Enum): APPROVED="approved"; REJECTED="rejected"; INSUFFICIENT="insufficient"
types.py   L168  class QuorumPolicy: min_votes:int=3; approval_threshold:float=0.6
runtime.py L126  ConsensusOutcome   (import)
runtime.py L133  QuorumPolicy       (import)

# proposer template
agents/mcp_consensus_proposer.py L35  class McpConsensusProposer(BaseAgent): tier="utility"; intent_descriptors=[IntentDescriptor(name="mcp_invoke", requires_consensus=True)]; _handled_intents={"mcp_invoke"}; act() returns proposal, NEVER invokes
tests/test_ad1019c_proposer.py L18   McpConsensusProposer(pool="mcp_consensus")   # ctor takes pool=
tests/test_ad1019c_consensus.py L73  rt.spawner.register_template("mcp_consensus_proposer", McpConsensusProposer); await rt.start()
tests/test_ad1019c_consensus.py L83  await runtime.create_pool("mcp_consensus","mcp_consensus_proposer",target_size=3)
tests/test_ad1019c_consensus.py L116 policy=QuorumPolicy(min_votes=3, approval_threshold=1.1)  # forces REJECTED

# pool wiring precedent
startup/finalize.py L2572  async def finalize_startup(*, runtime, config) -> FinalizationResult
startup/finalize.py L2602  if await _wire_desktop_ux(runtime=runtime, config=config):     # the helper-call anchor (4b)
startup/finalize.py L80    async def _wire_desktop_ux(*, runtime, config) -> bool          # the async-helper pattern (4a)
startup/finalize.py L3514  if config.mcp.agent_tools_enabled ...: register_template("mcp_consensus_proposer",...); await create_pool("mcp_consensus","mcp_consensus_proposer",target_size=3)
runtime.py L1710  async def create_pool(self, name, agent_type, target_size=None, ...) -> ResourcePool

# bus routing — subscribe indexes by intent_name; broadcast routes to that index
mesh/intent.py L145  def subscribe(self, agent_id, handler, intent_names=None): self._subscribers[agent_id]=handler; index per name  (one handler per agent_id)

# device tier as shipped (HEAD)
substrate/device_node.py L51  DEVICE_INTENT_DESCRIPTORS: device.notify(req_consensus=False), device.location/camera/screen(req_consensus=True), all tier="domain"
substrate/device_node.py L106 DeviceNodeAdapter Protocol: async def actuate(self, device: DeviceNode, intent: IntentMessage) -> IntentResult
substrate/device_node.py L116 NoOpDeviceNodeAdapter.actuate(device, intent) -> IntentResult
substrate/device_node.py L232 DeviceNodeRegistry.authorize(device_id, intent_name) -> tuple[bool,str]  ((True,"") on grant ok)
substrate/device_node.py      DeviceNode.trust_record_id = f"device:{device_id}"; get_device(device_id) -> DeviceNode|None
substrate/device_service.py L62  DeviceNodeService.handle_intent: returns None for non-"device.notify"; authorize→actuate→record_outcome(trust_record_id, success, intent_type, source="device")→_store_episode  (imports ONLY device_node + types + stdlib)
substrate/device_service.py L132 _store_episode(... authorized, success, reason): Episode(outcomes[kind="device_actuate",...], anchors=AnchorFrame(channel="device", trigger_type=intent.intent)); honest-degrade episodic None
runtime.py L897-916  __init__ device block: DeviceNodeRegistry(trust_network=self.trust_network, priors) eager; DeviceNodeService(adapter=NoOpDeviceNodeAdapter()) inline; if self.config.device.enabled: intent_bus.subscribe(DEVICE_NODE_SERVICE_ID, device_node_service.handle_intent, intent_names=["device.notify"])
config.py L5872  class DeviceConfig(BaseModel): enabled:bool=False (L5880); probationary_alpha=1.0; probationary_beta=3.0
config.py        SystemConfig.device: DeviceConfig

# AD numbering
PROGRESS.md  current highest landed top-level = AD-1052 (cited across recent entries); AD-843c-1/843b/843a all PRE-RESERVED #818 sub-numbers, NO new top-level
```

---

## STOP-flags (where HEAD differs from the framing, or where the Builder must not deviate)

1. **No HEAD/framing divergence found.** The framing matches the verified code: the real mechanism IS the propose-only-pool + commit-on-APPROVED runtime method (`submit_mcp_invoke_with_consensus`), NOT a direct `QuorumEngine.evaluate`. Proceed.
2. **Line-number drift:** the framing said `submit_mcp_invoke_with_consensus` ≈ L3232; it is actually **L3258** (and `submit_intent_with_consensus` is L3018). Anchor SEARCH blocks on the verified code text, not the numbers.
3. **The proposal intent MUST be the new internal `device_actuate`, NOT a re-broadcast of `device.location/camera/screen`.** Re-broadcasting an external name loops the dispatch handler. The proposer's declared intent name MUST be exactly `"device_actuate"` (== the method's broadcast intent) or quorum gets zero voters → always `INSUFFICIENT`.
4. **Subscriber id collision:** `"device_consensus_dispatch"` MUST differ from `DEVICE_NODE_SERVICE_ID` ("device_node_service") — `IntentBus.subscribe` keeps one handler per id; reuse would clobber the c-1 `device.notify` handler.
5. **Trust-on-both-paths is per the explicit instruction** (episode+trust on approved AND rejected). Note the nuance: a consensus REJECTION records `success=False` on the device handle (a device repeatedly requesting denied sensitive actions is down-weighted — defensible). The UNAUTHORIZED (grant-gate) path records NO trust (c-1 parity — a grant refusal is not a scored outcome). If the architect prefers trust ONLY on the actuated path, that is a one-line change (drop the trust block from the non-committed branch) — flag for confirmation, but the spec as written matches the stated "episode+trust on both".
6. **Do NOT close #818** in PROGRESS.md/roadmap text — note "completes #818"; the architect closes the issue after merge.
