# Platform Maturity Baseline - 2026-08-30

**Purpose:** Reproducible discovery baseline for AD-1270 / #1324.

**Authority:** Observational input to AD-1270b and AD-1270f. This report does
not itself pass an architecture, readiness, or release gate. The future
versioned checkers replace heuristic fields below as acceptance authorities.

## Source And Host

| Field | Value |
|---|---|
| Source commit hash | `bf6c9981151cafbc44b3bb8599d69b797f543fde` |
| Source extraction | `git archive bf6c9981151cafbc44b3bb8599d69b797f543fde src` into a temporary directory; working-tree source changes excluded |
| OS | Windows 11 `10.0.26200` |
| CPU | AMD Ryzen 9 7950X3D, 16 physical / 32 logical cores |
| Python | 3.12.13 |
| pytest | 9.0.2 |
| pytest-xdist | 3.8.0 |
| Git | 2.53.0.windows.1 |
| Local timezone | UTC-06:00 |

## Architecture Discovery

The source audit parsed every committed `src/**/*.py` file with Python's
`ast` module. Class body span is `end_lineno - lineno + 1`. Method counts include
only direct `FunctionDef` and `AsyncFunctionDef` nodes in `ClassDef.body`; nested
functions and methods on nested classes are excluded. Lexical counts are file
counts, not occurrence counts.

Candidate predicates used by the discovery script were:

- external private attribute: any `ast.Attribute` whose `attr` begins with `_`
   and whose immediate receiver is not the name `self`;
- direct database connection: an `ast.Call` whose callee renders exactly as
   `sqlite3.connect` or `aiosqlite.connect`;
- task creation: an `ast.Call` whose callee is `asyncio.create_task`,
   `loop.create_task`, `asyncio.get_running_loop().create_task`, or any
   attribute named `create_task` (the last form intentionally over-matches
   domain store methods);
- bare-expression task candidate: a task-creation candidate whose direct parent
   AST node is `ast.Expr`.

The discovery script did not persist its own source in this initial baseline.
AD-1270b must ship the reproducible checker before any candidate count becomes
a failing architecture gate.

| Signal | Observation | Interpretation limit |
|---|---:|---|
| Production Python files | 908 | Exact for the pinned commit and glob |
| Classes with body span over 500 lines | 66 | Review trigger, not automatic SRP violation |
| Classes with more than 15 methods | 77 | Review trigger, not automatic SRP violation |
| Files containing `ProbOSRuntime` | 60 | Includes comments and type-only facade references |
| Files explicitly importing `probos.protocols` | 37 | Does not count local Protocol definitions or structural DI without that import |
| External private-attribute candidates | 1,110 | Broad AST candidate set; includes false positives such as `super().__init__`, `os._exit`, and type metadata |
| Direct `sqlite3.connect` / `aiosqlite.connect` calls | 30 | Includes approved adapter and maintenance/CLI candidates; classification belongs to AD-1256 |
| Task-creation calls | 180 | Includes `asyncio.create_task`, loop task creation, and same-named domain methods |
| Bare-expression task-creation candidates | 26 | Candidate set only; a bare call does not prove the task is unowned elsewhere |
| Verified lower-to-higher layer violations | Not established | The two initial candidates were allowed `TYPE_CHECKING` + DI edges; the naive package-rank scan is rejected |

### Largest Classes

| Body lines | Methods | Class |
|---:|---:|---|
| 10,598 | 189 | `probos/cognitive/cognitive_agent.py::CognitiveAgent` |
| 5,967 | 107 | `probos/runtime.py::ProbOSRuntime` |
| 4,444 | 62 | `probos/proactive.py::ProactiveCognitiveLoop` |
| 3,316 | 74 | `probos/workforce.py::WorkItemStore` |
| 3,259 | 60 | `probos/cognitive/episodic.py::EpisodicMemory` |
| 3,217 | 60 | `probos/cognitive/crew_session.py::CrewSessionService` |
| 2,937 | 34 | `probos/cognitive/dreaming.py::DreamingEngine` |
| 2,759 | 56 | `probos/cognitive/crew_finalizer.py::CrewSessionFinalizer` |
| 2,529 | 59 | `probos/cognitive/counselor.py::CounselorAgent` |
| 2,115 | 42 | `probos/cognitive/llm_client.py::OpenAICompatibleClient` |

AD-1270b must turn each broad candidate family into a deterministic,
domain-aware classifier with reviewed exceptions before using it as a failing
fitness gate. No count in this section may be presented as a verified violation
denominator until that classifier ships.

## Full-Gate Cost Observation

### Method

1. Inputs were the deduplicated union of repository-root files and
   `logs/**/*` with suffix `.log`, `.txt`, `.out`, or `.stdout`.
2. Local mtime window was 2026-08-24 00:00:00 through 2026-09-01 00:00:00,
   UTC-06:00.
3. For each readable file, the parser selected the last single line containing
   `passed` and an elapsed `in <seconds>` pytest summary.
4. A run qualified when `passed + failed + errors >= 20,000`; field order was
   irrelevant. Incomplete and unreadable files were excluded, never counted as
   zero-result runs.
5. These legacy artifacts do not carry tree fingerprints, worker settings, or
   node manifests. They are cost evidence, not the non-gameable AD-1270f
   acceptance series. The canonical wrapper must supply those missing fields.

### Aggregate

| Metric | Value |
|---|---:|
| Qualifying completed artifacts | 38 |
| Total elapsed | 38,093.00 s / 10.58 h |
| Red artifacts | 16 |
| Red elapsed | 16,508.46 s / 4.59 h |
| Green artifacts | 22 |
| Green elapsed | 21,584.54 s / 6.00 h |
| Median | 953.18 s / 15:53 |
| Range | 853.25-1,774.27 s |

### Included Artifacts

Each SHA-256 is over the complete local artifact bytes.

| Artifact | SHA-256 | Passed | Failed | Skipped | Seconds |
|---|---|---:|---:|---:|---:|
| `_ad1263_full.txt` | `1b2fc3e62d901b0b8fce00df67d26b6d8d87e85d0b9eebbb2cdb9e19112455c0` | 24559 | 2 | 27 | 1774.27 |
| `logs/ad1262_gate.log` | `5519bc2e275be6f4b32f639150888cb5e0bd4616e6cc161177ffb8c754e1abd4` | 24539 | 6 | 28 | 1308.35 |
| `logs/ad1262_gate2.log` | `c48e26a5c6d85412674da58210268c5aa11ce7ad0e270761984193740a5d11ca` | 24544 | 1 | 28 | 1451.24 |
| `logs/ad1262_gate3.log` | `fd9b9374f4fec722f5cc33aebe0c86d36c763b784ab65d47b24a4ee6ce87111e` | 24568 | 1 | 28 | 892.31 |
| `logs/ad1263_gate.log` | `9f8e0a4a588b3e41e4958bc595b95135800736710ef4f688a088f038df719ed1` | 24561 | 0 | 27 | 1281.76 |
| `logs/ad1264_gate.log` | `f2bd0e18ad9ab6895419f1764ca18cb3219eb804dd2d1ebec7443c025f38e061` | 24532 | 2 | 27 | 911.71 |
| `logs/ad1264_gate2.log` | `975340269a918de8b375a2ad33bc5cb5a29cfb91ca9e688cc9af70264e4b5848` | 24542 | 0 | 27 | 894.42 |
| `logs/ad1269_gate.log` | `6b857d207c02812025e3242c823c23c277fbfd2e1578672dadf0083be53d62ab` | 24635 | 0 | 27 | 903.24 |
| `logs/ad1285_gate.log` | `be12caa47b809886691faccf57f0e3e767b690a97c8745ba0793fd640a23bd6e` | 25377 | 4 | 27 | 921.97 |
| `logs/ad1285_gate2.log` | `335973d3d627ce34b89e7d043ff405ab24491e118d5a8e1aa5824f036c38a629` | 25378 | 3 | 27 | 907.68 |
| `logs/ad1285_rev2_gate.log` | `98d5fcc1ad153bc6f566121c746101ed731f37585d2d01a17b7070d04c7ec6cb` | 25356 | 6 | 27 | 954.31 |
| `logs/ad1292_gate.log` | `cf28b9756445fd5dd3f1185de3d98bdf44594008aaf4bf4683460ff15ca7c88b` | 25370 | 5 | 27 | 857.61 |
| `logs/ad1292b_gate.log` | `98fafc566ef04fb87dbcf9615c01e0de31733082cb673ad6f602c6eade131a8d` | 25373 | 3 | 27 | 861.53 |
| `logs/ad1293_gate.log` | `65aa6843cafaffba040b976a7540745d08630b11aafd0860f6f9b12137c74146` | 25438 | 2 | 27 | 853.25 |
| `logs/ad1293_gate3.log` | `f541bc6e37ccf32b3f2d2fd6989840ac44045ed1526366e8583d8e08f25f2bf8` | 25438 | 2 | 27 | 879.74 |
| `logs/ad1293_gate4.log` | `be242b051068ed3e6824cf5891137c861dbe3668eeb9165ebb4cdf614e3f252c` | 25440 | 0 | 27 | 954.26 |
| `logs/ad1295_gate.log` | `3a7fb8854885be3d6e3a186975d0d342e5c79a2652966077ec829c9b4de493ac` | 25482 | 3 | 27 | 1097.11 |
| `logs/ad1295_rev2_gate.log` | `7a61d85eb62a90bc52e430f24ac4e2f4efa8e5515e186b23e46101af67556349` | 25494 | 3 | 27 | 949.53 |
| `logs/ad1295_rev2_gate2.log` | `eb89582ffe94af5502cced2d9261427fe1cefd48a289be3a94374a5afae0a8c9` | 25508 | 0 | 27 | 1032.26 |
| `logs/batch1_gate.log` | `f772be7cae9156beead62b84a36652da2197dc2eb7d86f2ad050097e04cebe25` | 24533 | 0 | 27 | 1011.41 |
| `logs/batch2_gate.log` | `90a7d4cc4d209dc9c574cab24f072802c4e55c80268074a17244c0f8f32a22a5` | 24533 | 0 | 27 | 954.61 |
| `logs/bf824_gate.log` | `882637ad7cfc0da1dd91d952eb5455cd82b57e27538cc9a40dc5718a06839de7` | 24500 | 2 | 27 | 992.30 |
| `logs/bf824_gate2.log` | `ace484370f1cbb68f062cf523880b46fde8a895883ce2f26cecd03b6adbcf7ac` | 24501 | 0 | 27 | 967.23 |
| `logs/bf834_gate.log` | `e7a2daf7a62ba805bedbe1455c9aa15995e7f8722a268cba80391ae1b4e6f762` | 24524 | 0 | 27 | 952.11 |
| `logs/bf840_gate.log` | `334066efbf6f9ad112c105373814141723bee9931c362141b571444bc0a16daf` | 24491 | 0 | 27 | 982.90 |
| `logs/bf840_gate5.log` | `dc6f52f1f0edf29c48d6ae22213c52abd4c98f1dfef4c45d0d55922ebd7ddbf6` | 24494 | 0 | 27 | 980.39 |
| `logs/bf842_gate.log` | `984330f06ef0be86ebe221dc53249110e1c3b4976e09ef08c997f08ad398764a` | 24479 | 0 | 27 | 971.78 |
| `logs/bf842_gate2.log` | `fa406d02a7f529989b7794381be801a20df91210457af452f7c9a40b855f6652` | 24479 | 0 | 27 | 1005.06 |
| `logs/bf847_bf848_gate.log` | `c796b9b75cb9dc38f0e6d1d3ae66d052795ec1225a0933759b6ca7f2d3b2a814` | 24502 | 0 | 27 | 1008.24 |
| `logs/bf850_gate.log` | `b850b659e691309985906b0404841dad9731dc8c0940be8c7a79be5eae2ae3ed` | 24519 | 0 | 27 | 938.92 |
| `logs/bf852_gate.log` | `c8035a3c014088670a3d803579a05d96bd9fce26f1143173b3044f763a236490` | 24502 | 0 | 27 | 942.62 |
| `logs/bf853_gate.log` | `876d610dcee00cb1e1681b8a2ffd0f07fd2d02475224cf60720a59a9f1495689` | 24516 | 0 | 27 | 948.58 |
| `logs/bf854_gate.log` | `739d8018f0bdc604da515ed8a4db640a473fd0dacc169f8c73e61ad94f0aef0d` | 24512 | 0 | 27 | 928.66 |
| `logs/bf854_gate2.log` | `1f35a5e0b8a8597261123dd956feb4f7bc3197beef2c80c6b1eb865c6d5bcbcc` | 24514 | 0 | 27 | 1153.39 |
| `logs/gate_ad1267.log` | `c0f74f6f432a9a908fbf8471a6f8c1f436e19ce08a9883fac4cd6049b1a511a6` | 24766 | 1 | 27 | 895.55 |
| `logs/gate_ad1267b.log` | `d2dda64b201334227a252b299b8dcc007f137edc2299e54089e774e145de7c91` | 24767 | 0 | 27 | 883.94 |
| `logs/gate_ad1271.log` | `50b7fe3c9f5f4cf1e21673c457d6600fd8422b8ff6aaa9fcb9f5d77fa8022105` | 24743 | 0 | 27 | 899.64 |
| `logs/gate_bf822.log` | `ef1c8e04169e08d21e91b61163de71f9594c6065bbd82226389929b28f9ad281` | 24722 | 0 | 27 | 989.12 |

## GitHub Duplicate Enumeration

Semantic searches scoped to `seangalliher/ProbOS`, including open and closed
issues, were run on 2026-08-30:

| Query | Enumerated matches |
|---|---|
| `platform maturity modular architecture god object SOLID runtime configuration finalization decomposition` | #1324 only |
| `test gate performance impact selection slow tests pytest full suite validation` | none |
| `seam contract producer consumer crossing test built tested inert` | none |
| `storage lifecycle connection factory sqlite database registry backup restore` | #1302 open; #739 and #400 closed |

Result: #1324 remains the integrated architecture/validation coordination
authority. #1302 retains storage ownership. No additional issue is warranted.