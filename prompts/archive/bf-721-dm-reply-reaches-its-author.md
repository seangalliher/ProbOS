# BF-721: a DM reply can reach the wrong agent

**Issue:** #1165 · **Epic:** #1162 · **Repo:** OSS (`d:\ProbOS`), branch `main`

## The defect

`capability_request_notifier.py:108` keys the Captain DM channel as
`dm-captain-{agent_id[:8]}`. Agent IDs are `{agent_type}_{pool_name}_{index}_{hash8}`
(`identity.py:27`), so `[:8]` truncates **inside the type**: every Counselor instance keys to
`counselo`. `_resolve_dm_target_agent_id` (`wardroom.py:23`) then returns the **first live agent
whose id starts with that prefix**, so a thread filed by instance 1 resolves to instance 0 and
the Captain's reply invokes the wrong agent.

`default_pool_size: 3`, so instances 1 and 2 exist by default.

**Live calibration:** all 9 rows in `capability_requests.db` are from
`counselor_counselor_0_67c601cb`. Only instance 0 has ever filed, so no misroute has occurred.
Real and reachable, not yet fired.

## Do NOT rename the channels

The obvious fix — key channels on the full agent id — is wrong here. The 8-char scheme is a
**repo-wide Ward Room convention**: the live vessel has **123 DM channels** using it
(`dm-builder_-engineer`, `dm-architec-diagnost`, `dm-counselo-surgeon_`), plus 2,701 threads and
2,703 posts. Renaming means migrating all of it, and the resolver's
`parts = channel_name.split("-")` / `len(parts) != 3` parse breaks for every existing channel.

It is also unnecessary.

## The fix: resolve per THREAD, not per CHANNEL

The authoritative identity is **already persisted**. The notifier passes `created_by=agent_id`
and `author_id=agent_id`, both full ids, and `threads.author_id` holds the exact filer for all
2,701 rows.

Today `target_agent_id` is computed once per channel (`wardroom.py:90` and `:126`, both from
`ch.name`) and the UI uses that one value for whichever thread is open
(`WardRoomThreadDetail.tsx:71` → `:110`). That is the structural cause: **one channel, many
threads, possibly several authors, a single answer.**

Resolve it per thread instead:

1. Each thread in the `/captain-dms` and `/dms` payloads gains its own `target_agent_id`,
   derived from that thread's `author_id`.
2. The channel-level `target_agent_id` **stays** — other consumers may read it and it is the
   correct fallback for a channel with no thread context. It becomes a default, not the answer.
3. The UI prefers the active thread's target and falls back to the channel's.

Zero migration, no schema change, no rename. And it is strictly more correct: two agents may
share a channel and each thread still replies to its own author.

## Two things to get right

**A. Do not gate on `is_alive`.** The current resolver skips any agent where
`getattr(agent, "is_alive", False)` is false. A proactive crew member is idle most of the time,
and AD-1076 already established that resolving a *persistent* membership must not depend on
momentary liveness — that exact bug silently suppressed group chats for weeks. Validate that the
author is a **known, registered** agent (`registry.get(agent_id)`), not that it is currently
awake. Fixing this is in scope; it is the same class of defect in the same function.

**B. A Captain-authored thread must not resolve to the Captain.** `author_id` is `"captain"` for
threads the Captain started. The reply target there is the *other* party, so fall back to the
channel-level resolution. Any author that does not resolve to a registered agent falls back the
same way, and a failed fallback still yields `None` so the UI degrades to the async post-only
path exactly as today.

## Out of scope

- Do not rename channels or migrate any data.
- Do not change `capability_request_notifier.py`'s channel naming.
- Do not touch the approval path — #1164 and #1167 shipped there and are unrelated.

## Tests

Backend — `tests/test_bf721_dm_reply_reaches_its_author.py`:

1. **The headline:** two agents of the same type (indices 0 and 1) whose ids share the 8-char
   prefix, one thread each in the one shared channel. Each thread's `target_agent_id` is its own
   author. Fails before the fix — both return instance 0.
2. A resting (not `is_alive`) author still resolves. Guards against reintroducing the AD-1076
   liveness gate.
3. A Captain-authored thread falls back to the channel target, and does not return `"captain"`.
4. An author that is not a registered agent falls back to the channel target.
5. No registered agent at all ⇒ `None`, and the endpoint still returns its payload.
6. The channel-level `target_agent_id` is unchanged for existing single-agent channels — assert
   the current behaviour is preserved.

UI — extend the existing `WardRoomThreadDetail` tests:

7. With a thread-level target present, the reply POSTs to **that** agent, not the channel's.
8. With none present, it falls back to the channel's — the existing behaviour, preserved.

**Mutation-check every fix:** revert production, confirm the new test fails, restore.

## Gates

1. Focused: the new file plus `rg -l 'wardroom|ward_room' tests/`.
2. Full Python gate:
   ```
   $env:PROBOS_DATA_DIR="$env:TEMP\bf721_$(Get-Random)"; $env:PROBOS_EMBEDDINGS='local'
   & d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/ -q -n 16 --dist=loadfile --timeout=600 2>&1 | Tee-Object -FilePath d:\ProbOS\logs\bf721-gate.log
   ```
   Never place a filter after `Tee-Object`. Baseline **22,769 nodes** (passed + skipped +
   failed), post-AD-1211. Reconcile `baseline + new tests`, counting parametrised cases
   separately.
3. **UI changed ⇒ both UI gates required:** `cd ui && npx vitest run` then `npm run build`.
   Vitest does not type-check; `tsc -b` has caught real errors repeatedly. Baseline 2,304 tests
   across 316 files.

Known flakes, not regressions: #1143, #1144.

## Report back

- The per-thread resolution shape, and whether the channel-level field stayed compatible.
- Reconciled Python gate numbers against 22,769, plus the UI numbers.
- Any existing test that encoded the old first-match behaviour as the contract — the issue notes
  the resolver tests *"explicitly accept first-match behaviour"*, so expect at least one. Update
  and explain inline, never delete.
- **Anything in this prompt that turned out to be untrue.** Say so rather than implementing
  around it.

Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
