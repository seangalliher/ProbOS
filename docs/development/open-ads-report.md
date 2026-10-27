# ProbOS — Reconciled AD/BF Ledger

**Generated file — do not edit by hand.**
Regenerate with `python scripts/gen_ad_ledger.py` (add `--online` to refresh the
GitHub issue layer). The generator is `scripts/gen_ad_ledger.py`; the pinned
snapshot is `docs/development/ad-ledger-snapshot.json`.

This replaces a hand-made 2026-03-31 snapshot that had been stale for months.

**Read the ceiling here, not from a tree scan.** AD and BF numbers are minted by
audits and reviews that file a GitHub issue *before* any code exists. A
recursive scan of the working tree therefore reports a ceiling that is already
too low, and reports intentionally-allocated numbers as free. That is how
collisions happen.

**No number below the ceiling is free merely because this file does not account
for it.** Gaps are listed as *unaccounted*, which means the four authorities are
silent — not that the number may be reused. Refresh the issue layer and check
`gh issue list --search "AD-NNNN in:title" --state all` before minting.

This file **observes** the ledger. It does not correct it: nothing is renumbered
or retired here, and disagreements between the authorities are reported below
rather than resolved.

## Ceilings

Derived from all four authorities. A tree scan sees only the numbers that reached code, so it reports a lower ceiling than this.

| Series | Highest allocated | Next free | Highest with code | Allocated above the code ceiling |
|---|---|---|---|---|
| AD | **AD-1350** | **AD-1351** | AD-1350 | _(none)_ |
| BF | **BF-939** | **BF-940** | BF-939 | _(none)_ |

## Where each layer came from

| Authority | Availability | Captured | Extent |
|---|---|---|---|
| `git log` commit subjects | pinned snapshot | 2026-10-27T19:53:12+00:00 at `81c99ea6` | 3455 subjects, 1047 numbers |
| `DECISIONS.md, decisions-era-1-genesis.md, decisions-era-2-emergence.md, decisions-era-3-product.md, decisions-era-4-evolution.md, decisions-era-5-unification.md` | live, every run | at check time | AD/BF entry headings |
| `PROGRESS.md, progress-era-1-genesis.md, progress-era-2-emergence.md, progress-era-3-product.md, progress-era-4-evolution.md, progress-era-5-unification.md` | live, every run | at check time | AD/BF status head lines |
| `gh issue list --state all` | pinned snapshot (network) | 2026-10-12T09:12:39+00:00 | 1410 issues, 971 numbers |

The two pinned layers are refreshed by running the generator (`--online` for issues). `--check` re-renders from the pinned snapshot and a fresh parse of the two live authorities, so it opens no socket and spawns no subprocess.

## Lifecycle

| State | AD | BF | Meaning |
|---|---|---|---|
| `allocated-open` | 51 | 9 | assigned, issue open, no shipped code |
| `deferred` | 0 | 0 | assigned, explicitly postponed |
| `superseded` | 1 | 0 | replaced by a later number |
| `retired` | 10 | 0 | abandoned, number **not** reusable |
| `shipped` | 1002 | 587 | code in history |

## Allocated and open — **do not reuse these numbers**

60 numbers. Every one is assigned. A recursive tree scan reports the ones without code as free.

| Number | Issue | Why | Title |
|---|---|---|---|
| `AD-1319` | [#1464](https://github.com/seangalliher/ProbOS/issues/1464) | issue #1464 open, no code | AD-1319: Ship View - state-bound 3D projection of the live mesh (child of AD-1307) |
| `AD-1313` | [#1365](https://github.com/seangalliher/ProbOS/issues/1365) | issue #1365 open, no code | AD-1313: Authentic digital visual language and spatial continuity for HXI work |
| `AD-1312` | [#1366](https://github.com/seangalliher/ProbOS/issues/1366) | issue #1366 open, no code | AD-1312: Contextual crew, knowledge, and administration experience |
| `AD-1311` | [#1364](https://github.com/seangalliher/ProbOS/issues/1364) | issue #1364 open, no code | AD-1311: Embodied co-presence and explicit multimodal session controls |
| `AD-1310` | [#1361](https://github.com/seangalliher/ProbOS/issues/1361) | issue #1361 open, no code | AD-1310: Shared evidence and artifact handback on the collaboration canvas |
| `AD-1309` | [#1362](https://github.com/seangalliher/ProbOS/issues/1362) | issue #1362 open, no code | AD-1309: Progressive collaboration intake and explicit conversation context |
| `AD-1308` | [#1363](https://github.com/seangalliher/ProbOS/issues/1363) | issue #1363 open, no code | AD-1308: Spatial workspace host and semantic navigation across HXI views |
| `AD-1307` | [#1360](https://github.com/seangalliher/ProbOS/issues/1360), [#1464](https://github.com/seangalliher/ProbOS/issues/1464) | issue #1360, #1464 open, no code | AD-1307: HXI spatial collaboration program - crew-first workspace and release contract |
| `AD-1290` | [#1337](https://github.com/seangalliher/ProbOS/issues/1337) | issue #1337 open, no code | AD-1290: Elastic Scatter/Gather and Team Trials |
| `AD-1289` | [#1336](https://github.com/seangalliher/ProbOS/issues/1336) | issue #1336 open, no code | AD-1289: Typed Mission Blackboard |
| `AD-1225` | [#1193](https://github.com/seangalliher/ProbOS/issues/1193) | issue #1193 open, no code | AD-1225: an agent pays a full ~18K-token prompt to decide to say nothing |
| `AD-1202` | [#1142](https://github.com/seangalliher/ProbOS/issues/1142) | issue #1142 open, no code | AD-1202: Shared HXI controls - glass material, contextual behavior, and a complete Bridge exemplar |
| `AD-1199` | [#1136](https://github.com/seangalliher/ProbOS/issues/1136) | issue #1136 open, no code | AD-1199: a typed human-claim lifecycle |
| `AD-1193` | [#1130](https://github.com/seangalliher/ProbOS/issues/1130) | issue #1130 open, no code | AD-1193: conversational streaming |
| `AD-1186` | [#1123](https://github.com/seangalliher/ProbOS/issues/1123), [#1138](https://github.com/seangalliher/ProbOS/issues/1138) | issue #1123, #1138 open, no code | AD-1186: Ship Trials -- a release catalog and policy over the existing evaluators |
| `AD-1136` | [#1055](https://github.com/seangalliher/ProbOS/issues/1055) | issue #1055 open, no code | AD-1136: First-class chat channel adapter (finish Discord/Slack gateway) (Phase 24) |
| `AD-1134` | [#1053](https://github.com/seangalliher/ProbOS/issues/1053) | issue #1053 open, no code | AD-1134: PyPI release + lightweight install path (Phase 35) |
| `AD-703` | [#479](https://github.com/seangalliher/ProbOS/issues/479) | issue #479 open, no code | AD-703: Starfleet Command — fleet-wide policy distribution across instances |
| `AD-392` | — | mentioned by an authority, no code and no closure |  |
| `AD-391` | — | mentioned by an authority, no code and no closure |  |
| `AD-390` | — | mentioned by an authority, no code and no closure |  |
| `AD-389` | — | mentioned by an authority, no code and no closure |  |
| `AD-375` | — | mentioned by an authority, no code and no closure |  |
| `AD-347` | — | a tracker head marks it open |  |
| `AD-346` | — | mentioned by an authority, no code and no closure |  |
| `AD-345` | — | mentioned by an authority, no code and no closure |  |
| `AD-344` | — | mentioned by an authority, no code and no closure |  |
| `AD-343` | — | mentioned by an authority, no code and no closure |  |
| `AD-342` | — | mentioned by an authority, no code and no closure |  |
| `AD-341` | — | mentioned by an authority, no code and no closure |  |
| `AD-340` | — | mentioned by an authority, no code and no closure |  |
| `AD-339` | — | mentioned by an authority, no code and no closure |  |
| `AD-338` | — | mentioned by an authority, no code and no closure |  |
| `AD-337` | — | mentioned by an authority, no code and no closure |  |
| `AD-323` | — | mentioned by an authority, no code and no closure |  |
| `AD-320` | — | mentioned by an authority, no code and no closure |  |
| `AD-319` | — | mentioned by an authority, no code and no closure |  |
| `AD-318` | — | mentioned by an authority, no code and no closure |  |
| `AD-315` | — | mentioned by an authority, no code and no closure |  |
| `AD-312` | — | mentioned by an authority, no code and no closure |  |
| `AD-309` | — | mentioned by an authority, no code and no closure |  |
| `AD-308` | — | mentioned by an authority, no code and no closure |  |
| `AD-305` | — | mentioned by an authority, no code and no closure |  |
| `AD-304` | — | mentioned by an authority, no code and no closure |  |
| `AD-284` | — | mentioned by an authority, no code and no closure |  |
| `AD-283` | — | mentioned by an authority, no code and no closure |  |
| `AD-282` | — | mentioned by an authority, no code and no closure |  |
| `AD-281` | — | mentioned by an authority, no code and no closure |  |
| `AD-277` | — | mentioned by an authority, no code and no closure |  |
| `AD-276` | — | mentioned by an authority, no code and no closure |  |
| `AD-274` | — | mentioned by an authority, no code and no closure |  |
| `BF-891` | — | mentioned by an authority, no code and no closure |  |
| `BF-888` | — | a tracker head marks it open |  |
| `BF-887` | — | a tracker head marks it open |  |
| `BF-885` | — | a tracker head marks it open |  |
| `BF-882` | — | a tracker head marks it open |  |
| `BF-881` | — | a tracker head marks it open |  |
| `BF-880` | — | a tracker head marks it open |  |
| `BF-7` | — | mentioned by an authority, no code and no closure |  |
| `BF-5` | — | mentioned by an authority, no code and no closure |  |

## Deferred

_(none)_

## Superseded

| Number | Issue | Why | Title |
|---|---|---|---|
| `AD-705` | [#481](https://github.com/seangalliher/ProbOS/issues/481), [#523](https://github.com/seangalliher/ProbOS/issues/523), [#554](https://github.com/seangalliher/ProbOS/issues/554), [#555](https://github.com/seangalliher/ProbOS/issues/555), [#556](https://github.com/seangalliher/ProbOS/issues/556), [#557](https://github.com/seangalliher/ProbOS/issues/557), [#558](https://github.com/seangalliher/ProbOS/issues/558) | a tracker head marks it superseded | AD-705: Voice Stack Backends — Whisper STT, Deepgram STT, Coqui/Piper TTS, Porcupine wake word |

## Retired — **never reusable**

| Number | Issue | Why | Title |
|---|---|---|---|
| `AD-1318` | [#1382](https://github.com/seangalliher/ProbOS/issues/1382) | issue #1382 closed as not planned, no code | AD-1318: Optional VS Code surface and Copilot-assisted strong-harness interoperability |
| `AD-1317` | [#1380](https://github.com/seangalliher/ProbOS/issues/1380) | issue #1380 closed as not planned, no code | AD-1317: Strong Supervised Worker host adapter and immutable restart recovery |
| `AD-1314` | [#1379](https://github.com/seangalliher/ProbOS/issues/1379) | issue #1379 closed as not planned, no code | AD-1314: ProbOS-hosted strong supervision harness program |
| `AD-1188` | [#1125](https://github.com/seangalliher/ProbOS/issues/1125) | issue #1125 closed as not planned, no code | AD-1188: orchestration-mode ablation rig |
| `AD-1150` | [#1068](https://github.com/seangalliher/ProbOS/issues/1068), [#1075](https://github.com/seangalliher/ProbOS/issues/1075), [#1083](https://github.com/seangalliher/ProbOS/issues/1083) | issue #1075 closed as not planned, no code | Epic: Agentic harness parity — loop conversation mechanics (AD-1146..AD-1150) |
| `AD-1149` | [#1074](https://github.com/seangalliher/ProbOS/issues/1074) | issue #1074 closed as not planned, no code | AD-1149: Prompt caching / stable prefix reuse |
| `AD-842` | [#817](https://github.com/seangalliher/ProbOS/issues/817), [#821](https://github.com/seangalliher/ProbOS/issues/821) | issue #821 closed as not planned, no code | AD-842: Per-agent tool grants in the ACM profile |
| `AD-840` | [#815](https://github.com/seangalliher/ProbOS/issues/815), [#819](https://github.com/seangalliher/ProbOS/issues/819) | issue #819 closed as not planned, no code | AD-840: HXI Skill Registry + per-agent ACM skill-assignment surface |
| `AD-709` | [#485](https://github.com/seangalliher/ProbOS/issues/485) | issue #485 closed as not planned, no code | AD-709: MemoryForge — implanted birth memories + curated memory banks (Long Horizon) |
| `AD-693` | [#387](https://github.com/seangalliher/ProbOS/issues/387) | issue #387 closed as not planned, no code | AD-693: Federation Knowledge Sync |

## Shipped

**AD** (1002): 1, 19-139, 142-153, 228, 262-273, 293-300, 302, 311, 313-314, 316-317, 321-322, 324, 348-355, 357-373, 376-388, 393-419, 423-502, 507-530, 532, 534, 538-541, 543, 550-554, 556-558, 560-577, 579-623, 625-680, 682-683, 685-692, 694-702, 704, 706-708, 710-766, 790-813, 815-828, 832-839, 841, 843, 845-847, 853-956, 958-966, 972, 975-1019, 1021-1038, 1040-1055, 1065, 1068-1089, 1091-1095, 1119-1133, 1135, 1137-1148, 1151-1185, 1187, 1189-1192, 1194-1198, 1200-1201, 1203-1224, 1226-1236, 1239-1248, 1250-1251, 1256-1261, 1265, 1267, 1269-1271, 1273-1288, 1291-1306, 1315-1316, 1320-1328, 1336, 1340-1341, 1343-1344, 1346-1347, 1349-1350

**BF** (587): 4, 6, 8-13, 23-25, 27, 29-37, 39-41, 43-44, 49, 53, 57-60, 63-69, 71, 76, 78-80, 82-86, 99-104, 106, 108-116, 118, 123-175, 177-179, 183-201, 203-204, 206-219, 222-326, 331-332, 597-680, 682-879, 883-884, 886, 889-890, 892-898, 900-927, 939

## Unaccounted — silent, **not** free

Numbers below the ceiling that no authority mentions. The issue layer is a snapshot and audits allocate before writing code, so silence here is absence of evidence. Confirm against live issues before minting.

**AD** (286): 2-18, 140-141, 154-227, 229-261, 275, 278-280, 285-292, 301, 303, 306-307, 310, 325-336, 356, 374, 420-422, 503-506, 531, 533, 535-537, 542, 544-549, 555, 559, 578, 624, 681, 684, 767-789, 814, 829-831, 844, 848-852, 957, 967-971, 973-974, 1020, 1039, 1056-1064, 1066-1067, 1090, 1096-1118, 1237-1238, 1249, 1252-1255, 1262-1264, 1266, 1268, 1272, 1329-1335, 1337-1339, 1342, 1345, 1348

**BF** (343): 1-3, 14-22, 26, 28, 38, 42, 45-48, 50-52, 54-56, 61-62, 70, 72-75, 77, 81, 87-98, 105, 107, 117, 119-122, 176, 180-182, 202, 205, 220-221, 327-330, 333-596, 681, 899, 928-938

## Inconsistencies — reported, deliberately not fixed

This generator observes the ledger; correcting an append-only history is a separate decision for a human.

A *collision* below means two issues each **lead** with the identical number. Sub-allocations that share a base (`AD-423a`, `AD-423b`, `AD-423c`) and epics that name their children in the title are normal and are not counted.

- `AD-443` — collision: 2 issues each lead with this number: [#42](https://github.com/seangalliher/ProbOS/issues/42), [#433](https://github.com/seangalliher/ProbOS/issues/433).
- `AD-473` — collision: 2 issues each lead with this number: [#67](https://github.com/seangalliher/ProbOS/issues/67), [#435](https://github.com/seangalliher/ProbOS/issues/435).
- `AD-474` — collision: 2 issues each lead with this number: [#68](https://github.com/seangalliher/ProbOS/issues/68), [#436](https://github.com/seangalliher/ProbOS/issues/436).
- `AD-482` — collision: 2 issues each lead with this number: [#76](https://github.com/seangalliher/ProbOS/issues/76), [#434](https://github.com/seangalliher/ProbOS/issues/434).
- `AD-529` — collision: 2 issues each lead with this number: [#103](https://github.com/seangalliher/ProbOS/issues/103), [#437](https://github.com/seangalliher/ProbOS/issues/437).
- `AD-538b` — collision: 2 issues each lead with this number: [#26](https://github.com/seangalliher/ProbOS/issues/26), [#418](https://github.com/seangalliher/ProbOS/issues/418).
- `AD-539c` — collision: 2 issues each lead with this number: [#106](https://github.com/seangalliher/ProbOS/issues/106), [#454](https://github.com/seangalliher/ProbOS/issues/454).
- `AD-539d` — collision: 2 issues each lead with this number: [#107](https://github.com/seangalliher/ProbOS/issues/107), [#455](https://github.com/seangalliher/ProbOS/issues/455).
- `AD-563` — collision: 2 issues each lead with this number: [#10](https://github.com/seangalliher/ProbOS/issues/10), [#34](https://github.com/seangalliher/ProbOS/issues/34).
- `AD-568a` — collision: 2 issues each lead with this number: [#17](https://github.com/seangalliher/ProbOS/issues/17), [#30](https://github.com/seangalliher/ProbOS/issues/30).
- `AD-572` — collision: 2 issues each lead with this number: [#123](https://github.com/seangalliher/ProbOS/issues/123), [#359](https://github.com/seangalliher/ProbOS/issues/359).
- `AD-574` — collision: 2 issues each lead with this number: [#6](https://github.com/seangalliher/ProbOS/issues/6), [#361](https://github.com/seangalliher/ProbOS/issues/361).
- `AD-580` — collision: 3 issues each lead with this number: [#112](https://github.com/seangalliher/ProbOS/issues/112), [#127](https://github.com/seangalliher/ProbOS/issues/127), [#1143](https://github.com/seangalliher/ProbOS/issues/1143).
- `AD-581` — collision: 2 issues each lead with this number: [#113](https://github.com/seangalliher/ProbOS/issues/113), [#468](https://github.com/seangalliher/ProbOS/issues/468).
- `AD-582` — collision: 2 issues each lead with this number: [#114](https://github.com/seangalliher/ProbOS/issues/114), [#128](https://github.com/seangalliher/ProbOS/issues/128).
- `AD-583f` — collision: 2 issues each lead with this number: [#117](https://github.com/seangalliher/ProbOS/issues/117), [#464](https://github.com/seangalliher/ProbOS/issues/464).
- `AD-589` — collision: 2 issues each lead with this number: [#153](https://github.com/seangalliher/ProbOS/issues/153), [#195](https://github.com/seangalliher/ProbOS/issues/195).
- `AD-594b` — collision: 2 issues each lead with this number: [#161](https://github.com/seangalliher/ProbOS/issues/161), [#472](https://github.com/seangalliher/ProbOS/issues/472).
- `AD-594d` — collision: 2 issues each lead with this number: [#163](https://github.com/seangalliher/ProbOS/issues/163), [#473](https://github.com/seangalliher/ProbOS/issues/473).
- `AD-605` — collision: 3 issues each lead with this number: [#181](https://github.com/seangalliher/ProbOS/issues/181), [#189](https://github.com/seangalliher/ProbOS/issues/189), [#487](https://github.com/seangalliher/ProbOS/issues/487).
- `AD-607` — collision: 2 issues each lead with this number: [#183](https://github.com/seangalliher/ProbOS/issues/183), [#488](https://github.com/seangalliher/ProbOS/issues/488).
- `AD-632d` — collision: 2 issues each lead with this number: [#235](https://github.com/seangalliher/ProbOS/issues/235), [#236](https://github.com/seangalliher/ProbOS/issues/236).
- `AD-632e` — collision: 2 issues each lead with this number: [#239](https://github.com/seangalliher/ProbOS/issues/239), [#240](https://github.com/seangalliher/ProbOS/issues/240).
- `AD-632f` — collision: 2 issues each lead with this number: [#237](https://github.com/seangalliher/ProbOS/issues/237), [#238](https://github.com/seangalliher/ProbOS/issues/238).
- `AD-633` — collision: 2 issues each lead with this number: [#228](https://github.com/seangalliher/ProbOS/issues/228), [#489](https://github.com/seangalliher/ProbOS/issues/489).
- `AD-641` — the trackers disagree: deferred, shipped. Resolved as `shipped`.
- `AD-641g` — collision: 2 issues each lead with this number: [#403](https://github.com/seangalliher/ProbOS/issues/403), [#430](https://github.com/seangalliher/ProbOS/issues/430).
- `AD-654d` — collision: 2 issues each lead with this number: [#326](https://github.com/seangalliher/ProbOS/issues/326), [#333](https://github.com/seangalliher/ProbOS/issues/333).
- `AD-660b` — collision: 2 issues each lead with this number: [#411](https://github.com/seangalliher/ProbOS/issues/411), [#460](https://github.com/seangalliher/ProbOS/issues/460).
- `AD-673` — collision: 2 issues each lead with this number: [#356](https://github.com/seangalliher/ProbOS/issues/356), [#370](https://github.com/seangalliher/ProbOS/issues/370).
- `AD-674` — collision: 2 issues each lead with this number: [#362](https://github.com/seangalliher/ProbOS/issues/362), [#371](https://github.com/seangalliher/ProbOS/issues/371).
- `AD-675` — collision: 2 issues each lead with this number: [#363](https://github.com/seangalliher/ProbOS/issues/363), [#372](https://github.com/seangalliher/ProbOS/issues/372).
- `AD-676` — collision: 2 issues each lead with this number: [#364](https://github.com/seangalliher/ProbOS/issues/364), [#373](https://github.com/seangalliher/ProbOS/issues/373).
- `AD-677` — collision: 2 issues each lead with this number: [#365](https://github.com/seangalliher/ProbOS/issues/365), [#374](https://github.com/seangalliher/ProbOS/issues/374).
- `AD-678` — collision: 2 issues each lead with this number: [#366](https://github.com/seangalliher/ProbOS/issues/366), [#375](https://github.com/seangalliher/ProbOS/issues/375).
- `AD-679` — collision: 2 issues each lead with this number: [#367](https://github.com/seangalliher/ProbOS/issues/367), [#376](https://github.com/seangalliher/ProbOS/issues/376).
- `AD-683` — collision: 2 issues each lead with this number: [#313](https://github.com/seangalliher/ProbOS/issues/313), [#419](https://github.com/seangalliher/ProbOS/issues/419).
- `AD-690` — collision: 3 issues each lead with this number: [#384](https://github.com/seangalliher/ProbOS/issues/384), [#417](https://github.com/seangalliher/ProbOS/issues/417), [#506](https://github.com/seangalliher/ProbOS/issues/506).
- `AD-691` — collision: 2 issues each lead with this number: [#385](https://github.com/seangalliher/ProbOS/issues/385), [#420](https://github.com/seangalliher/ProbOS/issues/420).
- `AD-697` — collision: 3 issues each lead with this number: [#428](https://github.com/seangalliher/ProbOS/issues/428), [#429](https://github.com/seangalliher/ProbOS/issues/429), [#431](https://github.com/seangalliher/ProbOS/issues/431).
- `AD-705` — the trackers disagree: shipped, superseded. Resolved as `superseded`.
- `AD-705a` — collision: 2 issues each lead with this number: [#554](https://github.com/seangalliher/ProbOS/issues/554), [#555](https://github.com/seangalliher/ProbOS/issues/555).
- `AD-706c` — collision: 3 issues each lead with this number: [#518](https://github.com/seangalliher/ProbOS/issues/518), [#642](https://github.com/seangalliher/ProbOS/issues/642), [#643](https://github.com/seangalliher/ProbOS/issues/643).
- `AD-718d` — collision: 2 issues each lead with this number: [#525](https://github.com/seangalliher/ProbOS/issues/525), [#553](https://github.com/seangalliher/ProbOS/issues/553).
- `AD-720a` — collision: 2 issues each lead with this number: [#549](https://github.com/seangalliher/ProbOS/issues/549), [#562](https://github.com/seangalliher/ProbOS/issues/562).
- `AD-720d` — collision: 5 issues each lead with this number: [#552](https://github.com/seangalliher/ProbOS/issues/552), [#563](https://github.com/seangalliher/ProbOS/issues/563), [#564](https://github.com/seangalliher/ProbOS/issues/564), [#565](https://github.com/seangalliher/ProbOS/issues/565), [#645](https://github.com/seangalliher/ProbOS/issues/645).
- `AD-721` — code is in history but [#530](https://github.com/seangalliher/ProbOS/issues/530), [#538](https://github.com/seangalliher/ProbOS/issues/538) is still open.
- `AD-721b` — collision: 6 issues each lead with this number: [#529](https://github.com/seangalliher/ProbOS/issues/529), [#540](https://github.com/seangalliher/ProbOS/issues/540), [#559](https://github.com/seangalliher/ProbOS/issues/559), [#560](https://github.com/seangalliher/ProbOS/issues/560), [#561](https://github.com/seangalliher/ProbOS/issues/561), [#663](https://github.com/seangalliher/ProbOS/issues/663).
- `AD-721d` — collision: 9 issues each lead with this number: [#531](https://github.com/seangalliher/ProbOS/issues/531), [#541](https://github.com/seangalliher/ProbOS/issues/541), [#618](https://github.com/seangalliher/ProbOS/issues/618), [#619](https://github.com/seangalliher/ProbOS/issues/619), [#620](https://github.com/seangalliher/ProbOS/issues/620), [#621](https://github.com/seangalliher/ProbOS/issues/621), [#622](https://github.com/seangalliher/ProbOS/issues/622), [#623](https://github.com/seangalliher/ProbOS/issues/623), [#658](https://github.com/seangalliher/ProbOS/issues/658).
- `AD-721i` — collision: 3 issues each lead with this number: [#537](https://github.com/seangalliher/ProbOS/issues/537), [#542](https://github.com/seangalliher/ProbOS/issues/542), [#543](https://github.com/seangalliher/ProbOS/issues/543).
- `AD-722` — collision: 4 issues each lead with this number: [#544](https://github.com/seangalliher/ProbOS/issues/544), [#545](https://github.com/seangalliher/ProbOS/issues/545), [#572](https://github.com/seangalliher/ProbOS/issues/572), [#578](https://github.com/seangalliher/ProbOS/issues/578).
- `AD-722a` — collision: 15 issues each lead with this number: [#567](https://github.com/seangalliher/ProbOS/issues/567), [#573](https://github.com/seangalliher/ProbOS/issues/573), [#604](https://github.com/seangalliher/ProbOS/issues/604), [#605](https://github.com/seangalliher/ProbOS/issues/605), [#606](https://github.com/seangalliher/ProbOS/issues/606), [#607](https://github.com/seangalliher/ProbOS/issues/607), [#608](https://github.com/seangalliher/ProbOS/issues/608), [#609](https://github.com/seangalliher/ProbOS/issues/609), [#610](https://github.com/seangalliher/ProbOS/issues/610), [#611](https://github.com/seangalliher/ProbOS/issues/611), [#612](https://github.com/seangalliher/ProbOS/issues/612), [#613](https://github.com/seangalliher/ProbOS/issues/613), [#614](https://github.com/seangalliher/ProbOS/issues/614), [#615](https://github.com/seangalliher/ProbOS/issues/615), [#624](https://github.com/seangalliher/ProbOS/issues/624).
- `AD-722b` — collision: 17 issues each lead with this number: [#568](https://github.com/seangalliher/ProbOS/issues/568), [#574](https://github.com/seangalliher/ProbOS/issues/574), [#592](https://github.com/seangalliher/ProbOS/issues/592), [#593](https://github.com/seangalliher/ProbOS/issues/593), [#594](https://github.com/seangalliher/ProbOS/issues/594), [#595](https://github.com/seangalliher/ProbOS/issues/595), [#596](https://github.com/seangalliher/ProbOS/issues/596), [#597](https://github.com/seangalliher/ProbOS/issues/597), [#598](https://github.com/seangalliher/ProbOS/issues/598), [#599](https://github.com/seangalliher/ProbOS/issues/599), [#600](https://github.com/seangalliher/ProbOS/issues/600), [#601](https://github.com/seangalliher/ProbOS/issues/601), [#602](https://github.com/seangalliher/ProbOS/issues/602), [#603](https://github.com/seangalliher/ProbOS/issues/603), [#655](https://github.com/seangalliher/ProbOS/issues/655), [#657](https://github.com/seangalliher/ProbOS/issues/657), [#659](https://github.com/seangalliher/ProbOS/issues/659).
- `AD-722c` — collision: 3 issues each lead with this number: [#569](https://github.com/seangalliher/ProbOS/issues/569), [#575](https://github.com/seangalliher/ProbOS/issues/575), [#654](https://github.com/seangalliher/ProbOS/issues/654).
- `AD-722d` — collision: 2 issues each lead with this number: [#570](https://github.com/seangalliher/ProbOS/issues/570), [#576](https://github.com/seangalliher/ProbOS/issues/576).
- `AD-722e` — collision: 3 issues each lead with this number: [#571](https://github.com/seangalliher/ProbOS/issues/571), [#577](https://github.com/seangalliher/ProbOS/issues/577), [#644](https://github.com/seangalliher/ProbOS/issues/644).
- `AD-722f` — collision: 2 issues each lead with this number: [#579](https://github.com/seangalliher/ProbOS/issues/579), [#580](https://github.com/seangalliher/ProbOS/issues/580).
- `AD-723a` — collision: 4 issues each lead with this number: [#616](https://github.com/seangalliher/ProbOS/issues/616), [#617](https://github.com/seangalliher/ProbOS/issues/617), [#625](https://github.com/seangalliher/ProbOS/issues/625), [#626](https://github.com/seangalliher/ProbOS/issues/626).
- `AD-724` — collision: 5 issues each lead with this number: [#582](https://github.com/seangalliher/ProbOS/issues/582), [#627](https://github.com/seangalliher/ProbOS/issues/627), [#628](https://github.com/seangalliher/ProbOS/issues/628), [#629](https://github.com/seangalliher/ProbOS/issues/629), [#1264](https://github.com/seangalliher/ProbOS/issues/1264).
- `AD-730` — collision: 9 issues each lead with this number: [#630](https://github.com/seangalliher/ProbOS/issues/630), [#631](https://github.com/seangalliher/ProbOS/issues/631), [#632](https://github.com/seangalliher/ProbOS/issues/632), [#633](https://github.com/seangalliher/ProbOS/issues/633), [#634](https://github.com/seangalliher/ProbOS/issues/634), [#635](https://github.com/seangalliher/ProbOS/issues/635), [#646](https://github.com/seangalliher/ProbOS/issues/646), [#647](https://github.com/seangalliher/ProbOS/issues/647), [#656](https://github.com/seangalliher/ProbOS/issues/656).
- `AD-733` — collision: 3 issues each lead with this number: [#641](https://github.com/seangalliher/ProbOS/issues/641), [#667](https://github.com/seangalliher/ProbOS/issues/667), [#668](https://github.com/seangalliher/ProbOS/issues/668).
- `AD-733c` — collision: 4 issues each lead with this number: [#675](https://github.com/seangalliher/ProbOS/issues/675), [#676](https://github.com/seangalliher/ProbOS/issues/676), [#677](https://github.com/seangalliher/ProbOS/issues/677), [#678](https://github.com/seangalliher/ProbOS/issues/678).
- `AD-742a` — collision: 3 issues each lead with this number: [#669](https://github.com/seangalliher/ProbOS/issues/669), [#679](https://github.com/seangalliher/ProbOS/issues/679), [#680](https://github.com/seangalliher/ProbOS/issues/680).
- `AD-749` — collision: 2 issues each lead with this number: [#686](https://github.com/seangalliher/ProbOS/issues/686), [#695](https://github.com/seangalliher/ProbOS/issues/695).
- `AD-750` — collision: 2 issues each lead with this number: [#687](https://github.com/seangalliher/ProbOS/issues/687), [#696](https://github.com/seangalliher/ProbOS/issues/696).
- `AD-752` — collision: 2 issues each lead with this number: [#688](https://github.com/seangalliher/ProbOS/issues/688), [#698](https://github.com/seangalliher/ProbOS/issues/698).
- `AD-753` — collision: 2 issues each lead with this number: [#689](https://github.com/seangalliher/ProbOS/issues/689), [#699](https://github.com/seangalliher/ProbOS/issues/699).
- `AD-754` — collision: 2 issues each lead with this number: [#690](https://github.com/seangalliher/ProbOS/issues/690), [#700](https://github.com/seangalliher/ProbOS/issues/700).
- `AD-755` — collision: 2 issues each lead with this number: [#691](https://github.com/seangalliher/ProbOS/issues/691), [#701](https://github.com/seangalliher/ProbOS/issues/701).
- `AD-756` — collision: 2 issues each lead with this number: [#692](https://github.com/seangalliher/ProbOS/issues/692), [#702](https://github.com/seangalliher/ProbOS/issues/702).
- `AD-757` — collision: 2 issues each lead with this number: [#693](https://github.com/seangalliher/ProbOS/issues/693), [#703](https://github.com/seangalliher/ProbOS/issues/703).
- `AD-758` — collision: 2 issues each lead with this number: [#694](https://github.com/seangalliher/ProbOS/issues/694), [#704](https://github.com/seangalliher/ProbOS/issues/704).
- `AD-817` — collision: 2 issues each lead with this number: [#747](https://github.com/seangalliher/ProbOS/issues/747), [#749](https://github.com/seangalliher/ProbOS/issues/749).
- `AD-819` — collision: 2 issues each lead with this number: [#752](https://github.com/seangalliher/ProbOS/issues/752), [#761](https://github.com/seangalliher/ProbOS/issues/761).
- `AD-820` — collision: 2 issues each lead with this number: [#753](https://github.com/seangalliher/ProbOS/issues/753), [#772](https://github.com/seangalliher/ProbOS/issues/772).
- `AD-822` — the trackers disagree: allocated-open, shipped. Resolved as `shipped`.
- `AD-822` — collision: 2 issues each lead with this number: [#755](https://github.com/seangalliher/ProbOS/issues/755), [#756](https://github.com/seangalliher/ProbOS/issues/756).
- `AD-825` — collision: 3 issues each lead with this number: [#760](https://github.com/seangalliher/ProbOS/issues/760), [#764](https://github.com/seangalliher/ProbOS/issues/764), [#771](https://github.com/seangalliher/ProbOS/issues/771).
- `AD-840` — collision: 2 issues each lead with this number: [#815](https://github.com/seangalliher/ProbOS/issues/815), [#819](https://github.com/seangalliher/ProbOS/issues/819).
- `AD-841` — the trackers disagree: allocated-open, shipped. Resolved as `shipped`.
- `AD-841` — collision: 2 issues each lead with this number: [#816](https://github.com/seangalliher/ProbOS/issues/816), [#820](https://github.com/seangalliher/ProbOS/issues/820).
- `AD-842` — collision: 2 issues each lead with this number: [#817](https://github.com/seangalliher/ProbOS/issues/817), [#821](https://github.com/seangalliher/ProbOS/issues/821).
- `AD-843` — collision: 2 issues each lead with this number: [#818](https://github.com/seangalliher/ProbOS/issues/818), [#822](https://github.com/seangalliher/ProbOS/issues/822).
- `AD-861` — collision: 2 issues each lead with this number: [#831](https://github.com/seangalliher/ProbOS/issues/831), [#1247](https://github.com/seangalliher/ProbOS/issues/1247).
- `AD-909` — collision: 2 issues each lead with this number: [#872](https://github.com/seangalliher/ProbOS/issues/872), [#951](https://github.com/seangalliher/ProbOS/issues/951).
- `AD-938` — the trackers disagree: allocated-open, shipped. Resolved as `shipped`.
- `AD-943` — collision: 2 issues each lead with this number: [#874](https://github.com/seangalliher/ProbOS/issues/874), [#878](https://github.com/seangalliher/ProbOS/issues/878).
- `AD-944` — collision: 2 issues each lead with this number: [#875](https://github.com/seangalliher/ProbOS/issues/875), [#879](https://github.com/seangalliher/ProbOS/issues/879).
- `AD-945` — collision: 2 issues each lead with this number: [#876](https://github.com/seangalliher/ProbOS/issues/876), [#880](https://github.com/seangalliher/ProbOS/issues/880).
- `AD-946` — collision: 2 issues each lead with this number: [#877](https://github.com/seangalliher/ProbOS/issues/877), [#881](https://github.com/seangalliher/ProbOS/issues/881).
- `AD-983` — the trackers disagree: deferred, shipped. Resolved as `shipped`.
- `AD-985` — the trackers disagree: allocated-open, shipped. Resolved as `shipped`.
- `AD-1138` — code is in history but [#1057](https://github.com/seangalliher/ProbOS/issues/1057) is still open.
- `AD-1143` — code is in history but [#1057](https://github.com/seangalliher/ProbOS/issues/1057), [#1064](https://github.com/seangalliher/ProbOS/issues/1064) is still open.
- `AD-1166` — collision: 2 issues each lead with this number: [#1097](https://github.com/seangalliher/ProbOS/issues/1097), [#1197](https://github.com/seangalliher/ProbOS/issues/1197).
- `AD-1170` — collision: 2 issues each lead with this number: [#1101](https://github.com/seangalliher/ProbOS/issues/1101), [#1257](https://github.com/seangalliher/ProbOS/issues/1257).
- `AD-1179` — the trackers disagree: allocated-open, shipped. Resolved as `shipped`.
- `AD-1185` — code is in history but [#1138](https://github.com/seangalliher/ProbOS/issues/1138) is still open.
- `AD-1189` — the trackers disagree: deferred, shipped. Resolved as `shipped`.
- `AD-1200` — the trackers disagree: allocated-open, shipped. Resolved as `shipped`.
- `AD-1230` — collision: 2 issues each lead with this number: [#1203](https://github.com/seangalliher/ProbOS/issues/1203), [#1256](https://github.com/seangalliher/ProbOS/issues/1256).
- `AD-1270` — the trackers disagree: allocated-open, shipped. Resolved as `shipped`.
- `AD-1270` — code is in history but [#1324](https://github.com/seangalliher/ProbOS/issues/1324) is still open.
- `AD-1287` — code is in history but [#1334](https://github.com/seangalliher/ProbOS/issues/1334) is still open.
- `AD-1288` — code is in history but [#1335](https://github.com/seangalliher/ProbOS/issues/1335) is still open.
- `AD-1299` — code is in history but [#1352](https://github.com/seangalliher/ProbOS/issues/1352) is still open.
- `AD-1300` — code is in history but [#1353](https://github.com/seangalliher/ProbOS/issues/1353) is still open.
- `AD-1301` — code is in history but [#1354](https://github.com/seangalliher/ProbOS/issues/1354) is still open.
- `AD-1302` — code is in history but [#1355](https://github.com/seangalliher/ProbOS/issues/1355) is still open.
- `AD-1303` — code is in history but [#1356](https://github.com/seangalliher/ProbOS/issues/1356) is still open.
- `AD-1304` — code is in history but [#1357](https://github.com/seangalliher/ProbOS/issues/1357) is still open.
- `AD-1326` — code is in history but [#1510](https://github.com/seangalliher/ProbOS/issues/1510) is still open.
- `AD-1327` — code is in history but [#1511](https://github.com/seangalliher/ProbOS/issues/1511) is still open.
- `BF-063` — collision: 2 issues each lead with this number: [#3](https://github.com/seangalliher/ProbOS/issues/3), [#135](https://github.com/seangalliher/ProbOS/issues/135).
- `BF-125` — collision: 2 issues each lead with this number: [#28](https://github.com/seangalliher/ProbOS/issues/28), [#29](https://github.com/seangalliher/ProbOS/issues/29).
- `BF-126` — collision: 2 issues each lead with this number: [#33](https://github.com/seangalliher/ProbOS/issues/33), [#133](https://github.com/seangalliher/ProbOS/issues/133).
- `BF-133` — collision: 2 issues each lead with this number: [#116](https://github.com/seangalliher/ProbOS/issues/116), [#134](https://github.com/seangalliher/ProbOS/issues/134).
- `BF-145` — collision: 2 issues each lead with this number: [#158](https://github.com/seangalliher/ProbOS/issues/158), [#159](https://github.com/seangalliher/ProbOS/issues/159).
- `BF-183` — collision: 2 issues each lead with this number: [#245](https://github.com/seangalliher/ProbOS/issues/245), [#246](https://github.com/seangalliher/ProbOS/issues/246).
- `BF-184` — collision: 2 issues each lead with this number: [#247](https://github.com/seangalliher/ProbOS/issues/247), [#248](https://github.com/seangalliher/ProbOS/issues/248).
- `BF-185` — collision: 2 issues each lead with this number: [#249](https://github.com/seangalliher/ProbOS/issues/249), [#250](https://github.com/seangalliher/ProbOS/issues/250).
- `BF-186` — collision: 2 issues each lead with this number: [#251](https://github.com/seangalliher/ProbOS/issues/251), [#252](https://github.com/seangalliher/ProbOS/issues/252).
- `BF-187` — collision: 2 issues each lead with this number: [#253](https://github.com/seangalliher/ProbOS/issues/253), [#255](https://github.com/seangalliher/ProbOS/issues/255).
- `BF-188` — collision: 2 issues each lead with this number: [#254](https://github.com/seangalliher/ProbOS/issues/254), [#255](https://github.com/seangalliher/ProbOS/issues/255).
- `BF-189` — collision: 2 issues each lead with this number: [#256](https://github.com/seangalliher/ProbOS/issues/256), [#257](https://github.com/seangalliher/ProbOS/issues/257).
- `BF-190` — collision: 2 issues each lead with this number: [#259](https://github.com/seangalliher/ProbOS/issues/259), [#261](https://github.com/seangalliher/ProbOS/issues/261).
- `BF-193` — collision: 2 issues each lead with this number: [#263](https://github.com/seangalliher/ProbOS/issues/263), [#264](https://github.com/seangalliher/ProbOS/issues/264).
- `BF-207` — collision: 2 issues each lead with this number: [#282](https://github.com/seangalliher/ProbOS/issues/282), [#345](https://github.com/seangalliher/ProbOS/issues/345).
- `BF-236` — the trackers disagree: allocated-open, shipped. Resolved as `shipped`.
- `BF-264` — collision: 2 issues each lead with this number: [#422](https://github.com/seangalliher/ProbOS/issues/422), [#636](https://github.com/seangalliher/ProbOS/issues/636).
- `BF-623` — the trackers disagree: allocated-open, shipped. Resolved as `shipped`.
- `BF-707` — collision: 2 issues each lead with this number: [#1113](https://github.com/seangalliher/ProbOS/issues/1113), [#1312](https://github.com/seangalliher/ProbOS/issues/1312).
- `BF-711` — code is in history but [#1138](https://github.com/seangalliher/ProbOS/issues/1138) is still open.
- `BF-759` — collision: 2 issues each lead with this number: [#1217](https://github.com/seangalliher/ProbOS/issues/1217), [#1219](https://github.com/seangalliher/ProbOS/issues/1219).
- `BF-804` — collision: 2 issues each lead with this number: [#1268](https://github.com/seangalliher/ProbOS/issues/1268), [#1350](https://github.com/seangalliher/ProbOS/issues/1350).
- `BF-889` — code is in history but [#1515](https://github.com/seangalliher/ProbOS/issues/1515) is still open.

## Unparseable lines

9 head-shaped lines could not be parsed. A malformed or historical entry is skipped and counted, never fatal — five eras of formatting conventions are represented in these files.

```
PROGRESS.md:1393 head-shaped line yielded no AD/BF token
PROGRESS.md:1399 head-shaped line yielded no AD/BF token
progress-era-3-product.md:146 head-shaped line yielded no AD/BF token
progress-era-3-product.md:167 head-shaped line yielded no AD/BF token
progress-era-3-product.md:190 head-shaped line yielded no AD/BF token
progress-era-4-evolution.md:15 head-shaped line yielded no AD/BF token
progress-era-4-evolution.md:24 head-shaped line yielded no AD/BF token
progress-era-4-evolution.md:32 head-shaped line yielded no AD/BF token
progress-era-4-evolution.md:48 head-shaped line yielded no AD/BF token
```
