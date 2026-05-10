# ProbOS Progress

**Status (2026-05-10).** Open OSS issues: 9 (3 from Wave 138 — AD-721b-1/-2/-3; 6 new from Wave 142 — AD-722b-1/-2/-3/-4/-5/-6 forward markers). Most recent shipped wave: 142 (AD-722b WebSocket push channel for avatar telemetry — WS /api/agent/{id}/avatar-telemetry-stream; popout flips sampling tier to HIGH; UI WS-first with 5 s open-timeout poll fallback; read-only snapshot contract preserved).
AD-697 + AD-698 establish the commercial-overlay seam
(`pip install -e ../<commercial-package>` → overlay active; uninstall →
back to OSS).

**Authoritative state.**
- `prompts/wave-plan.yaml` — wave roster (current wave: 142 done; next slot is 143).
- `DECISIONS.md` — append-only architectural decisions (current highest AD: AD-729).
- `tests/` — 13140 pytest at HEAD (4 pre-existing flakes in test_callsign_routing/test_ad719_chat_fanout outside this wave) + 561 vitest; gate runs `-n 8 --dist=loadfile`.

**Recent eras (archived):**
- [Era I — Genesis](progress-era-1-genesis.md)
- [Era II — Emergence](progress-era-2-emergence.md)
- [Era III — Product](progress-era-3-product.md)
- [Era IV — Evolution](progress-era-4-evolution.md)
- [Era V — Unification](progress-era-5-unification.md)

----

## Era VI — Commercial Bridge (Waves 105-128, May 2026)

### What landed (this era)

| Wave | AD/BF | Summary |
|------|-------|---------|
| 105 | AD-641g v1 | NATS cognitive chain pipeline foundation (publish-side, opt-in) |
| 106 | BF #423 | knowledge/store git-recovery test coverage (+6 tests) |
| 107 | AD-694a | extract `/api/ontology/graph` edge logic to `ontology/graph_snapshot.py` |
| 108 | BF #426 | `KnowledgeGraphView` TRUST mode O(n²) edge cap |
| 109 | BF #425 / AD-696 | wave-plan status drift reconciliation + convention docs |
| 110 | Nit #427 | `TrainingAgent` redundant `_runtime` override removed |
| 111 | AD-697 v1 | commercial overlay extension-point registry |
| 112 | AD-641g-1 | chain NATS consumer foundation (subscriber side, opt-in) |
| 113 | AD-697-1 + AD-698 | overlay seam validation: HXI badge + pre-intent authorization hook |
| 114 | BF #465 | roadmap reconciliation — flip 27 shipped `(planned, OSS)` tags |
| 115 | AD-443 (drift) | mobility protocol — already shipped |
| 116 | AD-482 (drift) | self-improvement pipeline — already shipped |
| 117 | AD-529 + AD-568 | comm contagion firewall + source governance |
| 118 | AD-660b | `/api/causal-templates` router |
| 119 | AD-572d-i + AD-573e-i | interruptible-wait + `recent_for_agent` infra |
| 120 | AD-539c-i + AD-539d-i | active gap remediation + federated aggregation |
| 121 | AD-509b/c/d + AD-507b | boot-camp continuations + curriculum progression |
| 122 | AD-511b + AD-511d | protective disengagement + boundary-probing detection |
| 123 | AD-522b + AD-522c | Cp/Cpk capability indices + graduated-response zone mapping |
| 124 | AD-583f/g (drift); AD-574c-i partial | observable state already shipped; DM convergence partial-deferred |
| 125 | AD-686c + AD-647d | `oracle.semantic_stats()` + chain CONSULT checkpoint store |
| 126 | AD-473 + AD-474 | PWA Web Push subscription registry + voice STT/TTS substrate |
| 127 | priority-4 cleanup combo | AD-509e/507c/507d/511c/511e/522d/522e/660c/660d |
| 128 | BF #466 | xdist stabilization: `-n 16 --dist=loadfile` |
| BF | BF #467 | distinguish leading @callsign (DM) from embedded mention (broadcast) |

**Net new tests this era:** ~145 pytest + ~5 vitest. Issue count: 37 closed.

### What's open (forcing-function deferrals)

| AD | Forcing function |
|----|------------------|
| AD-574c-ii | DM conversation convergence (full ProfileChatTab refactor — substrate now ready) |
| AD-641g-1-1 | flip executor to `await` ANALYZE results from NATS (depends on AD-641g-1 consumer in production use) |

----

## Era VI — Closing Notes

- **Commercial overlay seam is live.** `runtime.commercial_overlay_loaded` and `/api/system/extensions` expose registry state. `pre_intent_authorization` hook fires on every `IntentBus.broadcast`; default-empty registry means zero overhead.
- **No open OSS issues.** Pre-public-release tracker stays clean unless a regression or a new commercial-tagged AD lands.
- **Roadmap drift convention:** `(SHIPPED, OSS)` for landed entries; `(planned, OSS)` for pending. Reconciliation runs on demand (tracked in BF #465 / AD-696).


