# Promotion posts read the agent's own id and callsign: D5-R1 of #1754 and F-529 of #1523 (one slice; both parents stay open)

**Drafted by:** the Copilot Architect (fallback; the Claude Code bridge was logged out), 2026-11-13
**Revised by:** amendment A1 (section 15: the oracle's measurements, and mutation row 7's cell corrected), measured and applied by the orchestrator, 2026-11-13
**File in the repository:** `prompts/promotion-post-identity-reads.md` (the orchestrator may rename it; no AD or BF number is allocated, section "Numbers"). **Answer files:** in three parts, because the contract is too long for one `create` call: `answer-b-contract.part1.md` (this header, sections 1 to 6), `answer-b-contract.part2.md` (section 7: the slice), `answer-b-contract.part3.md` (sections 8 to 14, "Not in this issue: for the Captain"). Read them in that order; the labels of section 7 restart in the slice. The `create` tool writes CRLF; the apply tool reads the orchestrator's LF copy (the check in section 11 was run on the text with CRLF removed).
**Status:** ready to build on `origin/main` after BF-930/932 and #1769 have merged. At this consult `origin/main` is `4d8c51e4035d71660f0432b17083168050a1304e` (BF-933's merge). **Reading tree:** `D:\ProbOS-worktrees\bf930-932-build` at `b83ed1e347e1f5303b71cd21f4920a63065d59c0` (BF-930/932's batch; clean: `git status --short` printed nothing; read only). It differs from `origin/main` in `src/probos/cognitive/cognitive_agent.py` by 12 inserted lines at `:7608-7625` (`git diff --stat`: `12 insertions(+)`), after both promotion methods, so **the reads are on the same lines on both** (`:2859-2860`, `:2979-2980`), and in the trackers. **Oracle:** the Architect ran no pytest, no vitest, no build and no script that writes (a read-only consult). **What I ran instead** (section 11): every SEARCH of section 7 on the LF blobs of both refs (9 SEARCHes, 0 problems); an in-memory apply of all blocks (the patched `cognitive_agent.py`, the patched teaching test and the new test file compile; nothing was executed); an AST scan of every `.py` under `src/probos` for the two attribute names (with a positive control); enumerations of every caller and every test of the two methods; the existing Ward Room, channel and admission code read case by case. **What that leaves unchecked (all "expected" below):** every pytest result of the new file (12 cases), the mutation rows, the AD ledger regeneration, `scripts/check_architecture_principles.py --check`, the broad gate, and the live vessel (section "Not in this issue: for the Captain").
**Base blobs.** *Edited:* `src/probos/cognitive/cognitive_agent.py` `62c0f816bd5f1ce766a541abbfc0ccba6b743ae4` on `origin/main` (`2c2f3ee2b8dc51c972b5b280e955aaa70443c58f` on the reading tree: BF-930/932's lines); `tests/test_teaching_protocol.py` `432d3a232ef3f8004f13b3d8a46c58ab98f5f902`; `tests/fixtures/guard_name_allowlist.txt` `bdd194d01e6a14653cfdf98d96670039a2723752` (the last two equal on both refs). *Read, not edited (equal on both refs):* `tests/test_bf925_guard_names.py` `7610c2b21a334ed261e91b09e9f4c9c7ee94d702`, `tests/test_promotion_routing.py` `fb3d3b523a40df8b56923f3e61cb7e55ba12da05`, `src/probos/ward_room/channels.py` `cc9331d0f8ed43199cc8001b25258d8fd18bc318`, `src/probos/ward_room/service.py` `b871cc9bc6b45a89c2db5a034c039f204fee7747`, `src/probos/substrate/agent.py` `76d7ab13176405d52d975a77fe86be31966d1ede`, `src/probos/substrate/identity.py` `ebb299ab5cc6cd98caa4db0a9a2e20d2a7bd12bc`, `src/probos/agent_onboarding.py` `83c6065d0d2b546696b37bff6ca4de17938d7f5e`. *Trackers and the generated pair (they differ between the refs and move with the merges):* reading tree `PROGRESS.md` `bd1731caa443d0a81c1158377de58e92ad92f8ae`, `DECISIONS.md` `287e9da85cf7651c8183df832d1ea0da80a5adc2`, `docs/development/open-ads-report.md` `ca7c9ad63d19cdb2e68621bb4e31e14dc7331bd3`, `docs/development/ad-ledger-snapshot.json` `7ab3d8c84167afc2a62b3b2af3e7817c1998a8da`; `origin/main` `6977982df64e88416691c0f593f99eb1430a73b5`, `54d518a6fc38a2cd1d603fe1c85819c4d8f0458b`, `99a1a604a8197b5964ce0bda13015ec354e8a298`, `33363eb2bf06e1f45c8b4a278b83299920dd8b06`. **After BF-930/932 and #1769 have merged, every code blob above must still be equal (the first one changes only by BF-930/932's lines); the orchestrator re-runs the occurrence check of the nine SEARCHes of section 7 (each exactly once, at a line start, ASCII).** *Two paths do not exist* (`Test-Path` printed `False` for both): `prompts/promotion-post-identity-reads.md`, `tests/test_promotion_post_identity.py`.
**Dependencies:** BF-930/932 merges first (its lines in `cognitive_agent.py` are after ours); #1769 edits `builder.py`, `routers/build.py`, one layout test, the orchestrator profile and a new test file, none of ours. **Tier:** S1 M1 STANDARD, S1 M2 HIGH, S1 M3 STANDARD (D1). **Estimated tests (expected, not measured):** one new file, 12 cases (6 controls pass at M1, 6 xfail, section 6); one existing file loses two lines. No config key, no config model, no generated artifact but the AD ledger pair. **Numbers (hard rule):** **current highest AD: AD-1359** (`d:/ProbOS/.venv/Scripts/python.exe scripts/ad_ceiling.py`, exit 0: `git log --all` subjects AD-1359, GitHub issue titles in all states AD-1359 over 1,517 issues not truncated, `prompts/ad-*.md` AD-1350; next would be AD-1360); **current highest BF: BF-961** (my own enumeration, because `ad_ceiling.py` does not cover BF: `git log --all` subjects 961 over 1,356 refs, GitHub issue titles in all states 961, `prompts/bf-*.md` 941, the roadmap file 927). **Nothing is allocated:** both items are parent-backed, and no tracker head or commit subject of this slice is a number. Token the ledger would read and we do not want: **BF-954** (#1754's title reserves it for an open umbrella): it appears in no line of this slice.

**Tracker anchors (the orchestrator re-anchors after both merges).** `PROGRESS.md`: the title line `# ProbOS Progress` and the blank line after it (once, at the start of the file, on both refs: `git show <ref>:PROGRESS.md` starts `# ProbOS Progress`, an empty line, then the newest entry; no CR in the blob). `DECISIONS.md`: the heading `### AD-1346 M3e4d9 -- part (a) of the pending workforce scopes, classified (2026-11-05, #1604)` (once on both refs: line 1748 on `origin/main`, line 1764 on the reading tree; at a line start; ASCII; no CR in the blob; every entry of this period inserts before it, so this slice's entry lands after BF-930/932's and #1769's). Any other change to either file between these blobs and the build's base is a hard stop for the Architect. The AD ledger pair is regenerated at M3 by `scripts/gen_ad_ledger.py` (G3) and is not merged by hand. **No tracker line and no commit subject of this slice contains an `AD-` or `BF-` token.**

## 1. Problem

The two items are one defect in two methods of `CognitiveAgent`. Their anchors are old (`:2787`, `:2824`, `:2908`, `:2923`, `:2906-2907`, `:2708-2715`, `:2838-2841`); every one is re-derived on the reading tree. **The root cause is a name collision:** `_agent_id` and `_callsign` are the *observation keys* the same file builds (`cognitive_agent.py:6189`, `:6191`, `:6349`, `:6351`: `observation["_agent_id"] = self.id`, `observation["_callsign"] = getattr(self, 'callsign', self.agent_type)`), and the two methods read them as *attributes*, with the agent's type as the default.

| Claim (source) | Re-derived on `b83ed1e3` | Verdict |
|---|---|---|
| The reads are at `:2859-2860` and `:2979-2980` (my earlier answer) | `:2859` `agent_id = getattr(self, "_agent_id", agent_type)`, `:2860` `callsign = getattr(self, "_callsign", agent_type)` in `_announce_promotion_request` (def `:2830`); `:2979` `callsign = ...`, `:2980` `agent_id = ...` in `_teach_procedure` (def `:2917`) | **Holds, exactly** (D5-R1's `:2787`, `:2908` and F-529's `:2906-2907` are 72 to 73 lines early) |
| Nothing sets `_agent_id` or `_callsign` on a `CognitiveAgent` | AST scan of every `.py` under `src/probos` (section 11): `_callsign`: assigned nowhere, defined nowhere (no class attribute, `def`, property or `setattr` literal); `_agent_id`: 18 `self._agent_id = ...` in 18 helper classes (a queue, the dreaming engine, a browser session...), none descending from `BaseAgent` or `CognitiveAgent`; positive controls held | **Holds** |
| The values reach `create_thread`, `get_or_create_dm_channel` and the subscription | announce: thread author `:2881`, DM channel `:2896-2898` (first argument, creator, member), DM thread author `:2902`; teach: DM channel `:2995-2997`, thread author `:3001`; `ChannelManager.get_or_create_dm_channel` writes `created_by=agent_a_id` (`channels.py:271`), hands it to the shadow check (`:274`) and subscribes it (`:285`); `WardRoomService.create_thread` hands the author to the shadow check (`service.py:428`) | **Holds**, and the author id reaches more readers than the four named: the credibility row (`threads.py:492-497`), the restriction check (`:449-459`), the thread's episode (`:574-620`) |
| F-529: `_teach_procedure` has no production caller | enumeration over `src tests scripts docs config` (section 11): the def, a module function of the same name in the shell (`commands_procedure.py:62`, `:381`) and an API route named `teach_procedure` (`routers/procedures.py:150`) that teach **as the Captain** and do not call it; seven calls in `tests/test_teaching_protocol.py` | **Holds** |
| The tests mask it | `tests/test_teaching_protocol.py:80-81` set `id` and `callsign`; `:94-95` set `_callsign` and `_agent_id` on the double; no test names `_announce_promotion_request` or `_request_procedure_promotion` | **Holds** |
| Existing DM channels (the one behaviour change) | a name keeps the first 8 characters of each id (`channels.py:21-30`); a found channel is returned before anything is created or subscribed (`:252-263`) | **Holds, with a second effect and a limit** (D4, L1, L2, L8) |
| *New:* the router's DM recipients (a consumer the earlier consult did not read) | `WardRoomRouter` is built in production (`startup/finalize.py:5584`) and receives the Ward Room's events (`:5603-5630`: the fallback reference or the JetStream consumer, calling `route_event_coalesced`), so it routes every `ward_room_thread_created`; for an agent post it picks a DM's recipients as the first live crew agent with `agent.id != author_id` whose `id[:8]` is in the channel name (`ward_room_router.py:1022-1035`; `:986-995` for a Captain post), and `route_event` takes `author_id` from the event (`:425-427`, `:494-498`) | **The second effect:** a promotion DM authored by a type string excluded nobody, so an agent of the poster's type (the poster itself when alone) was told of its own post; with the id it no longer is (L8; case B3) |
| F-528 may join | both second arguments are names (`approver_id = approver` `:2888`; `target_callsign` `:2996`); the chief map (`:2781-2788`) is pinned by `tests/test_promotion_routing.py:34-46` and `:52-89`; F-528's own text calls the resolver design work | **No** |
| *New:* the earlier consult did not look for a test that pins the guard | `tests/fixtures/guard_name_allowlist.txt:13` lists an entry for `cognitive_agent.py`, name `_callsign`, kind `finding`; `tests/test_bf925_guard_names.py:196` fails on an allow-list entry "no longer guarded in that file" | **A required edit (P2-3)**: without it M2 turns a green test red |

## 2. Solution

One slice, three milestones. **M1** adds a test file that drives a real `CognitiveAgent` into a real `WardRoomService` on a temporary database through the two methods and reads back the stored rows (author ids, callsigns, the DM channel's creator and members, the ids the shadow check was handed), with the cases that fail on the base marked `built` (strict xfail at an `assert`), and removes the two attributes that masked the defect from the teaching test's double. **M2** changes the four reads (`self.id`; `self.callsign or agent_type`), deletes the allow-list entry the fix resolves, and turns the marker off. **M3** is the trackers. The second member of each DM stays a name (F-528), and a test pins that. The behaviour change for channels opened under the old reads, and for who the router tells, is recorded (D4, L1, L8).

## 3. Decisions

Each table ranks the options by correctness, safety, compatibility, fit, reversibility and validation cost; the first row is the decision. In-envelope means evidence, backward compatibility, no weakened control, no OSS/commercial boundary crossed, bounded rollback.

**D1. Slicing and tiers.**

| # | Option | Judgement |
|---|---|---|
| 1 | **One slice S1: M1 tests, M2 source, M3 trackers** | The two items are the same two reads in two methods of one class; one harness serves both; F-529's method has no caller, so a slice of its own would be built, tested and inert; one `git revert` range undoes everything |
| 2 | D5-R1 only | Leaves the same read, the allow-list entry and the masking double for F-529's one-line change |
| 3 | Two slices | Doubles the paperwork for four changed lines; the second has no consumer |
| 4 | One slice plus F-528 | A chief resolver is approval-routing design; the map is pinned; out |

**Tiers.** **M1 STANDARD**: tests only; the double's edit cannot fail on the base. **M2 HIGH**: two reads in a path that is reached from the lifecycle (`:7962`) and **swallows every error at DEBUG at two levels** (`_request_procedure_promotion` `:2805-2806`, `_announce_promotion_request` `:2910-2911`), so a regression is silent; the id it changes is the principal the admission seam, the Ward Room's author-keyed readers and the router's recipient selection see. Review it with the Diff Reviewer. **M3 STANDARD**: trackers and the ledger.

**D2. The edit, exactly.**

| # | Option (callsign read; the id is `self.id` in all) | Judgement |
|---|---|---|
| 1 | **`self.callsign or agent_type`** | `BaseAgent.callsign` is a class attribute `""` (`substrate/agent.py:39`); `AgentOnboardingService.wire_agent` sets it from the registry when the type has a callsign (`agent_onboarding.py:191-194`; `:301` and `:320` for an existing and a chosen callsign), as every pool's spawn hook (`runtime.py:2680`); empty only for a type with no callsign, which keeps the old default (the type). The same shape as five reads in the file (`:7663`, `:7693`, `:7704`, `:10885`, `:10901`: `self.callsign or self.agent_type`), and the Counselor, itself a `CognitiveAgent`, posts its DMs exactly so (`cognitive/counselor.py:2341-2354`: `agent_a_id=self.id`, `callsign_a=self.callsign`, `author_id=self.id`, `author_callsign=self.callsign`). No side effect |
| 2 | `self._resolve_callsign() or agent_type` | Adds BF-101's birth-certificate recovery, but it mutates the agent and logs a WARNING from a path that swallows every error, and needs a registry case; a later swap costs one token |
| 3 | `getattr(self, "callsign", agent_type)` | Wrong: the class default is `""`, so the default never applies; and a guard on a name the class defines |
| 4 | Set `_agent_id` and `_callsign` in `__init__` | A second copy of two attributes the agent already has |

For the id: `BaseAgent.__init__` sets `self.id` from the `agent_id` keyword or a uuid (`agent.py:42`); production passes `generate_agent_id(...)` (`substrate/pool.py:529-535`, `:616-622`) through `spawner.spawn` (`spawner.py:47`: `agent_class(pool=pool, **kwargs)`), so it is `{agent_type}_{pool}_{index}_{hash8}` (`identity.py:17-27`); the same file already reads `self.id` for the trust score ("BF-263: Use self.id, not agent_type", `:2960-2961`). **The test double** sets `id` and `callsign` itself (`tests/test_teaching_protocol.py:80-81`), so it needs no private attribute. **The second arguments stay** (`approver_id = approver` `:2888`; `target_callsign` `:2996`). **F-528 stays out, in one line:** the approver and the teaching target are names that no agent id equals, and resolving a chief's registered id is the approval-routing design F-528 itself assigns to a later item, with the chief map pinned by `tests/test_promotion_routing.py`. A control case pins the unchanged keys so the gap stays visible.

**D3. The tests.**

| # | Option | Judgement |
|---|---|---|
| 1 | **A real `CognitiveAgent` (constructed as the spawner does), a real `WardRoomService` on `tmp_path`, `check_at` replaced by a recorder in the two modules that call it, driven through `_request_procedure_promotion` (the method the lifecycle calls at `:7962`; it calls `_announce_promotion_request` at `:2798`) and `_teach_procedure`; the assertions read stored rows, and one case hands the stored author to the production router's `find_targets_for_agent`** | Crosses the seams from the caller to the stored row, to the id the shadow check was handed, and to the router's choice of who is told; both methods swallow their errors, so only stored rows prove a post happened |
| 2 | The same with a real `AdmissionService` and its identity, stop and ticket fixtures | The M3e4b tests need four fixtures for what one recorder shows |
| 3 | Assert on `AsyncMock` calls (the existing teaching tests' style) | The defect passed exactly this: a double that sets the attribute |

Format (the BF-930/932 lessons): one fenced block for the new file; every label names its file by full path; `built` is `pytest.mark.xfail(raises=AssertionError, strict=True)` unless `PROMOTION_POST_RUNXFAIL=1`, and **no case can fail on the base anywhere but at an `assert`**: the only patched names exist on the base (`check_at` in `ward_room/channels.py:10` and `ward_room/service.py:12`), `dms[0]` and `[...]` are read only after the assert that guards them, and the fixture helpers assert their own premises. The block is ASCII and LF; counts are "expected" until the oracle measures them.

**D4. The existing DM channels** (the one behaviour change, with its two visible effects; section 10 L1, L2, L8).

| # | Option | Judgement |
|---|---|---|
| 1 | **No migration** | A type-named channel is shared by every agent of the type (the name cuts each id to 8 characters), so no stored row says which agent it belonged to; the rows are history, valid as written; rollback is `git revert` with nothing to undo |
| 2 | A lookup that tries the type-named channel first | Keeps the shared channel and the wrong creator alive, and adds a second lookup to every post |
| 3 | Migrate creators and members to agent ids | Ambiguous (which agent?), irreversible by revert, a data change in the Ward Room for a P2 read fix |

*Inside the envelope:* backward-compatible (no schema, API or config change; old rows untouched); nothing refused either way (BF-903's guard passes a slot id: `visiting_certificate` says a slot id "matches neither [key shape] and costs no lookup", `visiting_officers.py:318-319`; and the author-keyed restriction check cannot refuse a post that the old reads let through, because no production code sets a restriction: section 11); rollback by revert. *What changes, derived:* the DM channel's name is built from the first 8 characters of each id, and an agent's id starts with its type. **A type of 8 or more characters names the same channel before and after** (counted in code: 32 of the 40 `CognitiveAgent` subclasses with a literal `agent_type`): a channel opened by an older build is *found* (`channels.py:252-263`, returned before anything is created or subscribed), keeps `created_by` and its members as the old reads recorded them (the type string), adds no member, and receives the next post with the agent's own id and callsign. **A shorter type names a new channel** (8 of 40: the next promotion DM opens it with the agent's id as creator and member; the old channel keeps its threads and is not used again). *A reader of an old channel sees* the agent's earlier threads authored by its type string and later ones by its callsign and id (the same agent under two names), and in the short-type case two channels for one pair. The author-keyed readers (`ward_room/messages.py:428-432`, `cognitive/social_memory.py:112-117`, credibility, the thread's episode) now see the agent where they saw a type string. **A second effect, on delivery (L8):** the router picks a DM's recipients by the first 8 characters of an agent's id in the channel name and drops the author by id, so a promotion DM authored by a type string told an agent of the poster's type (the poster itself when alone) about its own post; with the agent's id the poster is dropped (a same-type peer, if any, is still told, because the name carries only 8 characters). Cases K3a and K3b pin the channel effects and B3 the delivery effect.

**D5. The paperwork.**

| # | Option | Judgement |
|---|---|---|
| 1 | **No number: heads that start with a word** (`Promotion posts name their author ...`, `Promotion posts read the agent's own id and callsign ...`) and subjects that start `Promotion-post identity ...`; the parents named by item id and issue number | `gen_ad_ledger.py` reads a tracker line only when it starts, after markup, with `AD-`, `BF-`, `AD ` or `BF ` (`parse_entry_lines`, `:209-211`), and a commit subject only for tokens at its head (`_leading_tokens`, `:153-173`); `ad_ceiling.py` reads `AD-` tokens in subjects, titles and prompt names; none appears. No ledger number moves |
| 2 | Name the work BF-954 | The umbrella stays open with 160 items; a head token would mark it "mentioned" or "shipped" |
| 3 | Allocate a new BF | Both items already have a home; a new number would invent a second owner |

**The line each parent gets.** The slice closes nothing. After M3 merges the orchestrator: (a) in #1754 ticks `- [ ] [#1604] **D5-R1 ...` in the body (live: unticked on 2026-11-13; the body is 256,104 characters) and posts one comment; (b) in #1523 ticks `- [ ] **F-529.` in comment `6402853183` (live: unticked, with F-528) and posts one comment. **The #1754 comment says:** D5-R1 fixed on `main` at `<merge sha>`: `_announce_promotion_request` and `_teach_procedure` read `self.id` and `self.callsign`; the anchors in the item were old (the reads were at `:2859-2860` and `:2979-2980`); a real agent, a real Ward Room and the shadow check are now tested; one behaviour change (the Ward Room now sees the agent, not its type, as the poster: a channel opened under the old reads is found by name for a type of 8 or more characters and left unused for a shorter one, with no migration, and the promoting agent is no longer told of its own promotion DM); two limits recorded (the channel name still cuts ids to 8 characters; the second member is still a name, F-528). **The #1523 comment says:** F-529 fixed by the same change; `_teach_procedure` still has no production caller (the shell command and the API route teach as the Captain), so a future caller inherits the reads; F-528 stays open; and a sibling of the same class remains: `cognitive/communication_benchmarks.py:286` reads `getattr(agent, "_callsign", "")` (its own allow-list entry, `guard_name_allowlist.txt:15`). The Captain's action: none required (section "Not in this issue").

**D6. Public text.** No crew name, thread id, timestamp, live count or vessel line in any test, comment, tracker line, commit message or this contract. Fixtures are synthetic (`test-id`, `test-agent`, `t-agent`, `test-callsign`, `test-peer`). **One exception, named:** block N1-2's SEARCH quotes two existing lines of `tests/test_teaching_protocol.py` that contain a fixture callsign the repository already holds (`:81`, `:94`, `:237`); a SEARCH names the text it replaces, the REPLACE adds no name, and the new test file uses none. The chief's key in the department case is read from `CognitiveAgent._DEPARTMENT_CHIEFS["engineering"]`, so no chief's name is written in the new file. Agent types are code identifiers (section 11 lists the 8 short ones).

## 4. Milestones and gates

`PY` = `d:/ProbOS/.venv/Scripts/python.exe`. All commands run **from the repository root**, exactly as typed. **Who runs what.** The Builder may run only the focused pytest files named in G1 and G2 (always `-n 0`) and the architecture check. **Mine (the orchestrator's):** the broad gate, the mutation campaign, any wide run, the ledger comparison against the measured diff, the pull request.

**M0 (before M1):** record the collected count (`--collect-only -q`) of every existing file named in G2; the new file does not exist yet. (Static counts of test functions on the reading tree: `tests/test_teaching_protocol.py` 8, `tests/test_promotion_routing.py` 10, `tests/test_bf925_guard_names.py` 6.)

| M | Blocks | Gate |
|---|---|---|
| M1 | N1-1, N1-2 | G1 |
| M2 | P2-1, P2-2 (the reads), P2-3, P2-4 (the allow-list), P2-5, P2-6 (the marker and its import) | G2 |
| M3 | P3-1, P3-2, ledger | G3 |

- **G1.** `PY -m pytest tests/test_promotion_post_identity.py tests/test_teaching_protocol.py -q -n 0 -p no:randomly`. **Expected:** the 6 controls of the new file pass (K1 x2, K2 x3, K3a), the 6 built cases xfail (B1 x2, B2 x2, B3, K3b: `raises=AssertionError, strict=True`; an XPASS or any other exception is a FAIL), the teaching file's 8 pass: **14 passed, 6 xfailed** (expected, not measured). Then once with the marker off (`$env:PROMOTION_POST_RUNXFAIL = "1"`, the new file alone, then `Remove-Item Env:PROMOTION_POST_RUNXFAIL`): **6 failed, 6 passed**, each failure at its own `assert` (read the last line of each: `AssertionError`), none at an import, a fixture or a call.
- **G2 (suite order).** (1) `PY -m pytest tests/test_promotion_post_identity.py tests/test_teaching_protocol.py tests/test_promotion_routing.py tests/test_bf925_guard_names.py -q -n 0 -p no:randomly` (the new file 12 passed; the double's file; the chief map; the guard-name scan that P2-3 keeps green). (2) `PY -m pytest tests/test_ward_room.py tests/test_ward_room_dms.py tests/test_ad621_channel_visibility.py tests/test_ad1346_admission_store_writes.py tests/test_ad1346_admission_effect_census.py tests/test_ad1346_admission_file_write_census.py tests/test_ad1343_stop_seam_inventory.py -q -n 0 -p no:randomly` (the Ward Room the new cases drive, its DM channel tests, the router's target-selection tests that B3 reads beside, and the seams and censuses that read `ward_room/channels.py`, `ward_room/service.py` and `cognitive_agent.py` by file and scope, not by line: none reads the lines we change). (3) `PY -P scripts/check_architecture_principles.py --check`. **Expected:** the new file 12 passed; every other file 0 failed with collected counts equal M0; the check clean (no method added: `CognitiveAgent` stays one `srp-size` row with the same two triggers; no `db-connect`, `unowned-task` or `layer-import` row moves).
- **G3 (M3).** `PY -P scripts/gen_ad_ledger.py`; then `PY -P scripts/gen_ad_ledger.py --check`; then `PY -m pytest tests/test_ad1184_ad_ledger.py -q -n 0`. **Expected (not measured):** **no AD or BF number moves** (no head of this slice is a number); the report's git-log row changes (the pinned snapshot's time, head id and subject count); the skipped-line numbers it lists for `PROGRESS.md` shift by the 4 lines the entry adds (and for `DECISIONS.md` by its entry's lines, if any are listed below the insertion); the non-check run rewrites `docs/development/ad-ledger-snapshot.json`. **Any changed row of an AD or BF number is a hard stop for the Architect.**

**Final gate (mine, once, after the Diff Reviewer's findings are repaired and the reviewed tree is committed locally):** the mutation rows of section 9, and `PY scripts/run_test_gate.py --label promotion-post-identity --receipt logs/gates/promotion-post-identity.receipt.json`. **Harness rule.** No source change made to pass a test, no skip, no loosened assertion; a failing new case at G2, or any existing test failing, goes back to the Architect.

## 5. Commit messages

- **Contract commit (the orchestrator's):** `Promotion-post identity (D5-R1 of #1754, F-529 of #1523): contract for reading the agent's own id and callsign in the promotion request and the teaching post`
- **M1:** `Promotion-post identity S1 M1: tests for the promotion request and the teaching post carrying the agent's own id and callsign, xfail until built (#1754, #1523)`
- **M2:** `Promotion-post identity S1 M2: the two methods read self.id and self.callsign, and the guard allow-list drops its _callsign entry for cognitive_agent.py (#1754, #1523)`
- **M3:** `Promotion-post identity S1 M3: trackers and ledger (#1754, #1523)`; its body ends with the two lines `Refs #1754.` and `Refs #1523.`

Neither parent is closed by the slice (both are open umbrellas), so none carries `Closes`. No subject starts with, or contains, an `AD-` or `BF-` token; no message names a crew member, a thread or a live figure.

## 6. Tests

**New file `tests/test_promotion_post_identity.py` (12 cases).** Fixtures: a real `CognitiveAgent` subclass (`agent_type` `test-agent`, id `test-id`) built as the spawner builds one (`pool` and `agent_id` in the constructor), given the callsign `wire_agent` sets; a real `WardRoomService` on `tmp_path` (the fixture of `tests/test_ward_room.py:18-32`); a runtime that is a `SimpleNamespace` holding that Ward Room, an ontology (or `None`), a trust double and a procedure-store double; a recorder that replaces `check_at` in `ward_room/channels.py` and `ward_room/service.py` (`monkeypatch`, restored by pytest); for B3 the production `WardRoomRouter` over a registry that holds just the agent (the doubles of `tests/test_ad621_channel_visibility.py:50-90`; `is_crew_agent` patched to true as that file does). Every case has its own temporary database; nothing is shared. The drivers are `_request_procedure_promotion` (which calls `_announce_promotion_request`) and `_teach_procedure`; both swallow their errors, so each case asserts that threads and exactly one DM channel exist before it reads them.

| Case | Kind | Asserts |
|---|---|---|
| B1 the posts and the DM channel carry the agent's own id (2 cases: promotion-request, teaching) | built | every thread's `author_id`, the DM channel's `created_by`, a DM member, and every id the shadow check was handed all equal `agent.id` (`test-id`, not `test-agent`) |
| B2 the posts are signed with the agent's callsign (2) | built | every thread's `author_callsign` is the agent's callsign; the DM channel's description starts `DM: <callsign> ` |
| B3 the promoting agent is not its own DM recipient | built | with the production-shaped id `test-agent_test-pool_0_abcd1234` (state ACTIVE), the router's `find_targets_for_agent(<the DM channel>, <the stored thread's author_id>, mentions=[])` returns `[]` (nobody else is in the DM; the router drops the author by id) |
| K1 an agent with no callsign is signed with its type (2) | control | the same reads give the type, and the description starts `DM: test-agent ` (passes on the base; kills dropping the fallback) |
| K2 the second member of the DM is still a name, not an agent id (3: captain-approver, department-chief-approver, teaching-target) | control | the DM has exactly two members and one of them is the literal key (`captain`; the chief's key read from `_DEPARTMENT_CHIEFS["engineering"]`; the teaching target): F-528's gap stays visible; passes on the base |
| K3a a channel opened under a long type is found and left as it was | control | an agent whose id is `test-agent_test-pool_0_abcd1234`; a channel opened as the old reads opened it (`get_or_create_dm_channel("test-agent", "captain")`) is the only DM after the post, keeps `created_by` `test-agent` and its two members: nobody is added |
| K3b a channel opened under a short type is left unused and a new one opens | built | with type `t-agent` and id `t-agent_test-pool_0_abcd1234` there are two DM channels after the post, the new one created by the agent's id, and the old one has no thread |

The pass-before-build set is the six controls (the base posts, finds and subscribes exactly as these assert). **How each built case fails on the base:** B1, B2 at their set-equality assert (the base returns `{"test-agent"}`); B3 at `assert targets == []` (the base's stored author is the type, so the router returns the poster as a recipient: `["test-agent_test-pool_0_abcd1234"]`); K3b at `assert len(dms) == 2` (the base finds the old channel, so there is one). **What the file does not do:** it does not assert which channel the department thread lands in (F-528's second half), it does not run the real `AdmissionService` (the recorder shows the id at the seam), and it asserts nothing about `_teach_procedure` having a caller (**no production consumer reaches it**: the B and K cases call it as its own tests do, through the real Ward Room; a future agent-initiated teaching step would inherit the reads). **The existing file:** `tests/test_teaching_protocol.py` keeps its 8 cases; they pass before and after (they assert the title, the steps and the return value, never the author), and with the double's two private attributes gone they exercise the new reads through `agent.id` and `agent.callsign`.

## 7. The contract

Labels restart in the slice. Section 6 names the cases; this section gives every block. `PY`, the commands and who runs them are in section 4. SEARCH text is LF; the working copies are CRLF (the apply tool matches on LF). **Every SEARCH below occurs exactly once in its file on `origin/main` `4d8c51e4` and on the reading tree `b83ed1e3`, starts at a line start, and is ASCII** (section 11: run on the LF blobs of both refs: 5 SEARCHes of existing files, plus the 2 tracker anchors, 0 problems; the two SEARCHes of the new test file are checked against block N1-1 itself). No block's SEARCH overlaps another's. The blocks of one file are applied in label order. The REPLACE text of every block is ASCII. **A label line names the file of its block by the full path in backticks**: the apply tool takes a pair's file from the nearest preceding label line that names an existing path (or, for a new file, from the `New file` label).

### 7.1 Slice S1 (the promotion request and the teaching post read the agent's own id and callsign)

#### S1 M1

**N1-1.** New file `tests/test_promotion_post_identity.py` (12 cases; section 6 names them). It imports only modules that exist on the base, and every case that can fail on the base fails at an `assert` (no unpack or index before the assert that guards it; no patch of a name that the base lacks).

```python
"""Promotion posts name their author: D5-R1 of #1754 and F-529 of #1523.

``CognitiveAgent._announce_promotion_request`` (a procedure's promotion request) and ``_teach_procedure`` (a taught
procedure) post to the Ward Room, open a DM channel and subscribe its members. They used to read
``getattr(self, "_agent_id", agent_type)`` and ``getattr(self, "_callsign", agent_type)``; no agent has either
attribute, so every such post carried the agent's TYPE as its author id, as its DM channel's creator and member, and
as the id the shadow admission check was handed. These cases drive a real ``CognitiveAgent`` into a real
``WardRoomService`` on a temporary database and read back what was stored; one case hands the stored author to the
production router's target selection.

Synthetic fixtures only. The cases marked ``built`` fail on the base at their own assert and pass once the two
methods read ``self.id`` and ``self.callsign``; ``PROMOTION_POST_RUNXFAIL=1`` runs them as plain cases.
"""

from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio

import probos.ward_room.channels as ward_room_channels
import probos.ward_room.service as ward_room_service
from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.types import AgentState
from probos.ward_room import WardRoomService
from probos.ward_room_router import WardRoomRouter

built = (
    (lambda func: func)
    if os.environ.get("PROMOTION_POST_RUNXFAIL") == "1"
    else pytest.mark.xfail(raises=AssertionError, strict=True)
)

_AGENT_ID = "test-id"
_AGENT_TYPE = "test-agent"
_SHORT_TYPE = "t-agent"
_CALLSIGN = "test-callsign"
_PROCEDURE_ID = "test-procedure-id"
_TARGET = "test-peer"


class _PromotingAgent(CognitiveAgent):
    """A real agent. Nothing in this file sets a private attribute on it."""

    agent_type = _AGENT_TYPE
    instructions = "Test instructions."


class _ShortTypeAgent(_PromotingAgent):
    """The same agent with a type of fewer than 8 characters (a DM channel name keeps 8 characters of each id)."""

    agent_type = _SHORT_TYPE


class _Ontology:
    """What the two methods ask of the ontology: the department of an agent type."""

    def __init__(self, department: str) -> None:
        self._department = department

    def get_agent_department(self, agent_type: str) -> str:
        return self._department


class _Trust:
    """What a teaching reads of the trust network: a score above the teaching threshold."""

    def get_score(self, agent_id: str) -> float:
        return 0.9


def _promotion_result(criticality: str) -> dict:
    return {
        "eligible": True,
        "criticality": criticality,
        "procedure_name": "test-procedure",
        "procedure_description": "A synthetic procedure.",
        "compilation_level": 4,
        "intent_types": ["test_intent"],
        "quality_metrics": {"effective_rate": 0.9, "total_completions": 12},
    }


class _ProcedureStore:
    """The procedure-store reads the two methods make."""

    def __init__(self, criticality: str) -> None:
        self._criticality = criticality

    async def request_promotion(self, procedure_id: str) -> dict:
        return _promotion_result(self._criticality)

    async def get(self, procedure_id: str) -> SimpleNamespace:
        return SimpleNamespace(
            name="test-procedure",
            description="A synthetic procedure.",
            compilation_level=5,
            steps=[SimpleNamespace(step_number=1, action="run the first step")],
            preconditions=[],
            postconditions=[],
        )

    async def get_promotion_status(self, procedure_id: str) -> str:
        return "approved"

    async def get_quality_metrics(self, procedure_id: str) -> dict:
        return {"total_completions": 12, "effective_rate": 0.95}


@pytest_asyncio.fixture
async def room(tmp_path):
    service = WardRoomService(db_path=str(tmp_path / "ward_room.db"))
    await service.start()
    yield service
    await service.stop()


@pytest.fixture
def presented(monkeypatch):
    """The id each shadow store-write check was handed, in order: both Ward Room modules call ``check_at``."""
    seen: list[object] = []

    def record(service: object, *, effect: str, presented_id: object) -> None:
        seen.append(presented_id)

    monkeypatch.setattr(ward_room_channels, "check_at", record)
    monkeypatch.setattr(ward_room_service, "check_at", record)
    return seen


def _slot_id(agent_type: str) -> str:
    """An agent id in the production shape ``{agent_type}_{pool}_{index}_{hash8}`` (``substrate/identity.py``)."""
    return f"{agent_type}_test-pool_0_abcd1234"


def make_agent(
    room: WardRoomService,
    *,
    agent_cls: type[CognitiveAgent] = _PromotingAgent,
    agent_id: str = _AGENT_ID,
    callsign: str = _CALLSIGN,
    department: str = "",
    criticality: str = "low",
) -> CognitiveAgent:
    """A real agent, built as the spawner builds one (the pool and the agent id in the constructor) and given the
    callsign ``AgentOnboardingService.wire_agent`` sets. Its runtime holds the real Ward Room."""
    runtime = SimpleNamespace(
        ward_room=room,
        ontology=_Ontology(department) if department else None,
        trust_network=_Trust(),
        procedure_store=_ProcedureStore(criticality),
    )
    agent = agent_cls(pool="test-pool", agent_id=agent_id, runtime=runtime)
    agent.callsign = callsign
    return agent


async def _request_promotion(agent: CognitiveAgent) -> None:
    result = await agent._request_procedure_promotion(_PROCEDURE_ID)
    assert result is not None and result["eligible"] is True, "the promotion request never reached the announcement"


async def _teach(agent: CognitiveAgent) -> None:
    assert await agent._teach_procedure(_PROCEDURE_ID, _TARGET) is True, "the teaching DM was not sent"


async def _stored(room: WardRoomService) -> tuple[list, list]:
    """Every thread in the room, and its DM channels."""
    channels = await room.list_channels()
    threads = [thread for channel in channels for thread in await room.list_threads(channel.id)]
    return threads, [channel for channel in channels if channel.channel_type == "dm"]


def _router_over(agent: CognitiveAgent) -> WardRoomRouter:
    """The production router over a registry that holds just this agent; the collaborators it does not use to pick
    targets are doubles, as tests/test_ad621_channel_visibility.py builds it."""
    registry = MagicMock()
    registry.all.return_value = [agent]
    config = MagicMock()
    config.ward_room.event_coalesce_ms = 200
    return WardRoomRouter(
        ward_room=MagicMock(),
        registry=registry,
        intent_bus=MagicMock(),
        trust_network=MagicMock(),
        ontology=None,
        callsign_registry=MagicMock(),
        episodic_memory=None,
        event_emitter=MagicMock(),
        event_log=MagicMock(),
        config=config,
    )


_DRIVERS = pytest.mark.parametrize("drive", [_request_promotion, _teach], ids=["promotion-request", "teaching"])


@built
@_DRIVERS
async def test_the_posts_and_the_dm_channel_carry_the_agents_own_id(drive, room, presented):
    agent = make_agent(room)
    assert agent.id == _AGENT_ID and agent.agent_type == _AGENT_TYPE, "the premise: the agent's id is not its type"

    await drive(agent)

    threads, dms = await _stored(room)
    assert threads and len(dms) == 1, (threads, dms)
    assert {thread.author_id for thread in threads} == {agent.id}
    assert dms[0].created_by == agent.id
    assert agent.id in await room.get_channel_subscriber_ids(dms[0].id)
    assert presented and set(presented) == {agent.id}


@built
@_DRIVERS
async def test_the_posts_are_signed_with_the_agents_callsign(drive, room):
    agent = make_agent(room, callsign=_CALLSIGN)

    await drive(agent)

    threads, dms = await _stored(room)
    assert threads and len(dms) == 1, (threads, dms)
    assert {thread.author_callsign for thread in threads} == {_CALLSIGN}
    assert dms[0].description.startswith(f"DM: {_CALLSIGN} ")


@built
async def test_the_promoting_agent_is_not_its_own_dm_recipient(room):
    agent = make_agent(room, agent_id=_slot_id(_AGENT_TYPE))
    agent.state = AgentState.ACTIVE  # alive, as a started agent is

    await _request_promotion(agent)

    threads, dms = await _stored(room)
    assert len(dms) == 1, dms
    posted = [thread for thread in threads if thread.channel_id == dms[0].id]
    assert len(posted) == 1, threads
    with patch("probos.ward_room_router.is_crew_agent", return_value=True):
        targets = _router_over(agent).find_targets_for_agent(dms[0], posted[0].author_id, mentions=[])
    assert targets == [], (posted[0].author_id, targets)  # the router drops the author by id; nobody else is in the DM


@_DRIVERS
async def test_an_agent_with_no_callsign_is_signed_with_its_type(drive, room):
    agent = make_agent(room, callsign="")

    await drive(agent)

    threads, dms = await _stored(room)
    assert threads and len(dms) == 1, (threads, dms)
    assert {thread.author_callsign for thread in threads} == {agent.agent_type}
    assert dms[0].description.startswith(f"DM: {agent.agent_type} ")


@pytest.mark.parametrize(
    ("drive", "criticality", "department", "key"),
    [
        (_request_promotion, "high", "", "captain"),
        (_request_promotion, "low", "engineering", CognitiveAgent._DEPARTMENT_CHIEFS["engineering"]),
        (_teach, "low", "", _TARGET),
    ],
    ids=["captain-approver", "department-chief-approver", "teaching-target"],
)
async def test_the_second_member_of_the_dm_is_still_a_name_not_an_agent_id(drive, criticality, department, key, room):
    """The gap F-528 of #1523 records stays visible: the approver and the teaching target are names, not ids."""
    agent = make_agent(room, criticality=criticality, department=department)

    await drive(agent)

    _, dms = await _stored(room)
    assert len(dms) == 1, dms
    members = await room.get_channel_subscriber_ids(dms[0].id)
    assert key in members and len(members) == 2, (key, members)


async def test_a_dm_channel_opened_under_a_long_type_is_found_and_left_as_it_was(room):
    agent = make_agent(room, agent_id=_slot_id(_AGENT_TYPE))
    old = await room.get_or_create_dm_channel(_AGENT_TYPE, "captain")  # what the old reads opened

    await _request_promotion(agent)

    _, dms = await _stored(room)
    assert [dm.id for dm in dms] == [old.id], dms
    assert dms[0].created_by == _AGENT_TYPE
    assert await room.get_channel_subscriber_ids(old.id) == {_AGENT_TYPE, "captain"}


@built
async def test_a_dm_channel_opened_under_a_short_type_is_left_unused_and_a_new_one_opens(room):
    agent = make_agent(room, agent_cls=_ShortTypeAgent, agent_id=_slot_id(_SHORT_TYPE))
    old = await room.get_or_create_dm_channel(_SHORT_TYPE, "captain")  # what the old reads opened

    await _request_promotion(agent)

    _, dms = await _stored(room)
    assert len(dms) == 2, dms
    opened = [dm for dm in dms if dm.id != old.id]
    assert [dm.created_by for dm in opened] == [agent.id], dms
    assert await room.list_threads(old.id) == []
```

**N1-2** (`tests/test_teaching_protocol.py`: the double stops carrying the two attributes that masked the defect). The two removed lines are the repository's own text (a SEARCH names the text it replaces); the REPLACE adds no name.
SEARCH:
```
    agent.trust_score = defaults.get("trust_score", 0.9)
    agent._trust_score = defaults.get("trust_score", 0.9)
    agent._callsign = defaults.get("callsign", "LaForge")
    agent._agent_id = defaults.get("id", "agent-teacher-001")
    return agent
```
REPLACE:
```
    agent.trust_score = defaults.get("trust_score", 0.9)
    agent._trust_score = defaults.get("trust_score", 0.9)
    # No private _callsign or _agent_id: a CognitiveAgent has neither, and the promotion and teaching posts read
    # self.callsign and self.id (tests/test_promotion_post_identity.py drives a real agent through both).
    return agent
```

#### S1 M2

Apply the blocks in label order. `P2-1` and `P2-2` edit `src/probos/cognitive/cognitive_agent.py`; `P2-3` and `P2-4` edit `tests/fixtures/guard_name_allowlist.txt`; `P2-5` and `P2-6` edit the new test file (the marker and the import it alone used).

**P2-1** (`src/probos/cognitive/cognitive_agent.py`: `_announce_promotion_request`, the two reads).
SEARCH:
```
            agent_type = getattr(self, "agent_type", "")
            agent_id = getattr(self, "_agent_id", agent_type)
            callsign = getattr(self, "_callsign", agent_type)

            # Post to appropriate channel
```
REPLACE:
```
            agent_type = getattr(self, "agent_type", "")
            agent_id = self.id  # D5-R1 (#1754): the agent's own id; its type is not an id
            callsign = self.callsign or agent_type  # the type only for an agent with no callsign

            # Post to appropriate channel
```

**P2-2** (`src/probos/cognitive/cognitive_agent.py`: `_teach_procedure`, the two reads).
SEARCH:
```
        callsign = getattr(self, "_callsign", agent_type)
        agent_id = getattr(self, "_agent_id", agent_type)

        body = (
```
REPLACE:
```
        callsign = self.callsign or agent_type  # F-529 (#1523): as the promotion request reads it
        agent_id = self.id  # F-529 (#1523): the agent's own id, not its type

        body = (
```

**P2-3** (`tests/fixtures/guard_name_allowlist.txt`: the entry that P2-1 and P2-2 resolve; `tests/test_bf925_guard_names.py` fails on an entry whose name is no longer guarded in its file).
SEARCH:
```
src/probos/cognitive/captain_engagement.py | captain_dm_queue_depth | finding | ward_room.captain_dm_queue_depth has no production definition
src/probos/cognitive/cognitive_agent.py | _callsign | finding | self._callsign has no production definition (agents define callsign)
src/probos/cognitive/cognitive_agent.py | get_by_intent | finding | self._procedure_store.get_by_intent has no production definition
```
REPLACE:
```
src/probos/cognitive/captain_engagement.py | captain_dm_queue_depth | finding | ward_room.captain_dm_queue_depth has no production definition
src/probos/cognitive/cognitive_agent.py | get_by_intent | finding | self._procedure_store.get_by_intent has no production definition
```

**P2-4** (`tests/fixtures/guard_name_allowlist.txt`: the header note, so the file records why the entry went).
SEARCH:
```
# A2 (2026-10-26): nats_bus.py reconnected_count moved from duck to finding (nats-py 2.14.0 has no such attribute).
src/probos/channels/base.py | pairing_service | finding | self.runtime.pairing_service has no production definition
```
REPLACE:
```
# A2 (2026-10-26): nats_bus.py reconnected_count moved from duck to finding (nats-py 2.14.0 has no such attribute).
# A3: the cognitive_agent.py _callsign entry is gone: the promotion request and the teaching post read self.callsign now (F-529 of #1523; D5-R1 of #1754).
src/probos/channels/base.py | pairing_service | finding | self.runtime.pairing_service has no production definition
```

**P2-5** (`tests/test_promotion_post_identity.py`: the marker, after P2-1 to P2-4).
SEARCH:
```
built = (
    (lambda func: func)
    if os.environ.get("PROMOTION_POST_RUNXFAIL") == "1"
    else pytest.mark.xfail(raises=AssertionError, strict=True)
)
```
REPLACE:
```
def built(func):
    """The built cases pass; the marker no longer fails them."""
    return func
```

**P2-6** (`tests/test_promotion_post_identity.py`: the import that only the marker used).
SEARCH:
```
import os
from types import SimpleNamespace
```
REPLACE:
```
from types import SimpleNamespace
```

#### S1 M3: tracking

**P3-1.** `PROGRESS.md`. The anchor is the title line and the blank line after it. Replace `DATE` with M3's date. The entry is 4 lines (heading, two bullets, blank). The heading starts with a word, not a number, so the ledger reads no head token from it.
SEARCH:
```
# ProbOS Progress

```
REPLACE:
```
# ProbOS Progress

**Promotion posts name their author (DATE), parts of #1754 (D5-R1) and #1523 (F-529) -- a promotion request and a taught procedure now post, open their DM channel and subscribe under the agent's own id and callsign, not its type.**
- **Base.** `CognitiveAgent._announce_promotion_request` and `_teach_procedure` read `getattr(self, "_agent_id", agent_type)` and `getattr(self, "_callsign", agent_type)`; no agent has either attribute, so every promotion post carried the agent's type as its author id, as its DM channel's creator and member, and as the id the shadow admission check was handed. The teaching test's double set both attributes, and the announcement had no test.
- **Change.** The two methods read `self.id` and `self.callsign` (the type only for an agent with no callsign); the second member of each DM (the approver, the teaching target) is still a name, not an id (F-528 of #1523 stays open); `_teach_procedure` still has no production caller. **One behaviour change:** the Ward Room now sees the agent, not its type, as the poster. So a DM channel opened under the old reads is found by name where the type has 8 or more characters (the next post lands in it, with its old creator and members) and is left unused where it has fewer (the next promotion DM opens a new channel), and the router no longer tells the promoting agent of its own promotion DM (it matched the author by id, and the id was the type); nothing is migrated or refused. A new test file drives a real agent into a real Ward Room; the teaching double no longer carries the two attributes; the guard allow-list drops its `_callsign` entry for `cognitive_agent.py`. Contract `prompts/promotion-post-identity-reads.md`. Refs #1754, #1523.

```

**P3-2.** `DECISIONS.md`. The anchor is the heading line of the entry that follows this period's entries (once on `origin/main` `4d8c51e4`, at line 1748, and once on the reading tree, at line 1764; the BF-930/932 batch's and #1769's entries are inserted before it, and this slice's entry is inserted before it as well, so the order is the order of landing). If a later change moves that heading, anchor on the last line of the entry that then lands last. Replace `DATE` with M3's date. The heading names no AD or BF number.
SEARCH:
```
### AD-1346 M3e4d9 -- part (a) of the pending workforce scopes, classified (2026-11-05, #1604)
```
REPLACE:
```
### Promotion posts read the agent's own id and callsign (DATE, parts of #1754 D5-R1 and #1523 F-529)

- *Scope.* `cognitive/cognitive_agent.py` (two reads in each of `_announce_promotion_request` and `_teach_procedure`), one new test file, the teaching test's double, one line of `tests/fixtures/guard_name_allowlist.txt`. Contract `prompts/promotion-post-identity-reads.md`.
- *G1 (the edit).* `self.id`, and `self.callsign or agent_type`. Rejected: `_resolve_callsign()` (its birth-certificate recovery mutates the agent and logs a warning from a path that swallows every error; the swap later costs one token); setting `_agent_id` and `_callsign` on the agent (a second copy of two attributes it already has); resolving the approver's registered id, which is F-528's approval-routing design and stays out (the chief map is pinned by `tests/test_promotion_routing.py`).
- *G2 (existing DM channels).* A DM channel is named from the first 8 characters of each id, and an agent's id starts with its type, so a type of 8 or more characters names the same channel before and after (found, not recreated: its creator and members stay as the old reads recorded them, and the next post carries the agent's id), and a shorter type names a new one (the old channel stays, unused). The router picks a DM's recipients by the first 8 characters of an agent's id in the channel name and excludes the author by id (`ward_room_router.py`), so a post authored by a type string excluded nobody: an agent of the poster's type, the poster itself when alone, was told of its own promotion DM; it no longer is. No migration: the type-named channel is shared by every agent of the type, so no row says which agent it belonged to. Rejected: a lookup that tries the type-named channel first (it keeps the shared channel and the wrong creator alive). Nothing is refused either way: a slot id is not a visiting officer's identity, and no production code sets a posting restriction.
- *G3 (public text).* Synthetic fixtures only; no crew name, thread id, timestamp or live count in any test, comment, tracker line or commit message.
- *Residual.* L1 to L8 of the contract. *Reversal.* Revert the three commits of the slice, M3 then M2 then M1; the rows the changed code wrote (threads by an agent id, channels opened under an id) stay and are valid.

### AD-1346 M3e4d9 -- part (a) of the pending workforce scopes, classified (2026-11-05, #1604)
```

**Ledger.** Run G3 (section 4). No AD or BF number moves: no head of this slice's tracker text or commit subjects is a number. The roadmap Bug Tracker is not edited.

## 8. What this does NOT change

**Source.** The second argument of both DM calls (`approver_id = approver` `:2888`, `target_callsign` `:2996`); `_route_promotion_approval` and `_DEPARTMENT_CHIEFS` (`:2781-2828`); the channel match for the announcement (`chan_name`, `:2863-2876`: F-528's second half); the bodies and titles of the posts; both swallow arms (`:2805-2806`, `:2907-2911`, `:3011-3013`); `_request_procedure_promotion` and its trigger (`:7958-7962`); `_resolve_callsign` (`:8348-8360`); the observation keys `_agent_id` and `_callsign` (`:6189-6391`), which are correct as keys. **Ward Room.** `dm_channel_name` and its 8-character cut (`channels.py:21-30`), `get_or_create_dm_channel` (`:243-288`), `create_thread`, the schema, the shadow checks (`check_at`), the posting-restriction check and BF-903's visitor guard. **The router.** `ward_room_router.py` (its DM recipient selection is read, not edited). **Other teaching paths.** `experience/commands/commands_procedure.py` and `routers/procedures.py` teach as the Captain and are not touched. **The sibling.** `cognitive/communication_benchmarks.py:286` and its allow-list entry (`guard_name_allowlist.txt:15`). **All.** `config/system.yaml`, every Pydantic config model and generated reference; `ui/`; the commercial overlay (OSS only; no dependency; no schema change); every tracker but `PROGRESS.md`, `DECISIONS.md` and the AD ledger pair; the roadmap Bug Tracker table.

## 9. Mutation rows (each Line occurs once, stripped, in its file on M2's head)

**Not run by the Architect** (a read-only consult cannot run pytest; the oracle's run is in section 15, which corrects row 7's cell); the Lines were checked in memory against the patched `cognitive_agent.py` (each occurs once, on both refs: section 11), and the Killed-by cells are the cases I expect to fail. The oracle's campaign: each row's line replaced whole in the built file, the slice's new test file run (plus the named existing test), the file restored and its blob checked. **This table is the campaign of record only for a tree whose files equal the blobs the blocks give on `origin/main` `4d8c51e4`** (sha256 to be recorded by the oracle); a Builder whose files match does not repeat it; if a file differs, the rows naming it are rerun. Case labels are section 6's.

| # | File | Line (stripped) | Mutate to | Killed by |
|---|---|---|---|---|
| 1 | `src/probos/cognitive/cognitive_agent.py` | `agent_id = self.id  # D5-R1 (#1754): the agent's own id; its type is not an id` | `agent_id = agent_type` | B1 (promotion-request); B3; K3b |
| 2 | same | `callsign = self.callsign or agent_type  # the type only for an agent with no callsign` | `callsign = agent_type` | B2 (promotion-request) |
| 3 | same | the same line | `callsign = self.callsign` | K1 (promotion-request) |
| 4 | same | `agent_id = self.id  # F-529 (#1523): the agent's own id, not its type` | `agent_id = agent_type` | B1 (teaching) |
| 5 | same | `callsign = self.callsign or agent_type  # F-529 (#1523): as the promotion request reads it` | `callsign = agent_type` | B2 (teaching) |
| 6 | same | the same line | `callsign = self.callsign` | K1 (teaching) |
| 7 | same | `approver_id = approver` (unchanged line: the pin) | `approver_id = agent_type` | K2 (captain-approver), K2 (department-chief-approver), K3a |
| 8 | same | `agent_id, approver_id,` (unchanged: the DM's first member) | `agent_type, approver_id,` | B1 (promotion-request); K3b |
| 9 | same | `agent_id, target_callsign,` (unchanged: the teaching DM's first member) | `agent_type, target_callsign,` | B1 (teaching) |
| 10 | same | `agent_id, target_callsign,` | `agent_id, agent_id,` | K2 (teaching-target) |
| 11 | `tests/fixtures/guard_name_allowlist.txt` | block P2-3 reverted: the `_callsign` entry for `cognitive_agent.py` restored | | `tests/test_bf925_guard_names.py::test_production_guards_name_attributes_production_code_defines` (a stale entry) |
| 12 | `tests/test_teaching_protocol.py` | block N1-2 reverted, with rows 4 to 6 applied | | B1, B2 and K1 (teaching) of the new file; the old file still passes (it cannot see the defect: the reason the new file exists) |

## 10. Recorded limits

- **L1. Existing DM channels (the first visible effect of the one behaviour change: the Ward Room now sees the agent, not its type, as the poster).** A channel opened under the old reads is found by name where the agent's type has 8 or more characters (32 of the 40 `CognitiveAgent` subclasses with a literal `agent_type`, counted in code, not live): it keeps its type-string creator and members, no member is added (the found channel is returned before anything is created or subscribed, `channels.py:252-263`), and the next post carries the agent's id and callsign; where the type has fewer (8 of the 40) the name differs, the next promotion DM opens a new channel (creator and member: the agent's id) and the old one keeps its threads and is not used again. No migration. A reader sees the agent under two names in one channel (earlier threads: its type; later: its callsign and id) or two channels for one pair. Pinned by K3a and K3b.
- **L2. The channel name still cuts each id to 8 characters** (`dm_channel_name`, AD-1229's docstring: "types that share a prefix share a channel name; a reader must not treat a key as one agent"). Agents of one type (and types that share 8 characters) still share one DM channel per approver; whoever opened it is its creator and member, and a later agent posts into it without being added. D5-R1's sentence "every cognitive agent's DM to one approver names the same channel" is therefore cured for the *records the call writes* (author, callsign, shadow id, a channel it creates), not for the channel's granularity. Not changed.
- **L3. The second member is a name** (F-528): the approver is a department chief's lowercase key or `captain`, the teaching target a callsign; no agent id equals a chief's key. K2 pins it. The test does not assert which channel the department thread lands in (F-528's text records that the department channel is matched by id against channel names).
- **L4. `_teach_procedure` has no production caller** (section 11). The shell command and the API route teach as the Captain. Its fix is exercised only by its tests until an agent-initiated teaching step exists (the consumer that would reach it; none does today); that caller inherits the reads. The two entry points that exist (the shell's `/procedure teach` and the API's `POST /teach`) run their own bodies and never call it.
- **L5. Errors are still swallowed at DEBUG**: three levels in the promotion request (the caller `:2805-2806`, the method's DM arm `:2907-2908` and its outer arm `:2910-2911`) and one in the teaching (`:3011-3013`), so a failed post leaves nothing at INFO (pre-existing); the new cases read stored rows for that reason. If a production path ever restricts an agent from posting, its promotion posts will be refused and swallowed like any other post of it; before the fix they bypassed the check by posting as the type. No production code sets a restriction today (section 11).
- **L6. The sibling** `cognitive/communication_benchmarks.py:286` reads `getattr(agent, "_callsign", "")` (allow-list entry `:15`): the same class of defect on a benchmark path; recorded in the #1523 comment, not changed.
- **L7. Author-keyed readers now see the agent.** The credibility row (`threads.py:492-497`), the thread's episode (`:574-620`), the content firewall's per-author state, the peer-similarity check, the router's shadow decision (`ward_room_router.py:652`: `origin_id=author_id`) and the shadow admission check's principal (D5-R1's probe counted a principal-mismatch finding from these posts) key on the real id from now on. Not measured here: the live admission counters would show fewer principal-mismatch findings from promotion posts.
- **L8. Delivery: the promoting agent is no longer told of its own promotion DM (the second visible effect).** `WardRoomRouter.find_targets_for_agent` picks a DM's recipients as the first live crew agent whose id differs from the author's and whose first 8 characters are in the channel name (`ward_room_router.py:1022-1035`; the Captain-post form, `:986-995`, takes every such agent). A promotion DM authored by a type string excluded nobody, so an agent of the poster's type (the poster itself when alone, or an earlier-registered peer) was routed the thread as a notification and could answer it; authored by its id, the poster is dropped. Where there is no same-type peer, nobody is routed (the approver is a name, not an agent id: L3); a same-type peer, if any, is still routed (the name carries 8 characters: L2). B3 pins this at target selection only: it does not run `route_event`, the agent's handler or a model call. Not measured: how often the old self-delivery produced a reply (a live question; the log is the source).

## 11. Verified Against Codebase (2026-11-13, reading tree `D:\ProbOS-worktrees\bf930-932-build` at `b83ed1e3`; `origin/main` `4d8c51e4`)

**Run by the Architect, read-only (ripgrep, git, `gh`, CPython scripts piped on stdin with `-B`; nothing written but these answer files; no pytest, no build):**

```
git -C D:\ProbOS-worktrees\bf930-932-build log -1 --format='%H %s' -> b83ed1e347e1f5303b71cd21f4920a63065d59c0 "BF-932 S2 R1: ..."; git status --short | Measure-Object -> Count 0; git rev-parse origin/main -> 4d8c51e4035d71660f0432b17083168050a1304e; git diff --stat origin/main HEAD -- src/probos/cognitive/cognitive_agent.py -> 12 insertions(+), hunks at :7607, :7608, :7613
every SEARCH of section 7 (9, python on `git show <ref>:<path>` with CRLF removed from the answer file): on HEAD and on origin/main each occurrences=1, line-start=True, ascii=True; the two SEARCHes of the new test file occur once in block N1-1; "PROBLEMS: 0"
in-memory apply of all blocks on both refs: patched cognitive_agent.py, the new test file after M2 and the patched teaching test compile (syntax only; nothing executed); the new test file has no `os` import or use after M2; max line length 119; ASCII
AST count of getattr/hasattr guards with a literal name in cognitive_agent.py: 607 before, 603 after; removed ('getattr','_callsign') x2 and ('getattr','_agent_id') x2; added none
allow-list after P2-3: 23 entries -> 22; the cognitive_agent.py `_callsign` entry gone; the communication_benchmarks.py `_callsign` entry kept
AST scan of src/probos for CognitiveAgent subclasses with a literal `agent_type`: 40; fewer than 8 characters: 8 (builder, news, outlook, scout, surgeon, teams, weather, yeoman: code identifiers, not callsigns); 8 or more: 32 (e.g. architect, backend_swe, calculator, calendar, code_reviewer, cognitive)
Test-Path prompts/promotion-post-identity-reads.md, tests/test_promotion_post_identity.py -> False, False
git rev-parse <ref>:<path> for the 14 files of the header; tracker anchors: DECISIONS heading once (line 1748 / 1764), PROGRESS title + blank line once, both refs, ASCII, no CR
d:/ProbOS/.venv/Scripts/python.exe scripts/ad_ceiling.py -> exit 0; AD-1359 (git log --all, GitHub issue titles); AD-1350 (prompts); NEXT AD-1360
BF enumeration (python: git log --all subjects; gh issue list --state all --limit 4000; prompts/bf-*.md; roadmap.md) -> 961 / 961 (1,517 issues, not truncated) / 941 / 927; BF-954's title holder: #1754
gh issue view / gh api: #1754 OPEN, body 256,104 chars, D5-R1 line `- [ ] [#1604] **D5-R1`; #1523 OPEN, comment 6402853183 holds `- [ ] **F-528.` and `- [ ] **F-529.` (both unticked; the issue body has neither)
```

**Facts read (path:line on `b83ed1e3`; the reads are on the same lines on `origin/main`).** `cognitive/cognitive_agent.py`: `:2781-2788` (`_DEPARTMENT_CHIEFS`), `:2790-2807` (`_request_procedure_promotion`; `:2798` the announcement; `:2805-2806` the swallow), `:2809-2828` (`_route_promotion_approval`), `:2830-2911` (`_announce_promotion_request`: `:2857-2860` the reads, `:2879-2885` the channel thread, `:2888` `approver_id = approver`, `:2896-2906` the DM and its thread, `:2910-2911` the swallow), `:2917-3013` (`_teach_procedure`: `:2957-2961` the trust read by `self.id` with BF-263's comment, `:2979-2980` the reads, `:2995-3005` the DM and its thread, `:3011-3013` the swallow), `:7958-7962` (the trigger), `:8348-8360` (`_resolve_callsign`), `:6189`, `:6191`, `:6349`, `:6351` (the observation keys). `substrate/agent.py:39` (`callsign: str = ""`), `:42` (`self.id`); `substrate/identity.py:17-27`; `substrate/pool.py:529-535`, `:616-622`; `substrate/spawner.py:38-47`; `agent_onboarding.py:189-194`, `:301`, `:320`; `runtime.py:2680-2681`. `ward_room/channels.py:21-30` (the name), `:147-181` (`list_channels`), `:243-288` (the DM: found `:252-263`, `created_by` `:271`, shadow `:274`, subscribe `:284-286`); `ward_room/service.py:316-322`, `:423-431` (shadow `:428`), `:503-505`, `:526-528`; `ward_room/threads.py:242-271` (`list_threads`), `:428-433`, `:449-459`, `:492-498`, `:574-620`; `ward_room/messages.py:70-93` (`set_restriction`), `:428-432`, `:773-784`, `:814-825`; `cognitive/social_memory.py:112-117`; `cognitive/counselor.py:2341-2354` (the precedent: a `CognitiveAgent`'s DM with `self.id` and `self.callsign`); `admission/seam.py:60-64` (`check_at`: an exact `AdmissionService` only); `visiting_officers.py:311-337`, `:380-394` ("a crew member's slot id, the Captain or the system passes without a lookup"); `startup/finalize.py:5584` (the router is built in production) and `:5603-5630` (the Ward Room's events reach it). `ward_room_router.py:425-427` (`author_id`, `is_agent_post`), `:494-498` (`find_targets_for_agent`), `:642-656` (the per-target gate and the shadow decision), `:986-995` and `:1022-1035` (the DM recipients); `tests/test_ad621_channel_visibility.py:41-90` (the router's doubles); `substrate/agent.py:107-109` (`is_alive`). Tests: `tests/test_teaching_protocol.py:63-96` (the double: `:80-81`, `:94-95`), `:99-123`, `:126-245`; `tests/test_promotion_routing.py:12-29`, `:31-89`; `tests/test_bf925_guard_names.py:149-165`, `:168-181`, `:193-197`; `tests/fixtures/guard_name_allowlist.txt:1-8`, `:13`, `:15`; `tests/test_ward_room.py:18-32` (the fixture); `scripts/gen_ad_ledger.py:113`, `:153-173`, `:209-211`, `:281-343`; `scripts/ad_ceiling.py` (`_AD_RE`); `pyproject.toml:180-196` (`asyncio_mode = "auto"`, `timeout = 180`, `addopts = "-n 16 --dist=loadfile"`); `docs/development/architecture-baseline.yaml:408` (`CognitiveAgent` frozen by triggers, never by magnitude). Installed (metadata only): pytest 9.0.2, pytest-asyncio 1.3.0, pytest-xdist 3.8.0; pytest-randomly is not installed (`-p no:randomly` is a no-op).

**Absence Verified (2026-11-13)**

```
CLAIM: nothing sets `_agent_id` or `_callsign` on a CognitiveAgent
RUN:   python AST scan of every .py under src/probos: assignments (Assign, AnnAssign, AugAssign) to <expr>._agent_id / ._callsign, class-level assignments, def/property with those names, setattr(..., "<name>", ...) literals, and the 12 setattr sites with a dynamic name (read one by one); rg -n "__dict__\[|__dict__\.update|vars\(.*\)\.update|__slots__" src/probos
FOUND: `_callsign`: nothing of any shape. `_agent_id`: 18 `self._agent_id = ...` in PlanModeReplyGate, ConcurrencyManager, DreamingEngine, MCPDispatchOffer, AgentCognitiveQueue, RetroactiveEvolver, TierAuditSink, TierChoiceController, ToolManifestOffer, TurnCostBudget, _OwnershipLease, OnDemandPromotion, PromotedTurnContinuations, PerceptionModeController, VisionWorkingMemory, _DmSamplingGuard, BrowserSession, UrlRouteGuard; none descends from BaseAgent or CognitiveAgent by name; the 12 dynamic setattr receivers are a build, a chain-tuning config (two), a result, a report, a cleaned config, a task, a config parent, the runtime (three) and a pydantic model; the only `__slots__` naming `_agent_id` is MCPDispatchOffer's
POSITIVE CONTROL: the same scan on `callsign` finds `CognitiveAgent._resolve_callsign` (`self.callsign = cert.callsign`, cognitive_agent.py:8358), `AgentOnboardingService.wire_agent` (`agent.callsign = ...`, agent_onboarding.py:194, :301, :320) and 34 class-level `callsign` attributes; the `_agent_id` rows above are what the scan returns for a name that is assigned
HOLDS: yes

CLAIM: CognitiveAgent._teach_procedure has no production caller
RUN:   rg -n "_teach_procedure" src tests scripts docs config; rg -n "teach_procedure" src
FOUND: cognitive_agent.py:2917 (the def); commands_procedure.py:62 (a call) and :381 (the def) of a module function of the same name (posts as "captain"); routers/procedures.py:150 (a route function `teach_procedure`, posts as "captain"); tests/test_teaching_protocol.py: 7 calls (:135, :150, :162, :173, :187, :197, :210)
POSITIVE CONTROL: the pattern finds the def, the shell function and the seven test calls
HOLDS: yes (no `.teach`-style call on an agent; no getattr or string use: the bare-name pattern would match it)

CLAIM: _announce_promotion_request and _request_procedure_promotion have no test
RUN:   rg -n "_announce_promotion_request" src tests scripts docs config; rg -n "_request_procedure_promotion" src tests scripts; a grep of tests for "_announce_promotion|_teach_procedure|_request_procedure_promotion"
FOUND: src: cognitive_agent.py:2798, :2830 and :2790, :7962; docs/development/roadmap-era-5-completed.md:944 (prose); tests: only the seven teaching calls above
POSITIVE CONTROL: the same commands find the defs and callers in src
HOLDS: yes

CLAIM: no production code sets a posting restriction, so the author-keyed restriction check cannot refuse a post the old reads let through
RUN:   rg -n "set_restriction\(" src tests --glob '*.py'; rg -n "restrictions" src/probos --glob '*.py'
FOUND: messages.py:70 (the def) and tests/test_ad529_contagion_firewall.py (:323, :351, with prose at :310, :440); counselor.py:1664-1667 says no automatic quarantine applies a restriction and "nothing lifts it"; the other `restrictions` hits are the credibility reads and unrelated tool-permission grants
POSITIVE CONTROL: the pattern finds the def and the test callers
HOLDS: yes, today (L5)

CLAIM: no test or fixture other than the guard allow-list pins the two reads, and no other file pins the guard
RUN:   a grep of tests for the literal read text and for "_agent_id\", agent_type|_callsign\", agent_type"; a grep of tests/fixtures for "cognitive_agent\.py"; rg -n "\b_callsign\b" docs scripts config .github
FOUND: no test holds the read text; the `"_agent_id"` and `"_callsign"` literals in tests are observation dict keys (64 lines, none a `getattr`); tests/fixtures: guard_name_allowlist.txt:13 and the AD-1343 seam registry (scopes `handle_intent`, `handle_consultation_request`, `_run_agentic_dispatch`, `_maybe_run_conversational_agentic`, `recover_promoted_turn`: none a promotion method); docs: two prose lines about the observation keys (`roadmap-era-5-completed.md:5488`, `:7190`)
POSITIVE CONTROL: the fixtures grep finds the allow-list line that blocks M2, which the earlier consult did not know
HOLDS: yes (P2-3 is the one required edit outside the two methods)
```

## 12. Prior Art and Blind Spots

- **Internal prior art, adopted.** BF-263 fixed the same shape in the same two methods' neighbours ("Use `self.id`, not `agent_type`", `:2960-2961`, `:6158-6160`); BF-925's guard-name scan is what recorded F-529 as a finding, and its two-direction check is why P2-3 exists; AD-1229's `dm_channel_name` docstring states the 8-character sharing that L2 records; the AD-1346 M3e4d5 shadow checks are the consumer the recorder reads; BF-182 (the observation keys that the two methods mistook for attributes); BF-101's resolver (rejected, D2); BF-903's guard (passes a slot id). The BF-930/932 contract's format lessons (sections 15 and 16 there): one fence per new file, full paths in label lines, cases that fail at an assert, expected counts, an unused import removed in the same milestone (P2-6). **External:** none consulted.
- **Blind spots handled.** (1) Both methods swallow every error, so a test that asserts "no exception" proves nothing: the cases read stored rows. (2) A type of 8 or more characters gives the same channel name, so a test with `test-id` cannot see the channel effects: K3a and K3b use the production id shape. (3) The class default `callsign = ""` defeats `getattr(self, "callsign", type)`: why D2 option 3 is wrong. (4) The base's `_agent_id` is "defined" by 18 helper classes, so the guard scan never listed it, which is why only `_callsign` had an allow-list entry. (5) `check_at` is imported by name into two modules, so the recorder patches both. (6) The author id has readers beyond the four named (L7). (7) The working copies are CRLF and the tool writes CRLF: the SEARCHes were checked with CRLF removed. (8) A test double that sets an attribute the class lacks hides the defect: the double loses its two lines, and the comment says why. (9) The router drops the author by id and picks a DM's recipients by the channel name's 8-character prefix, so a test that stops at the stored row cannot see who is told: B3.
- **What discards a correct result** (asked separately from what makes a post fail). The correct id and callsign are written, then (a) the found-channel return discards the correct creator and membership of the call for an existing channel (L1); (b) the 8-character name makes a second agent of the type post into the first one's channel without being added (L2); (c) both swallow arms drop a correct failure signal below INFO (L5); (d) the department thread falls to the first channel when the department id does not equal a capitalized channel name (F-528's text; not asserted); (e) the shadow check and the ledger-style counters only count; (f) `find_targets_for_agent` breaks after the first matching agent, so at most one same-type peer is told. **Recorded:** L1 to L8.

## Batching

**One pull request, one broad gate, after BF-930/932 and #1769 have merged.**

| Point | Judgement |
|---|---|
| Files | `cognitive_agent.py`, three test-side files, the two trackers and the ledger pair; disjoint from #1769; BF-930/932 touches `cognitive_agent.py` after our lines (re-run the nine occurrence checks) |
| Order | M1, M2, M3; each M3 line of the trackers lands after the earlier batches' entries |
| Revert | Separate commits per milestone: M3, then M2, then M1; nothing is stored by the change, and rows written meanwhile stay valid |
| Cost: Python | G1 and G2 files at `-n 0`; once, mine: the mutation rows and `PY scripts/run_test_gate.py --label promotion-post-identity --receipt logs/gates/promotion-post-identity.receipt.json` |
| Cost: config, UI | None |

**What the rest wait for.** F-528 (a chief resolver; approval-routing design) and the channel granularity (L2) wait for a design item; neither blocks this slice.

## Not in this issue: for the Captain

None of this slice needs a decision, and nothing needs the vessel to be stopped by hand beyond the restart every merge needs.

1. **Nothing to deploy, migrate or configure.** No config key, no schema change, no data migration; existing DM channels are left as they are (L1).
2. **An optional look, with no deadline.** A promotion request fires only when a procedure reaches the promotion level after enough consecutive successes (`:7958-7962`; `PROMOTION_MIN_COMPILATION_LEVEL` 4, status `private`), so it cannot be forced. After the next one, read the thread in the ship channel or the department channel and the DM: its author is the agent's own callsign (not its type), the promoting agent itself should no longer appear as a recipient of (and so no longer reply in) its own Promotion Review thread, and for an agent whose type has fewer than 8 characters a new DM channel appears beside the old one. Source of truth: the Ward Room. Pass: the author reads as the agent. Not a gate of this slice.
3. **For the orchestrator, not the Captain:** after the merge, tick D5-R1 in #1754 and F-529 in #1523 (comment `6402853183`), and post the two comments of D5 (the lines each parent gets), naming the sibling at `communication_benchmarks.py:286` and leaving F-528 open.

| Data (later) | Chooses |
|---|---|
| Two agents of one type posting into one promotion DM channel, or a same-type peer told of a promotion DM | the channel's granularity (L2, L8): a naming change in `dm_channel_name`, its own design item |
| A chief's DM that nobody reads | F-528's resolver: the approver's registered agent id in place of its key |
| A restricted agent whose promotion request vanishes | L5: log the refusal above DEBUG |

## 13. Diff Reviewer: properties to verify

1. `cognitive_agent.py`: the diff is four changed lines in two methods and nothing else, and it is line-neutral (5 lines for 5 in `_announce_promotion_request`, 4 for 4 in `_teach_procedure`, so no later anchor moves); no `getattr` or `hasattr` is added; `agent_type` is defined before its use in both methods (`:2858`, `:2957`); the second arguments, the channel logic and both swallow arms are byte-identical.
2. The allow-list: exactly one entry removed (the `cognitive_agent.py` `_callsign` one), the `communication_benchmarks.py` entry kept, one comment line added; `tests/test_bf925_guard_names.py` passes.
3. The new test file: ASCII; no crew name, thread id, timestamp or live count (fixtures are `test-id`, `test-agent`, `t-agent`, `test-callsign`, `test-peer`); after M2 no `os` import and a no-op `built`; no module-level state; each case has its own temporary database; the `check_at` patches are `monkeypatch`; no built case can fail anywhere but at an `assert` (read the six: no index or unpack before its guard).
4. `tests/test_teaching_protocol.py`: only the two attribute lines gone and a comment added; its 8 cases are unchanged.
5. Public text: no tracker line and no commit subject holds an `AD-` or `BF-` token or a name; no `Closes`; each M3 body ends with its `Refs` lines.
6. The tracker sentence about the one behaviour change matches L1 and L8 and the cases K3a, K3b and B3.

## 14. Acceptance criteria

1. G1, G2 and G3 pass as stated in section 4; the mutation rows and the broad gate pass.
2. A promotion request and a taught procedure post, open their DM channel and subscribe under the agent's own id (B1), sign with its callsign (B2) and fall back to the type only for an agent with no callsign (K1); the router no longer picks the promoting agent as its own DM's recipient (B3).
3. The second member of each DM is unchanged (K2); a channel opened under the old reads behaves as D4 states (K3a, K3b).
4. `tests/test_bf925_guard_names.py` passes with the entry removed; no other test or fixture pinned the old reads.
5. Neither parent is closed; D5-R1 and F-529 are ticked and each parent has its comment; F-528 and the sibling are recorded.
6. No config key is added; the AD ledger pair is the only generated artifact; no AD or BF number moves.
7. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 15. Amendment A1 (2026-11-13): the oracle's measurements and one corrected cell

The orchestrator applied every block of section 7 by tool to a scratch tree (the oracle: the merge base of BF-930/932 plus the #1769 batch through its slice 2 M3; every SEARCH occurred exactly once, at a line start) and measured the gates and the mutation rows. Where sections 4, 6 and 9 say "expected" or "not measured", this section holds the measurement. Nothing in sections 1 to 8 changes; the only corrected cell is row 7's. The real build's base is `origin/main` after #1769 has merged: every code blob listed in the header (and `cognitive_agent.py` at `2c2f3ee2`) is equal on that base, and the two trackers are at the blobs the #1769 batch leaves.

**Measured.** M0 (before M1): the 10 existing files of the two G2 commands collect 236 tests (the new file is not in the tree yet). G1 at M1: `14 passed, 6 xfailed`; with `PROMOTION_POST_RUNXFAIL=1` (the new file alone): `6 failed, 6 passed`, every failure at an `assert` (no failure line names another exception). G2 at M2: command 1 (4 files) `44 passed` (the new file's 12 and the other files' 32), command 2 (7 files) `204 passed`; the architecture check passes (`srp-size=92, layer-import=0, db-connect=30, unowned-task=13`); 248 tests collected over the 11 files (236 + 12), every file of the old list with the same count. G3: `AD/BF ledger is current`, `tests/test_ad1184_ad_ledger.py` 33 passed, and no AD or BF number moves. **Wide consumer run** (22 test files that name an edited module and are in no G2 command, `-n 4`): `976 passed, 0 failed`. **Blobs after M2** (the LF blobs the real build equals): `src/probos/cognitive/cognitive_agent.py` `584cc9704978e5d5800f4ff9ef02ad5eb5484146`, `tests/test_teaching_protocol.py` `adb8f23fc8e2c3f21e46b571df496444bf131c8e`, `tests/fixtures/guard_name_allowlist.txt` `dda7aa0b0ff174fa1674b2b59b38bc4ede5f39c2`, `tests/test_promotion_post_identity.py` `b45949ea9d26ef7f4052470073e9ee27e0773cb7` (at M1: `7f735feba19e465574ed99e615b07f84921968d2`).

**Mutation rows.** Each row's line was replaced whole in the built file, the new test file run with the named existing test, the file restored and its blob checked: 14 runs (rows 1 to 11, and row 12 as 12a, 12b and 12c, that is rows 4 to 6 with the teaching test's old double, as the row's text says). 13 match the cells of section 9 exactly. **Row 7** (`approver_id = agent_type`) is also killed by K3a (three failures: K2 (captain-approver), K2 (department-chief-approver) and K3a): the channel's name is computed from the agent's id and the approver, so the mutant changes the name, the channel opened under the old reads is not found and a second DM opens. Row 7's cell above now lists K3a. These results are for a tree whose files equal the blobs above.
