# BF-953 (#1752): the read floor decides every spelling of one file the same way

**Drafted by:** the Copilot `Architect` (the Claude Code bridge's fallback), 2026-11-04
**Revised by:** the orchestrator (Claude Sonnet 5.5), 2026-11-04, before the build: §1 item 1 names the spelling probe as a session artifact that is not committed (it cited a file outside the repository); no block, count, hash or mutation row changed. The bridge's draft of this prompt (the Claude Code `claude-architect`, Opus 5.5) was stopped partway by a safety classifier, which is why the documented fallback drafted it.
**Revised by (Amendment 1):** the Copilot `Architect` (the Claude Code bridge's fallback), 2026-11-04, after review round 2 of the whole candidate (`d1aba238d5b1658c772c59d3c6273b5e7899c68c`, NOT READY). Identity becomes a deny-only layer (§3 D8: findings 1 to 3), the read-policy root builders resolve the workspace root (D9: finding 5), `list_files` shows a match without its namespace prefix (D10: finding 4, built as BF-948's M5), and §3 D3 to D7, §6, §9, §11, §16 and §17 are corrected where they overclaimed (finding 7). Finding 6 is scheduled, not built (BF-948 L16). M4's line numbers are those of `d1aba238`. **Updated after a second round-2 reviewer's report (R1 to R6):** the final component of a floor file root and of a credential name names the file it names (D11: R3 and R6), a file root outranks the workspace that encloses it in every spelling of the workspace root (T17: R1), an absent floor file root and an absent credential name are decided like a present one (T21: R6), the display form is tested through the verified reader (BF-948 T14: R4), and the claims that overreached are scoped (R6).
**Revised by (Amendment 2):** the Copilot `Architect` (the Claude Code bridge's fallback), 2026-11-04, after review round 3 of the whole candidate (`34bd9153aca8d7e89cf4468cdb1704f77edf791c`, NOT READY). A floor file root is compared by the file its own final component names, as a candidate is (D12), the two read-policy root builders keep a workspace root the system cannot resolve as it was composed (D13), `reader_spelling` says whether a listing may name a match (D14; BF-948's M6 uses it), and the claims that overreached are corrected (§1 items 9 to 12, §6 T16, T19 and T20, §16 items 3 and 13). BF-948 L16 stays scheduled. M5's line numbers are those of `34bd9153`. Review scope for M5 and M6 (recommended; the orchestrator decides, §16): the delta and §16 items 18 to 22, with the three reproductions of §1 items 9 to 11.
**Revised by (orchestrator, 2026-11-05, after Amendment 2):** section 10's rows DNY-11, DNY-12, DNY-16, DNY-19 and DNY-30 name lines that M5 and BF-948's M6 replaced (the two root builders now share `_workspace_root`, the floor call is `_floor_roots(protected_roots)`, and the listing's display form is `reader_spelling`): their anchors and mutants are the post-M6 text, because the census tool found the old anchors occurring 0 times on the built head; no code, count or other row changed.
**Revised by (Amendment 3):** the Copilot `Architect` (the Claude Code bridge's fallback), 2026-11-05, after review round 4 of the whole candidate (`a0857b088a09f4f0b5f8c975c45bb7f973039050`, NOT READY on F1 and F2; every round-3 finding resolved, none regressed). `reader_spelling` gives a spelling only where the verified reader's own rules on the text admit it, on every platform (D15: its location gate `validate_read_location`, called as it is, and its child-name rule for the final name). That closes round 4's F1 (a name that is not strict UTF-8) and the other refusals of the same gate and rule, which the function applied on Windows only or not at all. The sentence that said a listing's cost per match is unchanged is corrected (F2): the function calls no filesystem function (T32) and adds string and path-object work (L20). L18 lists what a listing cannot promise, L19 what a listing leaves out that only the plain reader opens. Review scope for M6: round 5 reviews the delta (§16 item 27 lists what it verifies); whether the standing order's "adds behaviour the findings did not ask for" clause widens it to the whole candidate is the orchestrator's decision (Amendment 3's §0.2 recommends the delta). BF-948's M7 is a docstring and two comments.
**Revised by (Amendment 4):** the Copilot `Architect` (the Claude Code bridge's fallback), 2026-11-05, after review round 5 of the whole candidate (`8c83093bd644be60d199c3f4cca1227f08472459`, NOT READY on A and B5-1; every round-4 finding resolved, none regressed). `reader_spelling` gives the verified reader's location gate the file's direct parent as well as the file (D15 as amended: the two texts `read_verified_file` gives it), on every platform, so a file whose direct parent the gate refuses has no spelling and is not listed (round 5's A: on POSIX a file in a directory named as a reserved device was offered and refused). Windows is unchanged: the chain rule of D14 already covered the direct parent. T29 and T30 pinned the wrong answer and are corrected; T34 (a generated differential against the reader's own gate and child-name rule) and T35 (real files, the real reader, the real tool) are new; L18 and L19 are amended, L20 has new numbers and L21 is new (the reader opens the directories above the direct parent without the gate, so the Windows rule is wider than the reader's text path). B5-1 corrects three claims of Amendment 3 (D15, SP12, L19): what refuses a name that is not strict UTF-8 is the reader's encoding of the path, and a refused name is answered `read_file failed` with the reader's own text, not always `invalid path`. Review scope for M7: round 6 reviews the delta (§16 items 28 to 32 list what it verifies). BF-948's M8 is a docstring.
**Revised by (Amendment 5):** the Copilot `Architect` (the Claude Code bridge's fallback), 2026-11-05, after review round 6 of the whole candidate (`bd67126a5e124cfe846c3008cad3dc1fc69f30dc`, NOT READY on F1, F3 and four claims; every round-5 finding resolved, none regressed). `reader_spelling` gives no spelling to a path with no final name (a root: the reader's pinned directory refuses the empty child name) and none to a path with a `..` part (the reader decides on the candidate its location gate returns, which resolves `..`; a listing's paths have none): two deny-only clauses before the Windows branch (D15; round 6's F1 and F3). T34 is rewritten on the public API (the gate and a real pinned directory's `read_bytes`; its corpus holds `..` parts, hidden names and roots), T29 and T30 gain rows, T36 and T38 (a root) and T37 (the texts the real reader gives its location gate) are new. The claims are deleted rather than reworded: the class lists leave D15, L18, L19, L21, §6, §16 and the trackers; L22 is the one place that says what the armed reader answers, with the output of the command that measured it (§13f); L20 gives a measured range with call counts; B6-3's "fail at once" is replaced by T37. Review scope for M8: round 7 reviews the delta (§16 items 33 to 38 list what it verifies). BF-948's M9 is a docstring, LF9, L19 and §17 item 6.
**Status:** M1 to M4 built (`c11a53dd`, `97101777`, `a7bd6372`, `f0f5f721`). M5 to build in the same PR, before BF-948's M6. **Base:** drafted on the BF-948 worktree head `728e1fc2d2f49fd04584adf2a41d1dfa68befcb5` (branch `fix/bf948-list-files-read-policy-20261104-ca0ca20b`, base `origin/main` `ca0ca20b9bfa80b4d2367bc61ab1f5d995969a38`). The orchestrator's brief named `9649df65`; `728e1fc2` adds only the amended BF-948 contract (`git diff --stat 9649df65 728e1fc2` is one file under `prompts/`), and every file this contract changes has the same blob at both (§13), so each pair applies to either. **Dependencies:** none; built first in the BF-948 PR (#1752 says so), before BF-948's M4. **Tier:** M1 STANDARD, M2 HIGH, M3 STANDARD, M4 HIGH, M5 HIGH. **Estimated tests:** 1 new file, `tests/test_bf953_read_floor_spellings.py` (29 test functions, 198 cases after M5; counts in §4).
**BF number:** BF-953, held by the title of #1752 (`gh issue view 1752`: OPEN, "BF-953: resolve_read_path does not return one decision for every spelling of one file"). Current highest: **BF-953** (GitHub issue titles, all states, 1,507 fetched; the next BF-95x is BF-954). `git log --all` subjects stop at BF-951; `prompts/bf-95*` is empty; the roadmap's Bug Tracker has no BF-95x row (§Absence Verified).
**Shared-contract change.** `resolve_read_path` is a public function every read path asks. This changes its decisions, so every consumer (§1, found by search) inherits it. **The Diff Reviewer therefore covers the whole candidate**, not the new lines: §16 lists the properties, and §3 D6 gives the compatibility story and §6 how it is tested.
**Which text describes the head.** Line numbers are those of `728e1fc2`. Where prose differs from a REPLACE or new-file block, the block wins. "Head text" means every docstring, comment, error string and test docstring in those blocks, plus the tracker entries (§8) and the commit messages (§5).

## 1. Problem

`security/file_access.py::resolve_read_path` (`:105-162`) resolves a path with `Path.resolve()` and decides it by comparing the result's text with three root lists through `_longest_match` (`:92-102`): the floor (the runtime data directory and the config files, `protected_read_roots` `:197-206`), the exempt roots (`workspace_exempt_roots` `:388-398`) and the permitted roots (`permitted_read_roots` `:165-194`).

1. **The function's decision depends on the spelling.** Measured on the committed head, Windows, Python 3.12.13, by the orchestrator's probe of 20 spellings of one fixture file (a session probe whose output is not committed, run on the tree, with `os.path.samestat` and the bytes as the premise that each row is the same file; T1 is its committed form). 11 spellings are decided like the ordinary one for a file on disk, because `Path.resolve()` normalises them: forward slashes, a doubled separator, a dot segment, `..` through a sibling and through a missing directory, swapped case, the 8.3 name, a trailing dot, a trailing space, a stream suffix, and the device prefix. **9 are decided differently**, for the floor and the permitted roots alike: the extended-length prefix (plain, swapped case, 8.3 name) and the share spellings of the local drive (`localhost`, `127.0.0.1`, the computer name, the extended forms of `localhost` and of the computer name, and `localhost` with `..`). One of the 11, the trailing space, is also decided differently for a file that is not on disk (found while building T1, on this host): `Path.resolve()` of a missing child of a directory spelled with a trailing space returns the extended-length spelling of it (`\\?\C:\…\dir\child`), so it takes the same road through the function. `Path.resolve()` keeps the extended-length prefix it was given and reports a share spelling of a local drive as the share path, so the text of the result matches none of the roots the ordinary spelling matches.
2. **The exemption case.** With a floor root over an exempt root, the 9 spellings are admitted only because no floor root matched them, so the exemption was never asked. After the fix a floor root matches them, and the exemption must still lift it where it applies (T1).
3. **The write side of the same module already treats this.** `_write_key` (`:266-281`) drops the `//?/` and `//./` prefixes (`_DEVICE_PREFIXES` `:252`) and `//?/UNC/` becomes `//`. It cannot make `//localhost/C$/x` the key of `C:/x`: BF-911 adds an `os.stat` identity layer for the config files (`:360-368`). The read side has neither.
4. **Consumers, by search** (`rg -n "resolve_read_path|resolve_for_runtime|protected_read_roots|permitted_read_roots|protected_config_files|workspace_exempt_roots|_longest_match|_ReadFloor" src tests scripts`; 85 hits in 10 `src` files, 7 test files, none in `scripts`):

   | Consumer | Where | How it asks |
   |---|---|---|
   | `resolve_for_runtime` | `security/file_access.py:401-411` | composes the three lists, calls `resolve_read_path` |
   | `read_verified_file`, `read_bounded_utf8` | `file_access.py:863-876`, `:902-` (calls at `:869`, `:933`) | pass the lists they were given; compare the returned path with their lexical candidate (`resolved != candidate`) |
   | `ReadFileTool`, `CodebaseReadSourceTool` | `cognitive/swe_harness/tools.py:449`, `:790` (`resolve_for_runtime`); `:339-341`, `:948-950` (the three lists) | |
   | `ListFilesTool` (BF-948) | `tools.py:563-580` | the base, then every match, with one composition of the lists |
   | `_ReadFloor` (BF-908) and its sites | `agents/code_search.py:143-146`, `:323-359` | one composition per search, one `resolve_read_path` per result path |
   | `FileReaderAgent`, `FileSearchAgent`, `DirectoryListAgent` | `agents/file_reader.py:106-108`, `agents/file_search.py:128-131`, `agents/directory_list.py:107-110` | `resolve_for_runtime` |
   | the copilot adapter | `cognitive/copilot_adapter.py:31-36`, `:110-112` | the three lists |
   | repository instructions | `repository_instructions.py:12-19`, `:62-64` | the three lists |
   | the agent work runner | `agent_work_runner.py:606-617`, `:699-714` | `permitted_read_roots`, `workspace_exempt_roots` |

   `protected_config_files` is also called by the write side (`file_access.py:350`). Nothing outside `file_access.py` calls `_longest_match` (§Absence Verified A1).

   **Found in review round 2 (Amendment 1), on `d1aba238`.** As properties of the head's decision:
   1. A share spelling of a path whose chain passes a link to another volume, below a permitted root, was admitted by the identity of the chain's lexical parents although the file is on the other volume (the ordinary spelling and a local link were refused). The lexical ancestry of a share spelling is not the file's physical ancestry.
   2. Identity said which directory a root names, but precedence still compared `len(root.parts)` of the root's own spelling, so an exempt root that names the floor directory or its parent in a device spelling (10 parts against the floor's 8) lifted the floor.
   3. `_file_identity` collapsed "no such file", "cannot be read" and "no file index" into `None`; `_longest_match` read that as "no floor match", and the call was admitted through another root's identity.
   4. A listing of an extended-prefix base, now admitted under a permitted root, named prefixed absolute paths that the armed reader (`read_verified_file`, through `validate_read_location`) rejects; for a base inside the project tree it named absolute names where project-relative names are promised (the display form came after the test against the project tree).
   5. A workspace root configured as an 8.3 short path was passed unresolved by the two read-policy root builders, so the resolved candidate never matched it by text.
   6. The same identity step left a share spelling through a link to another volume, into the interior of a floor root, admitted (on the base as well).
   7. A loaded config file (a floor file root) inside an exempt workspace root was admitted in every spelling when the workspace root was configured as a device path: precedence ranked the exemption by how its root is spelled, not by where it stands in the path (the cause of 2, with a file for the floor root).
   8. The floor's file roots and the credential file names were compared by the text of the final component as given: a stream suffix, trailing dots or spaces, or (for a credential name) another case, named the same file and were admitted, for a stream that exists and for a file that is not on disk.

   **Found in review round 3 (Amendment 2), on `34bd9153`.** As properties of the head's decision:
   9. A floor file root whose own final component carries a stream suffix (a configuration loaded as `loaded.yaml:settings`) was compared as spelled, while the candidate's final component was reduced to the file it names. So the root's own spelling was admitted where the base refused it (Windows, an ordinary configuration; introduced by M4). The same holds for a root spelled in the extended namespace with a trailing dot or space.
   10. `permitted_read_roots` resolved the workspace root inside the `try` that skips a failure. When every configured read root was unusable and the workspace root could not be resolved (a text with a NUL), the list was `[]`, which every consumer reads as "no limit"; the base kept the unresolved root and confined every read (introduced by M4). `workspace_exempt_roots` had the same failure point (its result there is the safe direction: no exemption).
   11. `ListFilesTool` named a match in the spelling `plain_spelling` returns without asking whether that spelling names the same file. A name that ends in a dot or a space (made through the extended namespace) opens a neighbour or nothing, and a reserved device name opens the device and is rejected by the verified reader (introduced by M5 for a prefixed base; the same on the base for an ordinary one). `file_access` gives the lister the function it asks (`reader_spelling`, D14); the lister is BF-948's M6.
   12. Claims: §16 item 3 said every drive-letter decision against drive-letter roots is the base's, which the final-component rule and the 8.3 workspace root disprove; T16 and §16 item 13 said T16 pins how an exemption is ranked, and it shows only that a text count is the same number; T19's docstring promised the suffix is kept and asserted admission only; the test module docstring, `PROGRESS.md` and `_namespace_free`'s docstring said such names "do not make another file" and that a bare drive is returned unchanged.

   **Found in review round 4 (Amendment 3), on `a0857b08`.** As properties of the head's decision:
   13. `reader_spelling` gave a spelling that the verified reader's location gate refuses: text that is not strict UTF-8 (a name with an unpaired UTF-16 surrogate on Windows, a name decoded with `surrogateescape` on POSIX). Listed from an ordinary and from an extended-prefix base, the name answered `read_file failed: ... surrogates not allowed` from the armed reader, and a repeat of the read counts as a tool defect (both reviewers; one measured `same_run_defect_count=2`, `persisted_faults=1`, `faults_after_sqlite_reload=1`). The function applied no other rule of the gate off Windows, so on POSIX it also gave a name with a colon or a character below 32, a reserved device stem as the final name (`aux.py`), and a base under a volume or device prefix that `plain_spelling` does not remove; and it applied the pinned directory's child-name rule (a backslash, a trailing dot or space in the final name) on Windows only, for the last two. The class is the one round 3's A3 and B1 belong to: a spelling a listing offers that the verified reader's rules on the text refuse.
   14. §16 item 20 said that `reader_spelling` reads nothing, so that a listing's cost per match is unchanged. It calls no filesystem function, and it builds path objects and strings for each match (10,000 calls on one path: 0.161 s on the head, 0.254 s after this amendment, 0.0066 s for `plain_spelling`).

   **Found in review round 5 (Amendment 4), on `8c83093b`.** As properties of the head's decision:
   15. `reader_spelling` applied the verified reader's location gate to the file's text only. `read_verified_file` also gives the gate the file's direct parent (`pin_directory(candidate.parent)` opens it through `PinnedDirectory.open`, whose first statement after the already-open check is `validate_read_location(path)`), and the gate's `PureWindowsPath(raw).is_reserved()` test looks at the final component of the text it is given. So on a POSIX host a file whose direct parent is a reserved device name (as `PureWindowsPath.is_reserved` decides it) was listed, and the armed reader answered `read_file failed: invalid path`; a repeat of the read counts as a tool defect (reviewer A; the orchestrator's probe: 31,941 of 292,464 POSIX-shaped texts, each with a reserved direct parent, 0 misses). It is on the base and not a regression. T29 and T30 pinned the wrong answer for it, and D15 stated it. On Windows the chain rule of D14 already withheld these names (0 of 43,380 generated inputs differ between the head and M7).
   16. Three sentences of Amendment 3 overclaimed (reviewer B, B5-1; claims only): L19 said a name with an unpaired surrogate "cannot be carried as text in a result" (the delivery path escapes it; what refuses it is the reader's `raw.encode("utf-8", errors="strict")`, a `UnicodeEncodeError`), and D15 and SP12 said a name the reader refuses and the listing offers "is answered `invalid path`" (that sentence was itself false: what the armed reader answers is L22, measured).

   **Found in review round 6 (Amendment 5), on `bd67126a`.** As properties of the head's decision:
   17. `reader_spelling` gave a spelling to a path with no final name: a root. `PinnedDirectory._leaf` refuses an empty child name, and `read_verified_file` of such a path answers `FileAccessDenied: invalid child name` (§13f K1). The pattern `**` yields the base itself, so a listing from a root base names the root: with `Path.glob` yielding only the base, the real `list_files` of the drive root returned `{'files': ['C:\\']}` and the real reader refused that text (`probe_root_listing.py`). Reviewer A, P2, ordinary reach, on the base; the orchestrator's probe found it as 3 holes in 716,165 Windows-shaped texts and 1 in 716,164 POSIX-shaped ones.
   18. `reader_spelling` decided the file's direct parent and its final name on the text it was given. The reader decides on the candidate `validate_read_location` returns, which resolves a `..` part (`os.path.abspath`): `PinnedDirectory.open` is given the candidate's parent and `_leaf` the candidate's name (T37). For a text with a `..` part the two differ: natively on Windows the real reader refused `ok\..\con\g.txt` (its candidate is `con\g.txt`) and read `con\..\ok\g.txt` (its candidate is `ok\g.txt`), and `reader_spelling` gave `None` for both; with `os.name` set to `posix` the head listed `/data/con/sub/../g.txt` and `/data/aux.py/sub/../g.txt`, whose candidate's direct parent the gate refuses (`probe_noncanonical.py`; the orchestrator's probe: 2,774 POSIX-shaped holes). A listing cannot yield a `..` part: its pattern refuses one and its base is resolved (`ListFilesTool.invoke`). Reviewer A, P2, injected-only, on the base.
   19. Claims of Amendment 4 that were wrong or unmeasured (reviewers A and B, P3, introduced; and the orchestrator's cost measurement). T34 wrote the pinned directory's private storage and called its private method from outside the class (F2). The sentence that `invalid path` is answered only for a prefix, a drive or a device name was false and stood in five places (B6-1: a colon after the drive and a control character are answered `invalid path` too: L22). D15 and L18 said that T34 and the probe would fail at once if the reader gave the gate a third text, but both encode the sequence by hand and neither runs the reader (B6-3). BF-948's §17 item 6 named "G1 to G4, G5, G6" where G7 and G8 stood (B6-2). L20 said about 10 µs a match more; the time varies between runs and with the depth of the path, so L20 now states the call counts and one run's times, not a range. Two clauses nobody measured are deleted, not reworded: L19's "a workspace on a POSIX host that keeps timestamped names with a colon" and L18's "never another file's content".
   20. **Found in review round 7, on `76cfc985` (reviewer B, claims only; P3, ordinary reach, introduced by Amendment 5).** L22 said how `ReadFileTool` wraps the message and that no test pins one: a `FileNotFoundError` has its own handler (`tools.py` 495 to 496), and three assertions of the BF-953 file pin `invalid child name` (lines 1155, 1412 and 1431). L20 attributed the cost fixtures to path depths of 3, 7 and 12 parts, which hold 3, 9 and 13 by `len(Path.parts)`, and gave a range as if it were a bound. K13's command lacked the quotes around `".."` and found one of the two lines it names. Corrected by deleting the wrapper and test sentences, stating the call counts and one run's times instead of a range, and recording the command that was run.

## 2. Solution

- **M1:** `tests/test_bf953_read_floor_spellings.py`, written first. Every spelling case the base decides differently, and every test that calls a helper M2 adds, is `xfail(strict=True)`: red on the base, for the reason its mark names.
- **M2:** `_longest_match` decides containment on the namespace-free text of both sides and, for a path or root that still names a share or device, on the identity the operating system gives the file. Windows only. `resolve_read_path` returns the resolved path exactly as before. The marks come off.
- **M3:** trackers and the ledger. The tracker pairs only insert.
- **M4 (Amendment 1):** identity is a deny-only layer. The floor is decided by text, by the identity of the path's own chain, by the volumes the chain reaches through a link, and refuses when it cannot be read; an exempt or a permitted root is decided by text alone; precedence compares where a match stands in the path's own chain; the final component of a floor file root and of a credential name is compared by the file it names (D11); the two root builders resolve the workspace root; `plain_spelling` is the display form `list_files` uses (BF-948's M5). Tests T11 to T22, and T1 to T3, T7 and T10 change; the BF-953 tracker entries are amended in place.
- **M5 (Amendment 2):** a floor file root is compared by the file its own final component names, as a candidate is, by adding that file to the floor's root list (`_floor_roots`, D12); both root builders keep a workspace root the system cannot resolve as it was composed, through one helper (`_workspace_root`, D13); `reader_spelling` gives the spelling a listing may name for a match, or none (D14), which BF-948's M6 uses. T16, T19 and T20 change, T23 to T28 are new, the claims are corrected, and the BF-953 tracker entries are amended in place.
- **M6 (Amendment 3):** `reader_spelling` calls the verified reader's location gate and applies its child-name rule to the final name, before the Windows branch of D14, on every platform (D15); T29 to T33 are new and T26 is Windows-only; §16 item 20 and L18 are corrected, L19 and L20 are new, and the BF-953 tracker entries are amended in place. BF-948's M7 changes the `ListFilesTool` docstring and two comments.
- **M7 (Amendment 4):** `reader_spelling` gives the verified reader's location gate the file's direct parent as well as the file (D15), on every platform; T29 and T30 are corrected, T34 and T35 are new; L18 and L19 are amended, L20 has new numbers and L21 is new; the three claims of B5-1 are corrected, and the BF-953 tracker entries are amended in place. BF-948's M8 changes the `ListFilesTool` docstring.
- **M8 (Amendment 5):** two deny-only clauses in `reader_spelling`, before the Windows branch: a path with no final name (a root) and a path with a `..` part have no spelling (D15). T29 and T30 gain rows, T34 is rewritten on the public API (the gate and a real pinned directory's `read_bytes`; the corpus holds `..` parts, hidden names and roots), T36 and T38 (a root) and T37 (the texts the real reader gives its gate) are new. The class lists are deleted from D15, L18, L19, L21, §6, §16 and the trackers instead of reworded; L22 holds the one table of what the armed reader answers, with the output of the command that measured it (§13f); L20 is a measured range. The BF-953 tracker entries are amended in place. BF-948's M9 changes the `ListFilesTool` docstring, LF9, L19 and §17 item 6.

## 3. Decisions

Criteria order: correctness (every spelling of one file the floor refuses), safety (at the floor, nothing admitted that was refused; an exempt or a permitted root admits a spelling only if it admits the ordinary spelling of the same file), compatibility, architectural fit, cost, reversibility.

- **D1, how the decision is made. Chosen: D1-d**, ranked against the other three on the evidence of §1.

  | Rank | Option | Sets the property? | Legitimate network path | Long local path | Path that does not exist | POSIX | Cost |
  |---|---|---|---|---|---|---|---|
  | 1 | **D1-d** the namespace-free text, then file identity for a path or root that still names a share or device (Windows only) | yes, for all 20 probed spellings, and for any spelling the system resolves to the same file (host names, addresses, shares): the `ident` column of the probe matched every row in all three scenarios | stays admitted unless a root is the file or an ancestor of it by identity | the extended-prefix local path is decided on its text; the returned path keeps its prefix, so it still opens | the nearest ancestor on disk decides; a root not on disk is matched by text only | unchanged: the new branch is behind `os.name == "nt"` | none for a drive-letter path; for a share path one `os.stat` per ancestor, once per call |
  | 2 | **D1-a** a textual key as the write side's (`_write_key`) | the prefix forms only. It cannot name a machine's own names and addresses, and the write side leaves `//localhost/C$` apart from `C:` too (BF-911 adds identity for that) | unchanged | decided on its text | by text | the write side's rules (case folding, trailing dots and spaces dropped) would make distinct POSIX names equal, so a permitted root would admit more. They must not be applied there | none |
  | 3 | **D1-c** refuse a spelling that cannot be matched to a local drive | complete for local aliases, by refusing every share path | refused: a compatibility break. It needs an operator escape (a config list of admitted shares) with a default, and a default that admits leaves the property unset | the prefix form is matched to a drive by text and admitted | by text | unchanged | none |
  | 4 | **D1-b** the operating system's final path name | no: this is what `Path.resolve()` already asks. For a handle opened by a share spelling of the local drive, the final path name is the share path (DOS and NONE flags), the redirector's device path (NT flag) or a failure (GUID flag), and the extended prefix is kept when it was given | | | cannot be asked: the file must exist | | |

  D1-d is D1-a's pure text step first (the prefix forms need no I/O and cover a root that is not on disk) and the system's own answer to "is this the same file" second. D1-a alone is rank 2 because it leaves exactly the host-name spellings undecided. D1-c is rank 3 because it breaks legitimate network reads for a property D1-d reaches without that.
- **D2, what the function returns. Chosen: the resolved path, as before, in the spelling `Path.resolve()` gave it.** The decision is made on the namespace-free text and the identity; the return value is not rewritten. A rewritten path (the extended prefix dropped) can name a different file than the one decided on, and it can lose the prefix a long local path needs to open. So for every admitted call the path returned is a resolved path (`Path(returned).resolve() == Path(returned)`) in the spelling `Path(raw).resolve()` gave (relative paths resolved against `relative_base` as before), and it names the file the decision was about (T1; T9 pins the exact string for the ordinary and the extended spelling). `read_verified_file` and `read_bounded_utf8` compare the returned path with their own lexical candidate: they see exactly what they saw.
- **D3, operator escape. None.** No config field is added, and nothing that was admitted for a reason other than its spelling is refused: a path on another machine's share stays admitted when no floor root is, or contains, that file by identity (T10). An exempt or a permitted root admits a share or device spelling only if its text names it (D8), as a permitted root did on the base. D1-c is the only option that needs an escape, and it is not chosen.
- **D4, where the new branch runs.** `_longest_match` first tests containment as before. Only if that fails, on Windows, and only if the path or the root starts with two backslashes, does it compare the namespace-free keys (`PureWindowsPath`, case-insensitive), and only for the floor, and only if a key still has a drive that starts with two backslashes (a share, a volume or a device), does it compare identities (D8). A drive-letter path against drive-letter roots costs nothing more than before (T9). The function is `_match_position`; it returns where the deepest matching root stands in the path's own chain, not the root.
- **D5, identity.** `_file_identity(path)` is `(st_dev, st_ino)` from `os.stat`, or `None` when the system says there is no such file (`FileNotFoundError`, `NotADirectoryError`). It raises the private `_Unverifiable` when the system cannot say: any other `OSError`, a `ValueError`, or a filesystem that gives no file index (zero). `_OnDisk` holds, for the path and every ancestor of it that is on disk, the identity and the part's count of parts without a namespace prefix (the deepest part wins a repeated identity) and the volumes the chain reaches other than that of its topmost part; it is read once per `resolve_read_path` call and only when the floor first asks. A floor root contains the path when its identity is one of those (it stands at that count), or when the chain reaches the root's volume (it stands at the path's own count); this covers a file root (a config file) and a directory root alike. `resolve_read_path` turns `_Unverifiable` into `FileAccessDenied` with the reason `path cannot be verified against the protected roots`, and logs the class of the cause only.
- **D6, compatibility, and how it is tested.**
  - On another platform the new branch never runs: decisions and return values are those of the base (T8 pins the POSIX names that must stay distinct: case, trailing dot and space, backslashes in a name).
  - On Windows a drive-letter path decided against drive-letter roots gets the same decision, the same return value and no extra I/O (T9, T1's ordinary rows).
  - Every admitted call returns what it returned (T1, T9). The only decisions that change are those of the spellings in §1: the 9, and the trailing space for a file that is not on disk (T1 to T4, red on the base in M1). After Amendment 1 a share spelling is also refused where only an exempt or a permitted root admitted the ordinary spelling (T1 to T3), a spelling the floor cannot be read for is refused (T12), and the final component of a floor file root and of a credential name is compared by the file it names, so a stream, trailing-dot, trailing-space or (for a credential name) case spelling of one is refused as the file is, on disk or not (D11; T19 to T21). The share spelling of a floor file root that is not on disk is the exception (L2).
  - A path no root covers stays admitted, and a root that is not on disk is matched by text only (T10).
- **D7, fences.** M1 to M4 of BF-953 change neither `src/probos/cognitive/swe_harness/tools.py` nor `tests/test_bf948_list_files_read_policy.py`. BF-948's M4 (committed) edited both by SEARCH; BF-948's M5 (Amendment 2) edits both again, after BF-953's M4, for the display form (D10). This contract's tests import seven names from the BF-948 test file's head (`_OUTSIDE`, `_PROTECTED`, `_link`, `_list`, `_runtime`, `_scene`, `_unlink`) and do not edit it; if BF-948 renames any, that is BF-948's amendment to carry.
- **D8, identity is a deny-only layer (Amendment 1; review round 2 findings 1 to 3). Chosen: S.**

  | Rank | Option | Allow-list never admits more than the ordinary spelling | Floor decides every spelling alike | Cost |
  |---|---|---|---|---|
  | 1 | **S**: the floor by text, by the identity of the path's own chain, by the volumes the chain reaches through a link, and refuses when it cannot be read; exempt and permitted roots by text alone; precedence by position in the path's own chain | by construction | for every spelling whose own chain names a floor root or reaches its volume, or cannot be read (L10 to L12 name the rest) | drive spelling 0; share or device spelling: the floor roots and one `os.stat` per part, once per call; allow-lists 0 |
  | 2 | **T**: identity for allow-lists too, with per-step reparse, mount and volume checks, a path-relative depth and a tri-state identity | holds as far as every transition is observable; the system gives a share spelling no physical path | as S | two per part per allow-list root, plus S's |
  | 3 | **U**: map a local share spelling to its drive-letter spelling and decide by text | for the mapped names only | needs S for aliases and device forms | S's plus the mapping's |
  | 4 | **D1-c**: refuse every share or device spelling no root names | holds | holds | 0; breaks a legitimate remote read, needs an escape |

  S is chosen on correctness (findings 1 to 3 cannot occur: nothing an allow-list admits depends on identity), safety (identity adds refusals only), cost (no identity read for an allow-list root) and the number of surfaces a reviewer must re-check. The floor's three rules are exactly the properties the probes exposed: the chain's identity (a floor root is one of its parts), the chain's volumes (the head and the base admitted the share spelling of a link into a floor root's interior), and the unreadable floor (finding 3). Precedence is a count of the path's own parts: an exemption stands where its text puts it, whatever its root's spelling (finding 2; T13, T16). **Compatibility:** a share spelling of the agent workspace was admitted on the base and by identity on the head, and is refused now; a share spelling of a permitted path was refused on the base and is still refused; no other admission is removed.
- **D9, the roots the builders compose (Amendment 1; finding 5).** `permitted_read_roots` and `workspace_exempt_roots` return `_resolve_workspace_root(workspace).resolve()`, as the candidate is resolved, so a root configured as an 8.3 short path, an unresolved data directory or a mapped drive is spelled as the paths under it are. `WorkspaceManager`, `_resolve_workspace_root` and `tools.py`'s private-result detector (which keeps the lexical root beside the resolved one) are unchanged.
- **D10, the display form of a listing (Amendment 1; finding 4 and the second reviewer's R4).** The policy admits an extended-prefix spelling and returns it as resolved (D2). The armed reader rejects that prefix lexically. `file_access.plain_spelling` (public, pure, Windows only) gives the spelling without the prefix the armed reader rejects, and `ListFilesTool` lists with it where `reader_spelling` gives one (BF-948's M5; D14 and D15 decide the rest). **The display form is applied before the test against the project tree**, so a base inside `src/` lists project-relative names whether it is spelled ordinarily or with an extended prefix (BF-948 T14); a share spelling of a local directory is listed by its absolute share spelling, which the verified reader opens too (BF-948 L18). Rejected: widening the reader's validator (shared by instruction reads and the pinned-directory code); relativising by file identity (more surface for one spelling); a recorded limit with a test that pins the failure.
- **D11, the final component names the file (Amendment 1; the second reviewer's R3 and R6). Chosen: compare the base file.** On Windows a final component that carries a stream (`name:stream`, `name:stream:$DATA`, `name::$DATA`) or ends in dots or spaces names the same file as its base `name`. A floor file root and a credential file name are therefore compared by the base file, by text, whether or not the file is on disk. `_base_name(name)` drops the text from the first colon and then the trailing dots and spaces (a name that would be empty stays as it is); `_base_file(path)` applies it to the final component; `_protected_leaf(path)` compares the credential names in the write side's canonical form (`_canonical_name`, case-folded, the key `_write_key` uses). The path an admitted read returns is the path as resolved, so a stream of an ordinary neighbour is read as named. It is applied once in `resolve_read_path`, before the identity step: the credential check, the on-disk chain and the floor comparison use the base file; the exempt and permitted comparisons use the path as resolved. It is pure text and adds no `os.stat` (T9). On another platform the names are compared as they are (T22). **Rejected:** refusing every name that carries a colon or ends in a dot or a space (a neighbour's stream is the caller's own file); looking the file up on disk and comparing identities (an absent file has no identity, so R6's absent file roots would stay open); changing `_write_key` (the write side's coverage is BF-911's; T20 pins that it refuses the same stream name). **Over-refusal:** L14. **Reach:** L15.
- **D12, a floor file root is compared by the file it names (Amendment 2; round 3's A1). Chosen: add the base file of each root next to it.** `_floor_roots(roots)` returns the roots as they are spelled, each followed by `_base_file(root)` when that is another spelling; `resolve_read_path` compares the candidate's base file with that list. A root whose final component names itself (every directory root a system resolves, an ordinary file root, and every root on another platform) adds nothing, so every decision against an ordinary root list is the head's (T24). **Effects.** A configuration loaded as `loaded.yaml:settings` refuses its own spelling, the ordinary spelling of the file, its default stream and every other stream of it (T23, T28); a position count is the root's own count of parts, so no exemption's rank changes (T27); the identity step is handed the added root and reads at most one more `os.stat` for a share or device spelling (L4); a directory root spelled in the extended namespace with a trailing dot or space also refuses the directory its base names (L16). **Rejected:** replacing the root by its base file (a floor directory spelled `dir.` in the extended namespace would stop being refused: a new admission); reducing in `protected_config_files` (its result is the write side's list, and it would change BF-911's stat loop); reducing only the stream suffix (a trailing dot or space on a file root is the same class).
- **D13, the workspace root as composed (Amendment 2; round 3's A2). Chosen: one helper.** `_workspace_root(runtime)` composes the root as the builders did and resolves it as a candidate is. When `resolve()` raises `OSError`, `RuntimeError` or `ValueError` it returns the root as composed; when the root cannot be composed it returns `None`. `permitted_read_roots` and `workspace_exempt_roots` use it, so a configured policy whose own roots are unusable still has the workspace root in its list, and the exempt list holds the same root, which no candidate is under (the base's two lists). **Recorded, not repaired (L17):** a configured policy whose every root is unusable and whose workspace root cannot be composed at all is `[]`, which every consumer reads as "no limit"; on the base the same two failures give the same list. A fail-closed form needs a root that matches nothing in a list whose emptiness now means "none configured" (seven call sites in five modules, and `reads_confined`): a change to that list's contract, not to this finding.
- **D14, the spelling a listing may name (Amendment 2; round 3's A3 and B1). Chosen: a textual rule, `reader_spelling`.** `file_access.reader_spelling(path)` (public, pure) is `plain_spelling(path)` when the verified reader's rules on the text admit it (D15) and, on Windows, when every component of it after its anchor names, as an ordinary path, what it names in the extended namespace, and `None` otherwise. A component fails if it ends in a dot or a space (the system drops both from an ordinary path), or if any part of the spelling, the final component or an ancestor, is a reserved device name (`PureWindowsPath.is_reserved`, the test the verified reader applies to the file and to the directory it pins: the rule here is wider than the reader's text path wherever a reserved name or a trailing dot or space stands above the direct parent, L21). It applies to a path that never had a prefix too, so it holds for an ordinary base. It completes D10: `plain_spelling` stays the first step, and `ListFilesTool` lists the spelling only where `reader_spelling` gives one (BF-948's M6), leaving a match with none out like a match the policy refuses. **Rejected:** an identity rule (for an ordinary base the match string already is the ordinary alias, so the namespace-preserved identity needs the lister to build the extended spelling itself, at two `os.stat` per match; a volume that reports file index 0 would empty every listing); the verified reader's own `validate_read_location` as the only gate (it checks the final component only, so a file in a directory named `con` passes it and the reader still fails: the textual chain rule stays; Amendment 3 adopts the gate as the first step, D15). **Cost:** no filesystem call per match; the work D15 adds per match is path objects and strings (L20).
- **D15, the verified reader's functions on the text (Amendments 3 to 5; rounds 4 to 6). Chosen: `reader_spelling` gives a spelling only where the verified reader's own functions admit the text of the file, on every platform, before the Windows rule of D14.** The functions are `validate_read_location`, called as it is on the file's text and on the text of the file's direct parent (the two texts `read_verified_file` gives it: the call list is §13f K2, and T37 records it from the real reader), and the final-name rule of `PinnedDirectory._leaf`, which the function restates in conditions (§13f K3 prints the reader's clauses and the function's) and which T31, T34 and T36 read back from a real pinned directory. A `ValueError` from either call (`UnicodeEncodeError` is one) gives `None`. A path with no final name gives `None`: `_leaf` refuses the empty name. A path with a `..` part gives `None`: the reader decides on the candidate `validate_read_location` returns, which resolves `..`, and a listing's paths have none (the pattern refuses `..` and the base is resolved, `ListFilesTool.invoke`), so the clause only keeps the function's stated input honest (round 6's F3). The gate is called, so a later change of it reaches the listing; what the armed reader answers for a refused text is L22; what a listing does not promise is L18; what only the plain reader opens is L19. **Whose rules.** A listing follows the verified reader's rules, not the plain reader's, because the lister cannot know which reader the next read uses: `ReadFileTool` and `CodebaseReadSourceTool` choose per call on `_read_context(context)` (`tools.py:292`), whose key `_workspace_read` the loop sets (`agentic_loop.py:2642`) from the run's delivery run for the two reader tools only (`result_offload.py:76`, `:305`); a `list_files` call is not one, and sharing the test would put the delivery state into a call to a tool that is not a reader (AD-1240's surface). **Rejected:** strict UTF-8 only (the reviewers' smallest fix in round 4: it leaves the gate's other refusals listed); the gate on the file alone (it leaves the direct parent's gate and the final-name rule: rounds 4 and 5); deciding the parent and the name from the candidate the gate returns instead of denying `..` (round 6's option iii: the function would return a text the reader does not read, and a derived path object cannot be built for a patched `os.name`, so the POSIX shape could not be tested on a Windows host); asking the loop (above); answering the reader's lexical refusal as a caller-input error (BF-948 L17: it changes the classification, not the listing); a public function the reader and the lister both call (it edits the armed reader, which other callers use: `copilot_adapter.py`, two sites of `tools.py`, and `workspace_result_store.py`'s `pin_directory` calls; the drift guards are T34's corpus, T37's recorded sequence and the probes, and a change of the reader's sequence fails T37, after which `reader_spelling`, T34's oracle and the probes are audited by hand: L21); a table of reserved names in the lister; gating every ancestor (the reader gives its gate none: L21).

## 4. Milestones and gates

| M | Tier | Why | Pairs | Gate |
|---|---|---|---|---|
| M1 | STANDARD | test only, no `src`; its strength is the strict xfails failing on the base for the reason they name, and the premise asserts | B1-1 | G1 |
| M2 | HIGH | a public function's decisions for every consumer (the read floor) | B2-1 to B2-11 | G2 |
| M3 | STANDARD | trackers | B3-1, B3-2, the ledger | G3 |
| M4 | HIGH | Amendment 1: the same public function's decisions for every consumer (identity deny-only, precedence, the root builders), its tests, and the in-place tracker amendments | B4-1, B4-2, B5-1, B5-2 | G5 |
| M5 | HIGH | Amendment 2: the same public function's decisions for every consumer (a floor file root by its file), the root builders' fallback, a new public function the lister asks, its tests and the in-place tracker amendments | B6-1, B6-2, B7-1, B7-2 | G6 |
| M6 | HIGH | Amendment 3: the decisions of the one public function the lister asks (the verified reader's rules on the text, on every platform), its tests, the in-place tracker amendments, and BF-948's M7 docstring (P8-1) | B8-1, B8-2, B9-1, B9-2 | G7 |
| M7 | HIGH | Amendment 4: the decisions of the one public function the lister asks (the direct parent's gate, on every platform), its tests, the in-place tracker amendments, and BF-948's M8 docstring (P9-1) | B10-1, B10-2, B11-1, B11-2 | G8 |
| M8 | HIGH | Amendment 5: the decisions of the one public function the lister asks (a root and a `..` part have no spelling), its tests (T34 rewritten on the public API, T36 to T38 new), the class lists deleted, the in-place tracker amendments, and BF-948's M9 docstring (P10-1) | B12-1, B12-2, B13-1, B13-2 | G9 |

Run each gate command as one file at a time with `-n 0`.

- **G1 (red).** `d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_bf953_read_floor_spellings.py -q -n 0`. Expected on a Windows host that serves every spelling (measured on this one, scratch copy of `728e1fc2`, home-guarded): **42 passed, 61 xfailed, 2 skipped, 0 failed** (105 tests: T1 to T4 are 20 cases each; the two skips are T3's stream-suffix case, a file-only spelling, and T8, POSIX only). On the `ubuntu-latest` runner, derived from the file (not run: this host is Windows): **1 passed (T8), 22 xfailed (T5, T6, T7), 82 skipped (every Windows-only case)**. Any other count, or an XPASS, is a hard stop back to the Architect. `--runxfail` shows each red for its marked reason: `AttributeError` for the missing helpers (T5, T6, T7, T9, T10) and an `AssertionError` naming the spelling and the decision for the 37 family cases.
- **G2 (green).** After M2: the same file, **103 passed, 2 skipped, 0 failed, 0 xfailed** (this host, scratch copy of `728e1fc2` with M1 and M2 applied from this contract's blocks; on the Linux runner, derived: 23 passed, 82 skipped). Then, one file at a time with `-n 0`, each unchanged by BF-953: `tests/test_bf758_file_read_confinement.py` (24 passed, 1 skipped), `tests/test_bf908_floor_and_children.py` (39 passed, 1 skipped), `tests/test_bf911_protected_config_write_refusal.py` (119 passed), `tests/test_bf948_list_files_read_policy.py` (17 passed), `tests/test_ad1200_instruction_file_access.py` (40 passed), `tests/test_ad1200_repository_instructions.py` (98 passed), `tests/test_ad1316_real_effect_routes.py` (67 passed, 2 skipped). Expected: those counts, 0 failed. Then `d:/ProbOS/.venv/Scripts/python.exe -P scripts/check_architecture_principles.py --check`.
- **G3.** `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py`; `... scripts/gen_ad_ledger.py --check`; `... -m pytest tests/test_ad1184_ad_ledger.py -q -n 0`. Expected: the generator rewrites `docs/development/open-ads-report.md` and `docs/development/ad-ledger-snapshot.json` (stage what it writes), `--check` says the ledger is current, and the test file gives **33 passed**. Run the test only after the regeneration: before it the file fails with "open-ads-report.md is stale".

- **G5 (M4).** Red first: apply B4-2 only (the test file), then `d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_bf953_read_floor_spellings.py -q -n 0`. Expected on a Windows host that serves every spelling and has a second local volume (measured on this one, scratch copy of `d1aba238`, home-guarded): **57 failed, 100 passed, 3 skipped** (160 tests). The 57: T1 7 (the six share families and `default stream suffix`), T2 6, T3 6, T7, T10, T11, T12 (2), T13 `device`, T14, T15 (6), T17 `device`, T18 (13), T19 (5: `:zz`, `:zz:$DATA`, `.`, a space, `. `), T20, T21 (5: `swapped case`, `trailing dot`, `trailing space`, `default stream`, `named stream`). Any other count is a hard stop back to the Architect. Green: apply B4-1, rerun: **157 passed, 3 skipped, 0 failed**. On the `ubuntu-latest` runner, derived from the file (not run: this host is Windows): **49 passed, 111 skipped** (T5, T6, T7, T8, T15, T16, T18 and T22 run; every other case is Windows-only). Then, one file at a time with `-n 0`, each unchanged by M4: `tests/test_bf758_file_read_confinement.py` (24 passed, 1 skipped), `tests/test_bf908_floor_and_children.py` (39 passed, 1 skipped), `tests/test_bf911_protected_config_write_refusal.py` (119 passed), `tests/test_ad1200_instruction_file_access.py` (40 passed), `tests/test_ad1200_repository_instructions.py` (98 passed), `tests/test_ad1316_real_effect_routes.py` (67 passed, 2 skipped), and `tests/test_bf948_list_files_read_policy.py` (30 passed before BF-948's M5, 32 after). Then `d:/ProbOS/.venv/Scripts/python.exe -P scripts/check_architecture_principles.py --check` (expected `architecture fitness check passed (srp-size=92, layer-import=0, db-connect=30, unowned-task=13)`). After B5-1 and B5-2, G3's three ledger commands.

- **G6 (M5).** Red first: apply B6-2 only (the test file), then `d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_bf953_read_floor_spellings.py -q -n 0`. Expected on a Windows host that makes named streams (measured on this one, scratch copy of `34bd9153`, home-guarded): **33 failed, 162 passed, 3 skipped** (198 tests). The 33: T23 4, T24 4, T25, T26 23, T28. T27 and the changed T16, T19 and T20 pass on the head: they pin what the head does, and §10's R3M rows show they kill. Any other count is a hard stop back to the Architect. Green: apply B6-1, rerun: **195 passed, 3 skipped, 0 failed**. On the `ubuntu-latest` runner, derived from the file (not run: this host is Windows): **77 passed, 121 skipped** (T5, T6, T7, T8, T15, T16, T18, T22, T24, T25 and T26 run; every other case is Windows-only). Then, one file at a time with `-n 0`, each unchanged by M5: `tests/test_bf758_file_read_confinement.py` (24 passed, 1 skipped), `tests/test_bf908_floor_and_children.py` (39 passed, 1 skipped), `tests/test_bf911_protected_config_write_refusal.py` (119 passed), `tests/test_ad1200_instruction_file_access.py` (40 passed), `tests/test_ad1200_repository_instructions.py` (98 passed), `tests/test_ad1316_real_effect_routes.py` (67 passed, 2 skipped), and `tests/test_bf948_list_files_read_policy.py` (32 passed before BF-948's M6, 34 after). Then `d:/ProbOS/.venv/Scripts/python.exe -P scripts/check_architecture_principles.py --check` (expected `architecture fitness check passed (srp-size=92, layer-import=0, db-connect=30, unowned-task=13)`, the same counts as G5). After B7-1 and B7-2: `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py --check` (expected `AD/BF ledger is current`; do not regenerate: the heads are unchanged, and a regeneration would only rewrite the captured git head and time) and `tests/test_ad1184_ad_ledger.py` (33 passed).

- **G7 (M6).** Red first: apply B8-2 only (the test file), then `d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_bf953_read_floor_spellings.py -q -n 0`. Expected on a Windows host (measured on this one, scratch copy of `a0857b08`, home-guarded): **18 failed, 221 passed, 4 skipped** (243 tests). The 18: T29 7 (the three surrogate rows, the two colon rows, the newline row, the character below 32 in an ancestor), T30 9 (colon, timestamp, newline, reserved stem, backslash, trailing dot, trailing space, `surrogateescape`, relative spelling), T33 2. T31 and T32 pass on the head: they pin the final-name rule against the pinned directory and the absence of a filesystem call, and R4M-13 and R4M-10 show they kill. Any other count is a hard stop back to the Architect. Green: apply B8-1 and P8-1, rerun: **239 passed, 4 skipped, 0 failed** (the 4: the default-stream premise, the two POSIX-only name tests, T31's backslash row). Then, one file at a time with `-n 0`, each unchanged by M6: `tests/test_bf758_file_read_confinement.py` (24 passed, 1 skipped), `tests/test_bf908_floor_and_children.py` (39 passed, 1 skipped), `tests/test_bf911_protected_config_write_refusal.py` (119 passed), `tests/test_ad1200_instruction_file_access.py` (40 passed), `tests/test_ad1200_repository_instructions.py` (98 passed), `tests/test_ad1316_real_effect_routes.py` (67 passed, 2 skipped), `tests/test_bf948_list_files_read_policy.py` (34 passed), and the 14 files of BF-948's G4 (**1340 passed, 3 skipped** in all). Then `d:/ProbOS/.venv/Scripts/python.exe -P scripts/check_architecture_principles.py --check` (expected `architecture fitness check passed (srp-size=92, layer-import=0, db-connect=30, unowned-task=13)`). After B9-1 and B9-2: `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py --check` (expected `AD/BF ledger is current`; do not regenerate: the heads are unchanged) and `tests/test_ad1184_ad_ledger.py` (33 passed). **Not run:** a POSIX host (no count is derived for it; T29, T30 and T31 run there, and T30's rows ran here with `os.name` set to `posix`).

- **G8 (M7).** Red first: apply B10-2 only (the test file), then `d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_bf953_read_floor_spellings.py -q -n 0`. Expected on a Windows host (measured on this one, scratch copy of `8c83093b`, home-guarded): **3 failed, 243 passed, 4 skipped** (250 tests). The 3: T30 2 (a reserved device name and a reserved device stem as the direct parent), T34 1 (the POSIX shape: 258 listed texts the reader's text path refuses). T29's new rows, T34's Windows shape and T35 pass on a Windows head: the chain rule of D14 already covers the direct parent there; they are checks of the seam, and R5M-1 to R5M-9 and R5M-T1 to R5M-T3 show what they kill. Any other count is a hard stop back to the Architect. Green: apply B10-1, rerun: **246 passed, 4 skipped, 0 failed** (the 4: the default-stream premise, the two POSIX-only name tests, T31's backslash row). Then, one file at a time with `-n 0`, each unchanged by M7: `tests/test_bf758_file_read_confinement.py` (24 passed, 1 skipped), `tests/test_bf908_floor_and_children.py` (39 passed, 1 skipped), `tests/test_bf911_protected_config_write_refusal.py` (119 passed), `tests/test_ad1200_instruction_file_access.py` (40 passed), `tests/test_ad1200_repository_instructions.py` (98 passed), `tests/test_ad1316_real_effect_routes.py` (67 passed, 2 skipped), `tests/test_bf948_list_files_read_policy.py` (34 passed), the 14 files of BF-948's G4 (**1340 passed, 3 skipped** in all) and `tests/test_ad1179_tool_schema_golden.py` (27 passed). Then `d:/ProbOS/.venv/Scripts/python.exe -P scripts/check_architecture_principles.py --check` (expected `architecture fitness check passed (srp-size=92, layer-import=0, db-connect=30, unowned-task=13)`). After B11-1 and B11-2: `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py --check` (expected `AD/BF ledger is current`; do not regenerate: the heads are unchanged) and `tests/test_ad1184_ad_ledger.py` (33 passed). **Not run:** a POSIX host (no count is derived for it; T29, T30, T31, T32, T34's POSIX shape and T35 run there; T35 is the first test of this contract to cross the seam natively on POSIX, and its first POSIX run is `ubuntu-latest`).

- **G9 (M8).** Red first: apply B12-2 only (the test file), then `d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_bf953_read_floor_spellings.py -q -n 0`. Expected on a Windows host (measured on this one, scratch copy of `bd67126a`, home-guarded): **9 failed, 251 passed, 4 skipped** (264 tests). The 9: T30 4 (a filesystem root; a '..' that leaves a reserved device name, a reserved device stem and an admitted name), T34 2 (both shapes), T36 2, T38 1. T29's three `..` rows, T30's other two new rows, T37 and T34's remaining checks pass on a Windows head: D14's rule already withholds a `..` part, and T37 records the reader, which M8 does not change; the R6M rows show what they kill. Any other count is a hard stop back to the Architect. Green: apply B12-1, rerun: **260 passed, 4 skipped, 0 failed** (264 tests; the 4: the default-stream premise, the two POSIX-only name tests, T31's backslash row). Then, one file at a time with `-n 0`, each unchanged by M8: `tests/test_bf758_file_read_confinement.py` (24 passed, 1 skipped), `tests/test_bf908_floor_and_children.py` (39 passed, 1 skipped), `tests/test_bf911_protected_config_write_refusal.py` (119 passed), `tests/test_ad1200_instruction_file_access.py` (40 passed), `tests/test_ad1200_repository_instructions.py` (98 passed), `tests/test_ad1316_real_effect_routes.py` (67 passed, 2 skipped), `tests/test_bf948_list_files_read_policy.py` (34 passed), the 14 files of BF-948's G4 (**1340 passed, 3 skipped** in all) and `tests/test_ad1179_tool_schema_golden.py` (27 passed). Then `d:/ProbOS/.venv/Scripts/python.exe -P scripts/check_architecture_principles.py --check` (expected `architecture fitness check passed (srp-size=92, layer-import=0, db-connect=30, unowned-task=13)`) and `git diff --check`. After B13-1 and B13-2: `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py --check` (expected `AD/BF ledger is current`; do not regenerate: the heads are unchanged) and `tests/test_ad1184_ad_ledger.py` (33 passed). **Not run:** a POSIX host (no count is derived for it; T29, T30, T31, T32, T34's POSIX shape, T35, T36's first row and T37 run there, and their first POSIX run is `ubuntu-latest`).

The broad gate runs once for the batch (BF-948, BF-953), after the Diff Reviewer's repairs: `d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --label bf948-bf953 --receipt logs/gates/bf948-bf953.receipt.json`. Not run here.

## 5. Commit messages

- M1: `BF-953 M1: reproductions of one file decided differently by spelling`
- M2: `BF-953 M2: the read floor decides every spelling of one file the same way`
- M3: `BF-953 M3: trackers and ledger`
- M4: `BF-953 M4: identity only ever adds a refusal at the floor, and an exemption is ranked by where it stands in the path`
- Amendment 2 (the contract only): `BF-953 (#1752): Amendment 2 to the build contract after review round 3 (M5: floor roots by their file, the workspace root as composed, the spelling a listing may name)`
- M5: `BF-953 M5: a floor file root is compared by the file it names, an unresolvable workspace root keeps the policy, and a listing spelling must name the file`
- Amendment 3 (the contract only): `BF-953 (#1752): Amendment 3 to the build contract after review round 4 (M6: a listing follows the verified reader's rules on the text)`
- M6: `BF-953 M6: a listing names only a spelling the verified reader's rules on the text admit`
- Amendment 4 (the contract only): `BF-953 (#1752): Amendment 4 to the build contract after review round 5 (M7: the direct parent's gate)`
- M7: `BF-953 M7: a listing names only a spelling the armed reader's text path admits`
- Amendment 5 (the contract only): `BF-953 (#1752): Amendment 5 to the build contract after review round 6 (M8: no spelling for a root or a '..' part; the class lists replaced by one measured table)`
- M8: `BF-953 M8: a listing names no root and no path with a '..' part`

## 6. Tests (`tests/test_bf953_read_floor_spellings.py`)

BF-953 owns every spelling test. A Windows-only case is skipped off Windows, and on Windows a spelling the host does not serve is skipped after its premise (`os.path.samestat` of the spelling and the ordinary path) fails, so a skip is never a pass. The families are one list (`_FAMILIES`); the spellings are built from the fixture path by `_spellings`.

| Id | Test | Covers | xfail until |
|---|---|---|---|
| T1 | `test_every_spelling_gets_the_decision_of_the_ordinary_spelling` (20 families) | floor (directory root, file root), exempt over floor, permitted, a file that is not on disk (a missing child of each root, an absent file root, and the missing default-stream case, each explicit), the path returned. **The 6 share families (`_SHARE_FAMILIES`) get the ordinary decision for the floor and the same refusal where the ordinary spelling is refused; where only an exempt or a permitted root admits the ordinary spelling they are refused, with that root's reason (Amendment 1, D8)** | M2, for the 9 families of §1 and, for a file not on disk, the trailing space (10); M4 changes the 6 share families' expectation |
| T2 | `test_read_file_decides_every_spelling_alike` (20) | consumer: `ReadFileTool`; a share family of a permitted file is answered `outside every readable root` | M2, the same 9; M4 as T1 |
| T3 | `test_list_files_decides_every_spelling_of_a_directory_alike` (20) | consumer: `ListFilesTool` on BF-948's rig; premise: the ordinary spelling is refused first; a share family of the permitted root and of the workspace is refused | M2, the same 9; M4 as T1 |
| T4 | `test_the_read_floor_refuses_every_spelling_of_a_config_file_the_write_side_refuses` (20) | write-side parity | M2, the same 9 |
| T5 | `test_the_namespace_free_form` (15 cases, any platform) | the pure canonicaliser | M2 (helper) |
| T6 | `test_the_namespace_free_form_agrees_with_the_write_sides_key` (any platform) | write-side parity, pure | M2 (helper) |
| T7 | `test_file_identity_is_the_file_the_system_names` (any platform) | the identity helper: one identity per file, `None` only for "no such file" (also under a file), `_Unverifiable` for a rejected name, a refused read and the zero index | M2 (helper); M4 changes the failure expectations |
| T8 | `test_a_posix_name_keeps_what_a_permitted_root_admits` (POSIX only) | nothing widens on POSIX | none: passes on the base |
| T9 | `test_a_drive_letter_path_costs_no_identity_lookup` (Windows) | compatibility; no extra I/O | M2 (helper) |
| T10 | `test_a_share_path_no_root_covers_stays_admitted` (Windows) | `_match_position` with the system's answers replaced: a legitimate network path no floor root covers stays admitted; a part of the chain that is the root, the deepest part and the deepest root win; a chain on the root's volume only through a link is inside at its own count; a root on the volume of the chain's top, on a volume the chain never reaches, or not on disk contains nothing; an exempt or permitted root is matched by text only | M2 (helper); M4 rewrites it |
| T11 | `test_a_share_spelling_is_never_admitted_by_a_root_its_text_does_not_name` (Windows, second local volume) | finding 1: a share spelling through a link to another volume, under a permitted root, refused as the ordinary spelling is; through the floor, a link into the interior of a floor root on that volume refused; a share spelling no floor root can contain still admitted; through `read_file` and `list_files` too (the second reviewer's R2) | M4 |
| T12 | `test_a_floor_that_cannot_be_read_refuses_a_share_spelling_and_nothing_else` (2, Windows) | finding 3: the floor root's read refused, or reporting index 0, while a permitted root's identity is real: the share spelling is refused with the bounded reason through the policy and through `ReadFileTool`; the ordinary spelling and a drive-letter path outside the floor are unchanged | M4 |
| T13 | `test_an_exemption_stands_where_its_text_puts_it_in_the_path_not_where_its_root_is_spelled` (4, Windows) | finding 2: an exempt root naming the floor directory or its parent as a device, extended-prefix, share or extended-UNC spelling lifts nothing, for an ordinary or a share candidate and through the configured workspace root; the workspace under the floor still lifts it, spelled with an extended prefix too | M4 |
| T14 | `test_a_workspace_root_configured_as_a_short_path_is_spelled_as_its_candidates_are` (Windows) | finding 5: both builders return the long resolved path; the workspace is admitted | M4 |
| T15 | `test_the_plain_spelling_drops_the_namespace_prefix_on_windows_only` (6, any platform) | `plain_spelling` | M4 |
| T16 | `test_a_namespace_free_root_stands_at_the_same_count_of_parts` (6, any platform) | dropping a namespace prefix changes no count of parts: a property of the text alone, which shows that a text match's count is the same number however the prefix is spelled and kills no mutant of `_match_position` (T27 pins the use of the count) | none: passes on the head |
| T17 | `test_a_loaded_config_file_outranks_the_workspace_that_encloses_it` (6, Windows) | the second reviewer's R1: the loaded config file inside the exempt workspace is refused in its ordinary, extended, device and share spellings however the workspace root is configured (ordinary, extended, device, share, extended UNC, a link to the data directory); `read_verified_file` and `read_bounded_utf8` refuse it too; a workspace file beside it is admitted unless the root names the data directory | M4 (red on the head for the device-spelled root) |
| T18 | `test_the_base_name_of_a_final_component` (13, any platform) | `_base_name`: the text from the first colon, then trailing dots and spaces, are dropped; a name that would be empty stays | M4 (helper) |
| T19 | `test_a_stream_or_trailing_dot_or_space_spelling_of_a_floor_file_is_decided_as_the_file_is` (6, Windows) | R3: a named stream, a stream with its type, the default stream, trailing dots and spaces of the config file and of a credential name are refused with the file's own reason in the ordinary, extended and share spellings; a neighbour with the same suffix is admitted, and the path returned is the one `Path.resolve()` spells for it (Amendment 2: it asserted admission only) | M4 |
| T20 | `test_a_named_stream_of_a_floor_file_is_refused_and_one_of_a_neighbour_is_read` (Windows) | R3 through `ReadFileTool` with real streams: the config file's and a credential name's streams are refused and give no content; the write side refuses the same name; a neighbour's stream is read as named, and `resolve_for_runtime` keeps the stream's name (Amendment 2) | M4 |
| T21 | `test_an_absent_file_root_and_an_absent_credential_name_are_decided_in_every_spelling_alike` (8, Windows) | R6: an absent floor file root and an absent credential name are refused in each final-component spelling and in the extended and device prefixes (the share spelling of an absent file root is L2); an absent neighbour is admitted | M4 |
| T22 | `test_a_posix_name_that_differs_by_case_dot_space_or_colon_is_another_file_for_the_floor` (POSIX only) | on POSIX the final component is compared as it is | M4 (derived, not run: this host is Windows) |
| T23 | `test_a_floor_file_root_spelled_with_a_suffix_is_decided_as_its_file_is` (4, Windows) | round 3's A1: a floor file root with a stream suffix (a configuration loaded as a stream) or, in the extended namespace, a trailing dot or space refuses its own spelling, the ordinary spelling of its file, the default stream, another stream and the extended prefix with the floor's reason; a neighbour with the same suffix is admitted | M5 |
| T24 | `test_the_floor_roots_include_the_file_each_final_component_names` (4, any platform) | `_floor_roots`: each root stays as spelled and its base file follows it where that is another spelling; an ordinary list is unchanged; on another platform nothing is added | M5 (helper) |
| T25 | `test_a_workspace_root_that_does_not_resolve_stays_in_the_read_policy_as_it_was_composed` (any platform) | round 3's A2: the unresolvable workspace root stays in both builders as composed; a configured policy with usable or unusable own roots still refuses a path outside them through the policy, `read_file` and `list_files`; the exempt list lifts nothing for it | M5 |
| T26 | `test_the_reader_spelling_is_one_that_names_the_file_in_the_ordinary_namespace` (23, Windows) | round 3's A3 and B1 (Windows only since round 4): `reader_spelling` gives the plain spelling, or none for a component that ends in a dot or a space or for a reserved device name in the final component or an ancestor; a name that only starts or ends like a device name keeps its spelling; the rules that apply on every platform are T29 to T31 | M5 (helper) |
| T27 | `test_a_text_match_stands_at_the_count_of_its_namespace_free_root` (4, Windows) and `test_an_identity_match_stands_where_the_path_names_it_not_where_its_root_is_spelled` (Windows) | T16 strengthened: the position `_match_position` returns for a text match (either side spelled with a prefix, the deepest root first or last) and for an identity match (the count of the path's own chain, never the root's spelled count; an exempt or a permitted root is not matched by identity) | none: pass on the head (R3M-11, R3M-12) |
| T28 | `test_a_configuration_loaded_as_a_stream_is_refused_for_every_spelling_of_its_file` (Windows, named streams) | round 3's A1 through the runtime: `protected_config_files` lists the stream as loaded; `resolve_for_runtime` and `read_file` refuse its spelling and the ordinary spelling of the file with the floor's reason and give no content; a neighbour's stream is read | M5 |
| T29 | `test_the_reader_spelling_follows_the_verified_readers_rules_on_the_text` (24, any platform) | round 4's F1, corrected by rounds 5 and 6: a path built as text on this platform's base is given only where the verified reader's own functions admit its text, one row per case of `_TEXT_CASES` (the ids are in §13f K9); a row's two answers (Windows, elsewhere) differ only where D14's rule is wider than the reader's text path (L21) | M6 (7 rows red on the head); M7 (the three direct-parent and above rows pass on a Windows head: its chain rule covers them); M8 (the three `..` rows pass on a Windows head for the same reason) |
| T30 | `test_the_reader_spelling_applies_the_readers_rules_off_windows_too` (21, any platform) | with `os.name` set to `posix` for the one call (a no-op on a POSIX host) and POSIX-shaped text: one row per case of `_POSIX_CASES` (the ids are in §13f K9): `reader_spelling` gives a spelling only where the verified reader's own functions admit the text, and a rule only Windows has gives the path | M6 (9 rows red on the head); M7 (2 rows red on the head: a reserved device name and a reserved device stem as the direct parent); M8 (4 rows red on the head: the root and three `..` rows) |
| T31 | `test_the_reader_spelling_agrees_with_the_pinned_directory_on_the_final_name` (9, any platform; the backslash row off Windows only) | for each final name of the test's rows (the ids are in §13f K9), a real pinned directory's `read_bytes` refuses it as `invalid child name` exactly when `reader_spelling` gives none, so the lister's restatement of the child-name rule is the reader's for those names (a name the gate refuses, such as a reserved device name, is answered `invalid path`: L22) | none: passes on the head (R4M-11, R4M-12, R4M-13) |
| T32 | `test_the_reader_spelling_calls_no_filesystem_function` (any platform) | `os.stat`, `os.lstat`, `os.scandir`, `os.listdir`, `os.getcwd` and `open` are replaced by functions that raise: no call happens for a spelling given, a spelling refused, an extended-prefix spelling or a relative one | none: passes on the head (R4M-10) |
| T33 | `test_a_listing_leaves_out_a_name_the_verified_reader_cannot_carry` (2, Windows) | round 4's F1 through the real tool: a directory with names that the plain reader opens and the verified reader's gate refuses (an unpaired surrogate in two file names and a directory name) beside an ordinary, a non-ASCII and an astral name and a file in an ordinary directory is listed from an ordinary and an extended-prefix base without the first kind; every file listed is opened by the verified reader with its own bytes; the unarmed `read_file` opens a name left out (L19) | M6 |
| T34 | `test_the_listing_agrees_with_the_verified_readers_text_path_over_a_generated_corpus` (2: the POSIX shape on any platform, the Windows shape on Windows) | round 5's A as a property, rewritten by round 6 (F1 to F3): over the 9,032 file texts per shape of `_corpus` (each directory of `_CORPUS_DIRS` and each final name of `_CORPUS_FILES` from zero to three directories deep, the root, and each final name directly under it), `reader_spelling` gives a spelling for no text the oracle refuses and for no text that is not its own normal form, and withholds no text the oracle admits except one the same-file rule withholds (Windows) or one that is not its own normal form. The oracle is the reader's own functions through the public API only: `validate_read_location` on the text and on the direct parent of the candidate (the text's normal form, as `os.path.abspath` gives it), and a real pinned directory's `read_bytes` for the candidate's final name. Premises: at least 6,000 texts; the corpus holds a path with no final name and the oracle refuses it; the oracle admits between 5 % and 95 %; at least 100 texts only the parent's gate refuses, 20 only normalising refuses, and 100 admitted texts that are not their own normal form | M7 (the POSIX shape red on the head: 258 holes); M8 (both shapes red on the head: the root, and on POSIX the `..` texts); R5M-1, -2, -4, -5, -6, -7, R4M-1 to R4M-7, R5M-T1 to T3, R6M-0 to R6M-8, R6M-T1 to R6M-T4 |
| T35 | `test_a_listing_and_the_verified_reader_agree_about_a_reserved_direct_parent` (any platform, real files) | round 5's A through the real reader and the real tool: `ok/g.txt`, `con/g.txt`, `aux.py/g.txt` and `con/sub/g.txt` are made (through the extended namespace on Windows); the real `read_verified_file` refuses the two with a reserved direct parent (`ValueError`) and reads the other two; `list_files` of the directory lists `ok/g.txt` and, off Windows, `con/sub/g.txt`; each file listed is read by the verified reader with its own bytes | M7 (passes on a Windows head; its POSIX run is `ubuntu-latest`); R3M-8 |
| T36 | `test_a_path_with_no_final_name_has_no_spelling_and_the_pinned_directory_refuses_its_empty_name` (2: the root of this platform's base; a share root, Windows) | round 6's F1: a real pinned directory's `read_bytes` refuses the empty name as `invalid child name`, and `reader_spelling` of the root gives none | M8 (2 rows red on the head); R6M-1 to R6M-3 |
| T37 | `test_the_verified_reader_gives_its_location_gate_the_file_and_its_direct_parent_and_nothing_above` (2: a canonical text, a text with a `..` part; any platform, a real file) | round 6's B6-3: the real `read_verified_file` of a file two directories deep gives `validate_read_location` the file's text, then the direct parent of the candidate it returned, then the candidate, in that order, and no directory above the direct parent; the candidate of a text with a `..` part is its normal form; a change of which texts the reader gives its gate fails it | none: passes on the head; R6M-9 to R6M-11 |
| T38 | `test_a_listing_whose_only_match_is_a_drive_root_lists_nothing` (Windows) | round 6's F1 through the real tool: with `Path.glob` yielding only the base, the real `list_files` of the drive root lists nothing; the policy admits the root and the real verified reader refuses its empty name | M8 (red on the head); R6M-1 |

## 7. The contract

**Pair grammar.** A pair belongs to the line `**B2-1** \`path\`` above it (the path is the first backticked token). The section runs to the next line that starts with `**B`, `## ` or `### `. Inside it, each `SEARCH:` line outside a fence, with the fenced block that follows, and the next `REPLACE:` line with its fenced block, is one pair. A fence is four backticks, optionally with a language tag, closed by four backticks; fenced text is verbatim, with LF line ends (the files are CRLF in the working tree; the applier keeps each file's own ends). Every SEARCH occurs exactly once in its file and pairs apply in order. A section marked `(new)` holds one fenced block: the whole new file. **No line inside an M1 or M2 fence starts with `**B`, `## ` or `### `.** Each of M3's two pairs holds such a line inside its fences (the PROGRESS paragraph starts with `**B`; the DECISIONS entry holds heading lines), so M3's pairs are applied with the `edit` tool, as BF-948's M3 was, or by an applier that ends a section only outside a fence. All 14 blocks (one new file and 13 pairs) were dry-run on a scratch copy of `728e1fc2` with a fence-aware applier (§13); M1 and M2 also parse under the plain "next `**B`, `## ` or `### ` line" rule.

### 7.1 M1

**B1-1** `tests/test_bf953_read_floor_spellings.py` (new)

````python
"""BF-953 (#1752): ``resolve_read_path`` returns one decision for every spelling of one file.

A path is decided the same way however it is spelled: for the floor (a directory root and a file root), for
the exempt roots that lift the floor, and for the permitted roots; and the path returned is the resolved
path, which names the file the decision was made on. The Windows spellings are built from fixture files this
test creates. A spelling the host does not serve is skipped once its premise (it names the same file as the
ordinary spelling) fails, so a skip is never a pass. The textual canonicaliser, the identity helper and the
POSIX rule run on every platform.
"""

from __future__ import annotations

import ctypes
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from probos.cognitive.swe_harness.tools import ReadFileTool
from probos.security import file_access
from probos.security.file_access import FileAccessDenied, protected_write_refusal, resolve_read_path
from tests.test_bf948_list_files_read_policy import _OUTSIDE, _PROTECTED, _list, _runtime, _scene

WINDOWS = pytest.mark.skipif(os.name != "nt", reason="BF-953: these are Windows path spellings")
_CONTENT = b"bf953 fixture"
_READ_PROTECTED = "read_file refused: path is protected: the runtime's data directory or a config file"
_READ_OUTSIDE = "read_file refused: path is outside every readable root"

_FAMILIES = [
    "forward slashes", "doubled separator", "dot segment", "dotdot via sibling dir", "dotdot via missing dir",
    "swapped case", "8.3 short name", "trailing dot", "trailing space", "default stream suffix", "device prefix",
    "extended prefix", "extended prefix, swapped case", "extended prefix, 8.3",
    "UNC localhost admin share", "UNC 127.0.0.1 admin share", "UNC computer-name admin share",
    "UNC extended localhost", "UNC extended computer-name", "UNC localhost, dotdot",
]
# The spellings the base decides differently from the ordinary one (measured on the committed head): the extended-length
# and share spellings and, for a file that is not on disk only (T1), a trailing space (the resolved path of a missing
# child of such a directory carries the extended-length prefix). M2 removes the marks.
_DECIDED_DIFFERENTLY = frozenset(_FAMILIES[11:])
_XFAIL = pytest.mark.xfail(strict=True, reason="BF-953: the base decides this spelling differently from the ordinary one")
_PARAMS = [pytest.param(name, marks=_XFAIL) if name in _DECIDED_DIFFERENTLY else name for name in _FAMILIES]
_PARAMS_T1 = [
    pytest.param(name, marks=_XFAIL) if name in _DECIDED_DIFFERENTLY | {"trailing space"} else name for name in _FAMILIES
]
_BASE_LACKS_IT = pytest.mark.xfail(strict=True, raises=AttributeError, reason="BF-953: M2 adds the helper this test calls")


def _short(text: str) -> str | None:
    """The 8.3 form of the existing path *text* the system gives, or None when the volume gives it none."""
    buffer = ctypes.create_unicode_buffer(1024)
    size = ctypes.windll.kernel32.GetShortPathNameW(text, buffer, len(buffer))  # type: ignore[attr-defined]
    return buffer.value if 0 < size < len(buffer) and buffer.value.lower() != text.lower() else None


def _spellings(target: Path) -> dict[str, str]:
    """Spellings of the existing path *target* (a drive-letter path), built from the path itself."""
    text = str(target)
    drive, rest = os.path.splitdrive(text)
    letter, parent, name = drive[0], str(target.parent), target.name
    parent_rest = rest.rsplit("\\", 1)[0]
    computer = os.environ.get("COMPUTERNAME", "")
    short = _short(text)

    def share(host: str, tail: str = rest) -> str:
        return f"\\\\{host}\\{letter}${tail}"

    spelled = {
        "forward slashes": text.replace("\\", "/"),
        "doubled separator": text.replace("\\", "\\\\", 1),
        "dot segment": f"{parent}\\.\\{name}",
        "dotdot via sibling dir": f"{parent}\\..\\{target.parent.name}\\{name}",
        "dotdot via missing dir": f"{parent}\\no-such-dir-bf953\\..\\{name}",
        "swapped case": text.swapcase(),
        "trailing dot": text + ".",
        "trailing space": text + " ",
        "device prefix": "\\\\.\\" + text,
        "extended prefix": "\\\\?\\" + text,
        "extended prefix, swapped case": "\\\\?\\" + text.swapcase(),
        "UNC localhost admin share": share("localhost"),
        "UNC 127.0.0.1 admin share": share("127.0.0.1"),
        "UNC extended localhost": "\\\\?\\UNC\\localhost\\" + letter + "$" + rest,
        "UNC localhost, dotdot": share("localhost", f"{parent_rest}\\..\\{target.parent.name}\\{name}"),
    }
    if target.is_file():
        spelled["default stream suffix"] = text + "::$DATA"
    if short:
        spelled["8.3 short name"] = short
        spelled["extended prefix, 8.3"] = "\\\\?\\" + short
    if computer:
        spelled["UNC computer-name admin share"] = share(computer)
        spelled["UNC extended computer-name"] = "\\\\?\\UNC\\" + computer + "\\" + letter + "$" + rest
    return spelled


def _spelling_or_none(family: str, target: Path) -> str | None:
    """The *family* spelling of the existing *target*, or None when this host has none or does not serve it."""
    spelling = _spellings(target).get(family)
    if spelling is None:
        return None
    try:
        same = os.path.samestat(os.stat(spelling), os.stat(target))
    except OSError:
        same = False
    return spelling if same else None


def _spelling(family: str, target: Path) -> str:
    spelling = _spelling_or_none(family, target)
    if spelling is None:
        pytest.skip(f"BF-953 premise: this host has no {family} spelling that names {target.name}")
    return spelling


def _fixture(tmp_path: Path) -> SimpleNamespace:
    """A floor directory holding an exempt directory, a config file with a neighbour, a permitted directory and one outside.

    Every name is long, so that the volume gives each an 8.3 name when it makes them."""
    root = tmp_path.resolve()
    lay = SimpleNamespace(
        data=root / "floor data directory",
        work=root / "floor data directory" / "work area directory",
        allowed=root / "allowed directory long name",
        outside=root / "outside directory long name",
        config=root / "config directory long name" / "loaded config long name.yaml",
    )
    for directory in (lay.work, lay.allowed, lay.outside, lay.config.parent):
        directory.mkdir(parents=True)
    lay.floor_note = lay.data / "floor note long name.txt"
    lay.work_note = lay.work / "work note long name.txt"
    lay.allowed_note = lay.allowed / "allowed note long name.txt"
    lay.outside_note = lay.outside / "outside note long name.txt"
    lay.neighbour = lay.config.parent / "neighbour file long name.yaml"
    for note in (lay.floor_note, lay.work_note, lay.allowed_note, lay.outside_note, lay.config, lay.neighbour):
        note.write_bytes(_CONTENT)
    return lay


def _decide(raw: str, *, protected: Any = (), exempt: Any = (), permitted: Any = None) -> tuple[str, str]:
    """The whole decision of one call: ``("admitted", <path returned>)`` or ``("refused", <reason>)``."""
    try:
        resolved = resolve_read_path(
            raw, protected_roots=list(protected), exempt_roots=list(exempt), permitted_roots=permitted,
        )
    except FileAccessDenied as exc:
        return "refused", exc.reason
    return "admitted", str(resolved)


@WINDOWS
@pytest.mark.parametrize("family", _PARAMS_T1)
def test_every_spelling_gets_the_decision_of_the_ordinary_spelling(tmp_path: Path, family: str) -> None:
    """T1: each spelling of a file is decided as its ordinary spelling is, against a directory root and a file root of
    the floor, an exempt root under the floor, and a permitted root; so is a file that is not on disk; and the path an
    admitted call returns is the resolved path and names the file."""
    lay = _fixture(tmp_path)
    floor = [lay.data.resolve(), lay.config.resolve()]
    exempt, permitted = [lay.work.resolve()], [lay.allowed.resolve()]
    cases = [
        (lay.floor_note, {"protected": floor, "exempt": exempt}, "refused"),
        (lay.config, {"protected": floor}, "refused"),
        (lay.neighbour, {"protected": floor}, "admitted"),
        (lay.work_note, {"protected": floor, "exempt": exempt}, "admitted"),
        (lay.allowed_note, {"permitted": permitted}, "admitted"),
        (lay.outside_note, {"permitted": permitted}, "refused"),
    ]
    for target, roots, expected in cases:
        ordinary = _decide(str(target), **roots)
        assert ordinary[0] == expected, f"premise: the ordinary spelling of {target.name}: {ordinary}"
        spelled = _decide(_spelling(family, target), **roots)
        assert spelled[0] == expected, f"{family} of {target.name}: {spelled}"
        if expected == "refused":
            assert spelled[1] == ordinary[1], f"{family} of {target.name}: another reason"
        else:
            assert Path(spelled[1]) == Path(spelled[1]).resolve(), "the path returned is a resolved path"
            assert os.path.samestat(os.stat(spelled[1]), os.stat(target)), "the path returned names the file"
    missing = [
        (lay.data, {"protected": floor}, "refused"),
        (lay.work, {"protected": floor, "exempt": exempt}, "admitted"),
        (lay.allowed, {"permitted": permitted}, "admitted"),
        (lay.outside, {"permitted": permitted}, "refused"),
    ]
    for directory, roots, expected in missing:
        absent = "missing note long name.txt"
        assert _decide(str(directory / absent), **roots)[0] == expected, "premise: the ordinary spelling"
        spelling = _spelling_or_none(family, directory)
        if spelling is not None:
            assert _decide(spelling + "\\" + absent, **roots)[0] == expected, f"{family}, not on disk"


@WINDOWS
@pytest.mark.parametrize("family", _PARAMS)
async def test_read_file_decides_every_spelling_alike(tmp_path: Path, family: str) -> None:
    """T2: ``ReadFileTool`` answers every spelling of a file as it answers the ordinary one."""
    scene = _scene(tmp_path)
    floor_note = scene.data / "floor note long name.txt"
    allowed_note = scene.allowed / "allowed note long name.txt"
    outside_note = scene.outside / "outside note long name.txt"
    for note in (floor_note, allowed_note, outside_note):
        note.write_bytes(_CONTENT)
    cases = [
        (floor_note, [], _READ_PROTECTED),
        (outside_note, [scene.allowed], _READ_OUTSIDE),
        (allowed_note, [scene.allowed], None),
    ]
    for note, read_roots, refusal in cases:
        tool = ReadFileTool(_runtime(scene, read_roots=read_roots))
        ordinary = await tool.invoke({"path": str(note)})
        assert ordinary.error == refusal, f"premise: the ordinary spelling of {note.name}: {ordinary.error}"
        spelled = await tool.invoke({"path": _spelling(family, note)})
        assert spelled.error == refusal, f"{family} of {note.name}: {spelled.error}"
        if refusal is None:
            assert "bf953 fixture" in repr(spelled.output)


@WINDOWS
@pytest.mark.parametrize("family", _PARAMS)
async def test_list_files_decides_every_spelling_of_a_directory_alike(tmp_path: Path, family: str) -> None:
    """T3: ``list_files`` asks the same function for its base and for each match, on BF-948's rig. The ordinary
    spellings are decided first (the premise); then a spelling of the floor directory is refused, a spelling of a
    directory outside the permitted root is refused, and a spelling of the permitted root and of the agent
    workspace under the floor is listed."""
    scene = _scene(tmp_path)
    (scene.allowed / "allowed note long name.txt").write_bytes(_CONTENT)
    assert (await _list(scene, [], "*", str(scene.data))).error == _PROTECTED  # premise
    assert (await _list(scene, [scene.allowed], "*", str(scene.outside))).error == _OUTSIDE  # premise
    listed = await _list(scene, [scene.allowed], "*", str(scene.allowed))
    assert listed.error is None and {Path(n).name for n in listed.output["files"]} == {
        "allowed note long name.txt", "ok.txt", "sub",
    }  # premise
    assert (await _list(scene, [], "*", str(scene.workspace))).error is None  # premise: the exemption lifts the floor
    refused_floor = await _list(scene, [], "*", _spelling(family, scene.data))
    assert refused_floor.error == _PROTECTED and refused_floor.output is None, family
    refused_outside = await _list(scene, [scene.allowed], "*", _spelling(family, scene.outside))
    assert refused_outside.error == _OUTSIDE and refused_outside.output is None, family
    spelled = await _list(scene, [scene.allowed], "*", _spelling(family, scene.allowed))
    assert spelled.error is None, f"{family}: {spelled.error}"
    assert {Path(n).name for n in spelled.output["files"]} == {"allowed note long name.txt", "ok.txt", "sub"}, family
    workspace = await _list(scene, [], "*", _spelling(family, scene.workspace))
    assert workspace.error is None and [Path(n).name for n in workspace.output["files"]] == ["scratch.txt"], family


@WINDOWS
@pytest.mark.parametrize("family", _PARAMS)
def test_the_read_floor_refuses_every_spelling_of_a_config_file_the_write_side_refuses(
    tmp_path: Path, family: str,
) -> None:
    """T4: the write side refuses every spelling of the loaded config file (BF-911); so does the read floor."""
    lay = _fixture(tmp_path)
    runtime = SimpleNamespace(config_path=lay.config)
    configs = file_access.protected_config_files(runtime)
    assert lay.config.resolve() in configs, "premise: the runtime names the file"
    assert protected_write_refusal(str(lay.config), runtime=runtime) is not None, "premise: the write side refuses it"
    assert _decide(str(lay.config), protected=configs)[0] == "refused", "premise: the read floor refuses it"
    spelled = _spelling(family, lay.config)
    assert protected_write_refusal(spelled, runtime=runtime) is not None, f"{family}: the write side"
    assert _decide(spelled, protected=configs)[0] == "refused", f"{family}: the read floor"


_NAMESPACE_CASES = [
    ("\\\\?\\C:\\data\\note.txt", "C:\\data\\note.txt"),
    ("\\\\?\\c:\\Data", "c:\\Data"),
    ("\\\\?\\C:", "C:"),
    ("\\\\.\\C:\\data", "C:\\data"),
    ("\\\\?\\UNC\\host\\share\\dir\\f.txt", "\\\\host\\share\\dir\\f.txt"),
    ("\\\\?\\unc\\host\\share", "\\\\host\\share"),
    ("C:\\data\\note.txt", "C:\\data\\note.txt"),
    ("\\\\host\\share\\dir", "\\\\host\\share\\dir"),
    ("\\\\?\\Volume{4d83c44e-bb8a-4ae4-b23a-fe55aac6532d}\\data", "\\\\?\\Volume{4d83c44e-bb8a-4ae4-b23a-fe55aac6532d}\\data"),
    ("\\\\?\\1:\\data", "\\\\?\\1:\\data"),
    ("\\\\?\\CC:\\data", "\\\\?\\CC:\\data"),
    ("\\\\?\\C:data", "\\\\?\\C:data"),
    ("/srv/data/note.txt", "/srv/data/note.txt"),
    ("", ""),
    ("\\\\?\\", "\\\\?\\"),
]


@_BASE_LACKS_IT
@pytest.mark.parametrize(("text", "expected"), _NAMESPACE_CASES)
def test_the_namespace_free_form(text: str, expected: str) -> None:
    """T5: pure text, the same on every platform: the extended and device prefixes of a drive path and the extended
    UNC prefix go; a volume or device name, a drive-relative form and a path of another platform stay."""
    assert file_access._namespace_free(text) == expected


@_BASE_LACKS_IT
@pytest.mark.parametrize("text", [case[0] for case in _NAMESPACE_CASES if case[0] and case[0] != case[1]])
def test_the_namespace_free_form_agrees_with_the_write_sides_key(text: str) -> None:
    """T6: for every spelling the canonicaliser rewrites, the write side's key (BF-911) of the text and of the rewrite
    are the same."""
    assert file_access._write_key(text) == file_access._write_key(file_access._namespace_free(text))


@_BASE_LACKS_IT
def test_file_identity_is_the_file_the_system_names(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """T7: one identity for every name of a file, none for a path that names nothing, and none when the filesystem
    reports no file index."""
    note = tmp_path / "note.txt"
    note.write_bytes(_CONTENT)
    (tmp_path / "sub").mkdir()
    link = tmp_path / "note-link.txt"
    os.link(note, link)
    identity = file_access._file_identity(note)
    assert identity is not None
    assert file_access._file_identity(tmp_path / "sub" / ".." / "note.txt") == identity == file_access._file_identity(link)
    assert file_access._file_identity(tmp_path / "sub") != identity
    assert file_access._file_identity(tmp_path / "missing.txt") is None
    assert file_access._file_identity(Path("bad\x00name")) is None
    with monkeypatch.context() as patched:
        patched.setattr(file_access.os, "stat", lambda _path: SimpleNamespace(st_dev=7, st_ino=0))
        assert file_access._file_identity(note) is None


@pytest.mark.skipif(os.name == "nt", reason="BF-953: on Windows these names are one directory")
def test_a_posix_name_keeps_what_a_permitted_root_admits(tmp_path: Path) -> None:
    """T8: on POSIX the names that differ by case, a trailing dot or space, a backslash or a Windows-looking prefix are
    other directories, and none of them is inside the permitted root."""
    root = tmp_path.resolve()
    names = ["allowed", "Allowed", "allowed.", "allowed ", "allowed\\x", "\\\\?\\allowed", "\\\\localhost\\allowed"]
    for name in names:
        (root / name).mkdir()
        (root / name / "note.txt").write_bytes(_CONTENT)
    assert len(list(root.iterdir())) == len(names), "premise: every name is its own directory"
    permitted = [root / "allowed"]
    assert _decide(str(root / "allowed" / "note.txt"), permitted=permitted)[0] == "admitted"
    for name in names[1:]:
        assert _decide(str(root / name / "note.txt"), permitted=permitted) == (
            "refused", "path is outside every readable root",
        ), name
    assert _decide(f"{root / 'allowed'}\\note.txt", permitted=permitted)[0] == "refused"


@WINDOWS
@_BASE_LACKS_IT
def test_a_drive_letter_path_costs_no_identity_lookup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """T9: a drive-letter path against drive-letter roots, and an extended-prefix local path (decided on its text),
    ask the system for no identity; the path returned is unchanged."""
    lay = _fixture(tmp_path)
    asked: list[Path] = []
    monkeypatch.setattr(file_access, "_file_identity", lambda path: asked.append(path))
    roots = {"protected": [lay.data.resolve()], "exempt": [lay.work.resolve()], "permitted": [lay.allowed.resolve()]}
    plain = _decide(str(lay.allowed_note), **roots)
    extended = _decide("\\\\?\\" + str(lay.allowed_note), **roots)
    assert plain == ("admitted", str(lay.allowed_note)) and extended == ("admitted", "\\\\?\\" + str(lay.allowed_note))
    assert asked == []


@WINDOWS
@_BASE_LACKS_IT
def test_a_share_path_no_root_covers_stays_admitted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """T10: containment of a share path is decided by identity. With the system's answers replaced (no host is
    contacted), a share path that is not the root and has no ancestor that is the root is not inside it, and one
    that has is."""
    root = _fixture(tmp_path).data.resolve()
    absent_root = root.parent / "no-such-root"
    same_as_root = Path("\\\\bf953-alias\\share\\floor")
    known = {root: (1, 1), same_as_root: (1, 1), absent_root: None}
    monkeypatch.setattr(file_access, "_file_identity", lambda path: known[path] if path in known else (2, hash(path)))
    elsewhere = Path("\\\\bf953-remote\\share\\dir\\note.txt")
    inside = same_as_root / "sub" / "note.txt"
    assert file_access._longest_match(elsewhere, [root]) is None
    assert file_access._longest_match(inside, [root]) == root
    assert file_access._longest_match(same_as_root, [root]) == root
    assert file_access._longest_match(inside, [absent_root]) is None
````

### 7.2 M2

**B2-1** `src/probos/security/file_access.py`

SEARCH:
````python
def _depth(root: Path) -> int:
    return len(root.parts)


def _longest_match(resolved: Path, roots: Iterable[Path]) -> Path | None:
    """The deepest root that contains *resolved*, or ``None``."""
    best: Path | None = None
    for root in roots:
        try:
            if resolved == root or resolved.is_relative_to(root):
                if best is None or _depth(root) > _depth(best):
                    best = root
        except (OSError, ValueError):
            continue
    return best
````
REPLACE:
````python
def _depth(root: Path) -> int:
    return len(root.parts)


# BF-953: one decision for every spelling of one file. ``Path.resolve()`` keeps the Windows extended-length
# prefix it is given and reports a share spelling of a local drive as the share path, so the textual test
# below saw each as another place. On Windows the text is first reduced to its namespace-free form
# (``_namespace_free``), and a path or root that still names a share or a device is also compared by the
# identity the system gives the file (``_file_identity``). Elsewhere containment is the textual test.
_NAMESPACE_PREFIXES = ("\\\\?\\", "\\\\.\\")
_EXTENDED_UNC = "\\\\?\\UNC\\"


def _namespace_free(text: str) -> str:
    r"""BF-953: *text*, a path as ``str(WindowsPath)`` spells it, without its Windows namespace prefix.

    ``\\?\UNC\host\share\x`` is ``\\host\share\x``; ``\\?\C:\x`` and ``\\.\C:\x`` are ``C:\x``. Any other
    text (a volume or device name, a drive-relative form, a path of another platform) is returned as it is.
    Pure: it reads nothing and does not depend on the platform it runs on.
    """
    if text[:8].upper() == _EXTENDED_UNC.upper():
        return "\\\\" + text[8:]
    if text[:4] in _NAMESPACE_PREFIXES and text[4:5].isascii() and text[4:5].isalpha() and text[5:6] == ":":
        if text[6:7] in ("", "\\"):
            return text[4:]
    return text


def _file_identity(path: Path) -> tuple[int, int] | None:
    """BF-953: the identity the system gives the file *path* names, ``(volume, file index)``.

    ``None`` when it is not on disk, cannot be read, or its filesystem reports no file index (zero).
    """
    try:
        info = os.stat(path)
    except (OSError, ValueError):
        return None
    return (info.st_dev, info.st_ino) if info.st_ino else None


class _OnDisk:
    """BF-953: the identities of a path and of each ancestor of it that is on disk, read once and only when asked."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._found: frozenset[tuple[int, int]] | None = None

    def holds(self, identity: tuple[int, int]) -> bool:
        if self._found is None:
            found = (_file_identity(part) for part in (self._path, *self._path.parents))
            self._found = frozenset(ident for ident in found if ident is not None)
        return identity in self._found


def _longest_match(resolved: Path, roots: Iterable[Path], on_disk: _OnDisk | None = None) -> Path | None:
    """The deepest root that contains *resolved*, or ``None``.

    A root contains a path that is under it as spelled. On Windows (BF-953) it also contains a path that is
    under it once both are without a namespace prefix, and a path or root that still names a share or a
    device is contained when the path, or an ancestor of it, is the same file as the root
    (:func:`_file_identity`). A root with no identity, because it is not on disk, is matched by spelling
    only. *on_disk* lets the root lists of one decision read the path's identities once.
    """
    best: Path | None = None
    if on_disk is None:
        on_disk = _OnDisk(resolved)
    for root in roots:
        try:
            inside = resolved == root or resolved.is_relative_to(root)
            if not inside and os.name == "nt" and (str(resolved).startswith("\\\\") or str(root).startswith("\\\\")):
                key = PureWindowsPath(_namespace_free(str(resolved)))
                root_key = PureWindowsPath(_namespace_free(str(root)))
                inside = key == root_key or key.is_relative_to(root_key)
                if not inside and (key.drive.startswith("\\\\") or root_key.drive.startswith("\\\\")):
                    root_id = _file_identity(root)
                    inside = root_id is not None and on_disk.holds(root_id)
            if inside and (best is None or _depth(root) > _depth(best)):
                best = root
        except (OSError, ValueError):
            continue
    return best
````

**B2-2** `src/probos/security/file_access.py`

SEARCH:
````python
    Resolution happens BEFORE containment, so a symlink pointing into the floor
    is caught -- the same ``resolve() + is_relative_to`` order
    ``WorkspaceManager.resolve_file`` uses.
    """
````
REPLACE:
````python
    Resolution happens BEFORE containment, so a symlink pointing into the floor
    is caught -- the same ``resolve() + is_relative_to`` order
    ``WorkspaceManager.resolve_file`` uses.

    BF-953: the decision is the same for every spelling of one file, for the floor, the
    exempt roots and the permitted roots (:func:`_longest_match`). What is returned is the
    resolved path itself, in the spelling it was resolved to, never a rewritten one: it
    names the file the decision was made on.
    """
````

**B2-3** `src/probos/security/file_access.py`

SEARCH:
````python
    protect = _longest_match(resolved, protected_roots)
    if protect is not None:
        exempt = _longest_match(resolved, exempt_roots)
````
REPLACE:
````python
    on_disk = _OnDisk(resolved)  # BF-953: read at most once, and only if a root is compared by identity
    protect = _longest_match(resolved, protected_roots, on_disk)
    if protect is not None:
        exempt = _longest_match(resolved, exempt_roots, on_disk)
````

**B2-4** `src/probos/security/file_access.py`

SEARCH:
````python
    if permitted_roots and _longest_match(resolved, permitted_roots) is None:
````
REPLACE:
````python
    if permitted_roots and _longest_match(resolved, permitted_roots, on_disk) is None:
````

**B2-5** `tests/test_bf953_read_floor_spellings.py`

SEARCH:
````python
# The spellings the base decides differently from the ordinary one (measured on the committed head): the extended-length
# and share spellings and, for a file that is not on disk only (T1), a trailing space (the resolved path of a missing
# child of such a directory carries the extended-length prefix). M2 removes the marks.
_DECIDED_DIFFERENTLY = frozenset(_FAMILIES[11:])
_XFAIL = pytest.mark.xfail(strict=True, reason="BF-953: the base decides this spelling differently from the ordinary one")
_PARAMS = [pytest.param(name, marks=_XFAIL) if name in _DECIDED_DIFFERENTLY else name for name in _FAMILIES]
_PARAMS_T1 = [
    pytest.param(name, marks=_XFAIL) if name in _DECIDED_DIFFERENTLY | {"trailing space"} else name for name in _FAMILIES
]
_BASE_LACKS_IT = pytest.mark.xfail(strict=True, raises=AttributeError, reason="BF-953: M2 adds the helper this test calls")
````
REPLACE:
````python
_PARAMS = list(_FAMILIES)
````

**B2-11** `tests/test_bf953_read_floor_spellings.py`

SEARCH:
````python
@pytest.mark.parametrize("family", _PARAMS_T1)
def test_every_spelling_gets_the_decision_of_the_ordinary_spelling(
````
REPLACE:
````python
@pytest.mark.parametrize("family", _PARAMS)
def test_every_spelling_gets_the_decision_of_the_ordinary_spelling(
````

**B2-6** `tests/test_bf953_read_floor_spellings.py`

SEARCH:
````python
@_BASE_LACKS_IT
@pytest.mark.parametrize(("text", "expected"), _NAMESPACE_CASES)
````
REPLACE:
````python
@pytest.mark.parametrize(("text", "expected"), _NAMESPACE_CASES)
````

**B2-7** `tests/test_bf953_read_floor_spellings.py`

SEARCH:
````python
@_BASE_LACKS_IT
@pytest.mark.parametrize("text", [case[0] for case in _NAMESPACE_CASES if case[0] and case[0] != case[1]])
````
REPLACE:
````python
@pytest.mark.parametrize("text", [case[0] for case in _NAMESPACE_CASES if case[0] and case[0] != case[1]])
````

**B2-8** `tests/test_bf953_read_floor_spellings.py`

SEARCH:
````python
@_BASE_LACKS_IT
def test_file_identity_is_the_file_the_system_names(
````
REPLACE:
````python
def test_file_identity_is_the_file_the_system_names(
````

**B2-9** `tests/test_bf953_read_floor_spellings.py`

SEARCH:
````python
@WINDOWS
@_BASE_LACKS_IT
def test_a_drive_letter_path_costs_no_identity_lookup(
````
REPLACE:
````python
@WINDOWS
def test_a_drive_letter_path_costs_no_identity_lookup(
````

**B2-10** `tests/test_bf953_read_floor_spellings.py`

SEARCH:
````python
@WINDOWS
@_BASE_LACKS_IT
def test_a_share_path_no_root_covers_stays_admitted(
````
REPLACE:
````python
@WINDOWS
def test_a_share_path_no_root_covers_stays_admitted(
````

### 7.3 M3

M3 changes no `src` or `tests` file. Its pairs are B3-1 and B3-2 (§8), plus the ledger.

### 7.4 M4 (Amendment 1)

All blocks are against `d1aba238`. **Apply B4-2 first (red, G5), then B4-1.** Where prose differs from a block, the block wins. `_depth` is removed (it had no other caller: `rg -n "_depth\(" src tests scripts` found only `file_access.py`). B4-2 imports `_link` and `_unlink` from BF-948's test file (D7).

**B4-1** `src/probos/security/file_access.py`

SEARCH:
````python
def _depth(root: Path) -> int:
    return len(root.parts)


# BF-953: one decision for every spelling of one file. ``Path.resolve()`` keeps the Windows extended-length
# prefix it is given and reports a share spelling of a local drive as the share path, so the textual test
# below saw each as another place. On Windows the text is first reduced to its namespace-free form
# (``_namespace_free``), and a path or root that still names a share or a device is also compared by the
# identity the system gives the file (``_file_identity``). Elsewhere containment is the textual test.
_NAMESPACE_PREFIXES = ("\\\\?\\", "\\\\.\\")
_EXTENDED_UNC = "\\\\?\\UNC\\"
````
REPLACE:
````python
# BF-953: the floor decides each spelling of one file as its ordinary spelling is decided. ``Path.resolve()`` keeps the
# Windows extended-length prefix it is given and reports a share spelling of a local drive as the share path, so the
# textual test below saw each as another place. On Windows the text is first reduced to its namespace-free form
# (``_namespace_free``) for every root list. The floor alone is also decided by the identity the system gives the
# file (``_file_identity``), for a path or root that still names a share or a device: identity only ever adds a
# refusal, and an exempt or permitted root is matched by text, so no spelling is admitted by one it does not
# textually name (BF-953 Amendment 1). The floor's file roots and the credential names are decided on the file the
# final component names (``_base_file``). Elsewhere containment is the textual test.
_NAMESPACE_PREFIXES = ("\\\\?\\", "\\\\.\\")
_EXTENDED_UNC = "\\\\?\\UNC\\"
_FLOOR_UNVERIFIED = "path cannot be verified against the protected roots"
````

SEARCH:
````python
def _file_identity(path: Path) -> tuple[int, int] | None:
    """BF-953: the identity the system gives the file *path* names, ``(volume, file index)``.

    ``None`` when it is not on disk, cannot be read, or its filesystem reports no file index (zero).
    """
    try:
        info = os.stat(path)
    except (OSError, ValueError):
        return None
    return (info.st_dev, info.st_ino) if info.st_ino else None


class _OnDisk:
    """BF-953: the identities of a path and of each ancestor of it that is on disk, read once and only when asked."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._found: frozenset[tuple[int, int]] | None = None

    def holds(self, identity: tuple[int, int]) -> bool:
        if self._found is None:
            found = (_file_identity(part) for part in (self._path, *self._path.parents))
            self._found = frozenset(ident for ident in found if ident is not None)
        return identity in self._found


def _longest_match(resolved: Path, roots: Iterable[Path], on_disk: _OnDisk | None = None) -> Path | None:
    """The deepest root that contains *resolved*, or ``None``.

    A root contains a path that is under it as spelled. On Windows (BF-953) it also contains a path that is
    under it once both are without a namespace prefix, and a path or root that still names a share or a
    device is contained when the path, or an ancestor of it, is the same file as the root
    (:func:`_file_identity`). A root with no identity, because it is not on disk, is matched by spelling
    only. *on_disk* lets the root lists of one decision read the path's identities once.
    """
    best: Path | None = None
    if on_disk is None:
        on_disk = _OnDisk(resolved)
    for root in roots:
        try:
            inside = resolved == root or resolved.is_relative_to(root)
            if not inside and os.name == "nt" and (str(resolved).startswith("\\\\") or str(root).startswith("\\\\")):
                key = PureWindowsPath(_namespace_free(str(resolved)))
                root_key = PureWindowsPath(_namespace_free(str(root)))
                inside = key == root_key or key.is_relative_to(root_key)
                if not inside and (key.drive.startswith("\\\\") or root_key.drive.startswith("\\\\")):
                    root_id = _file_identity(root)
                    inside = root_id is not None and on_disk.holds(root_id)
            if inside and (best is None or _depth(root) > _depth(best)):
                best = root
        except (OSError, ValueError):
            continue
    return best
````
REPLACE:
````python
class _Unverifiable(Exception):
    """BF-953 (Amendment 1): the system could not say which file a path names, so the floor cannot be checked."""


def _base_name(name: str) -> str:
    """BF-953 (Amendment 1): the name of the file the final component *name* names, on Windows: without a stream suffix (the
    text from the first ``:``) and without trailing dots and spaces. A name that would be empty is returned as it is. Pure."""
    return name.split(":", 1)[0].rstrip(" .") or name


def _base_file(path: Path) -> Path:
    """BF-953 (Amendment 1): *path* with its final component reduced to the file it names (:func:`_base_name`), on Windows;
    any other path, and every path on another platform, as it is. The floor and the credential names are decided on it, so a
    stream, trailing-dot or trailing-space spelling of a floor file is decided as the file is, whether or not it is on disk;
    an admitted read keeps the path as resolved. Pure: it reads nothing."""
    if os.name != "nt":
        return path
    base = _base_name(path.name)
    return path.with_name(base) if base != path.name else path


def _protected_leaf(path: Path) -> bool:
    """Whether the final component of *path* is a credential vault file name: exactly as the base compared it
    (``PROTECTED_LEAF_NAMES``), and on Windows (BF-953 Amendment 1) as the write side compares it, in the canonical form
    (:func:`_canonical_name`), so another case is the same name."""
    return _canonical_name(path.name) in _PROTECTED_LEAF_KEYS if os.name == "nt" else path.name in PROTECTED_LEAF_NAMES


def _file_identity(path: Path) -> tuple[int, int] | None:
    """BF-953: the identity the system gives the file *path* names, ``(volume, file index)``.

    ``None`` when no such file is on disk (the system says there is none). Raises :class:`_Unverifiable` when the
    system cannot say: the read fails for any other reason, or its filesystem reports no file index (zero).
    """
    try:
        info = os.stat(path)
    except (FileNotFoundError, NotADirectoryError):
        return None
    except (OSError, ValueError) as exc:
        raise _Unverifiable from exc
    if not info.st_ino:
        raise _Unverifiable
    return info.st_dev, info.st_ino


def plain_spelling(path: Path) -> Path:
    """BF-953 (Amendment 1): *path* without its Windows namespace prefix, as a reader that rejects the prefix is given it.

    The extended-length and device prefixes of a drive path and the extended UNC prefix are removed
    (:func:`_namespace_free`); any other path, and every path on another platform, is returned as it is. Pure: it
    reads nothing. A final component that ends in a dot or a space is not the same file once the prefix is gone.
    """
    return Path(_namespace_free(str(path))) if os.name == "nt" else path


class _OnDisk:
    """BF-953: the identities of a path and of each ancestor of it that is on disk, read once and only when asked.

    ``position`` is the count of parts, without a namespace prefix, of the deepest part of the path's own chain that
    has a given identity; ``reaches`` is whether the chain is on a volume other than the one its topmost part is on.
    Reading a part the system cannot say anything about raises :class:`_Unverifiable`.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._places: dict[tuple[int, int], int] | None = None
        self._crossed: frozenset[int] = frozenset()

    def _read(self) -> dict[tuple[int, int], int]:
        if self._places is None:
            places: dict[tuple[int, int], int] = {}
            volumes: list[int] = []
            for part in (self._path, *self._path.parents):
                identity = _file_identity(part)
                if identity is not None:
                    places.setdefault(identity, len(PureWindowsPath(_namespace_free(str(part))).parts))
                    volumes.append(identity[0])
            self._crossed = frozenset(volumes) - {volumes[-1]} if volumes else frozenset()
            self._places = places
        return self._places

    def position(self, identity: tuple[int, int]) -> int | None:
        return self._read().get(identity)

    def reaches(self, volume: int) -> bool:
        self._read()
        return volume in self._crossed


def _identity_position(root: Path, on_disk: _OnDisk, whole: int) -> int | None:
    """BF-953 (Amendment 1): where in the path's own chain the floor root *root* is taken to contain it, or ``None``.

    The root contains the path at the part of its chain that is the same file as the root. It also contains it, at
    the path's own depth *whole*, when the chain is on the volume the root is on only through a link, because its
    text then does not say where on that volume the file is. A root not on disk contains nothing. Raises
    :class:`_Unverifiable` when the root or a part of the chain cannot be read.
    """
    identity = _file_identity(root)
    if identity is None:
        return None
    place = on_disk.position(identity)
    if place is None and on_disk.reaches(identity[0]):
        return whole
    return place


def _match_position(
    resolved: Path, roots: Iterable[Path], on_disk: _OnDisk | None = None, *, floor: bool = False,
) -> int | None:
    """Where in *resolved*'s own chain the deepest root that contains it stands (a count of parts), or ``None``.

    A root contains a path that is under it as spelled; it stands at its own count of parts. On Windows (BF-953) it
    also contains a path that is under it once both are without a namespace prefix, standing at the count of the
    root's parts so reduced. For the floor only (*floor*), a path or root that still names a share or a device is also
    compared by identity (:func:`_identity_position`); the exempt roots and the permitted roots never are, so a
    spelling is admitted only by a root its text names. Raises :class:`_Unverifiable` for a floor that cannot be
    read. *on_disk* lets the root lists of one decision read the path's identities once.
    """
    best: int | None = None
    if on_disk is None:
        on_disk = _OnDisk(resolved)
    for root in roots:
        try:
            at = len(root.parts) if resolved == root or resolved.is_relative_to(root) else None
            if at is None and os.name == "nt" and (str(resolved).startswith("\\\\") or str(root).startswith("\\\\")):
                key = PureWindowsPath(_namespace_free(str(resolved)))
                root_key = PureWindowsPath(_namespace_free(str(root)))
                if key == root_key or key.is_relative_to(root_key):
                    at = len(root_key.parts)
                elif floor and (key.drive.startswith("\\\\") or root_key.drive.startswith("\\\\")):
                    at = _identity_position(root, on_disk, len(key.parts))
        except (OSError, ValueError):
            continue
        if at is not None and (best is None or at > best):
            best = at
    return best
````

SEARCH:
````python
    BF-953: the decision is the same for every spelling of one file, for the floor, the
    exempt roots and the permitted roots (:func:`_longest_match`). What is returned is the
    resolved path itself, in the spelling it was resolved to, never a rewritten one: it
    names the file the decision was made on.
    """
````
REPLACE:
````python
    BF-953: the floor decides one file in every spelling the system treats as that file: for a path that
    :func:`_match_position` compares (a share or device spelling also by the identity of its own chain), and on Windows
    for the final component (a stream suffix, trailing dots and spaces, another case: :func:`_base_file`), for a floor
    file root and a credential vault name, whether or not the file is on disk. Not covered: a share or device spelling of
    a floor file root that is not on disk (L2). An exempt or a permitted root admits a share or device spelling only if
    its text names that root, and a floor that cannot be read for a share or device spelling refuses it. What is
    returned is the resolved path itself, in the spelling it was resolved to, never a rewritten one: it names the file
    the decision was made on (a named stream keeps its suffix).
    """
````

SEARCH:
````python
    if resolved.name in PROTECTED_LEAF_NAMES:
        raise FileAccessDenied(raw, "that file holds credentials and is not readable")

    on_disk = _OnDisk(resolved)  # BF-953: read at most once, and only if a root is compared by identity
    protect = _longest_match(resolved, protected_roots, on_disk)
    if protect is not None:
        exempt = _longest_match(resolved, exempt_roots, on_disk)
        # Longest prefix wins: a deeper exemption lifts a shallower floor.
        if exempt is None or _depth(exempt) <= _depth(protect):
            raise FileAccessDenied(
                raw, "path is protected: the runtime's data directory or a config file"
            )

    if permitted_roots and _longest_match(resolved, permitted_roots, on_disk) is None:
        raise FileAccessDenied(raw, "path is outside every readable root")
    return resolved
````
REPLACE:
````python
    base_file = _base_file(resolved)  # BF-953 (Amendment 1): what the floor and the credential names are decided on
    if _protected_leaf(base_file):
        raise FileAccessDenied(raw, "that file holds credentials and is not readable")

    on_disk = _OnDisk(base_file)  # BF-953: read at most once, and only if the floor is compared by identity
    try:
        protect = _match_position(base_file, protected_roots, on_disk, floor=True)
    except _Unverifiable as exc:
        logger.warning(
            "BF-953: the read floor could not be verified for a path (%s); the read is refused",
            type(exc.__cause__).__name__ if exc.__cause__ is not None else "no file index",
        )
        raise FileAccessDenied(raw, _FLOOR_UNVERIFIED) from None
    if protect is not None:
        exempt = _match_position(resolved, exempt_roots)
        # Longest prefix wins: a deeper exemption lifts a shallower floor. Both stand at a count of
        # parts of this path's own chain, not of the spelling of the root.
        if exempt is None or exempt <= protect:
            raise FileAccessDenied(
                raw, "path is protected: the runtime's data directory or a config file"
            )

    if permitted_roots and _match_position(resolved, permitted_roots) is None:
        raise FileAccessDenied(raw, "path is outside every readable root")
    return resolved
````

SEARCH:
````python
    try:
        from probos.execution.workspace import _resolve_workspace_root

        roots.append(_resolve_workspace_root(workspace))
    except Exception:
````
REPLACE:
````python
    try:
        from probos.execution.workspace import _resolve_workspace_root

        # BF-953 (Amendment 1): resolved as the candidate is, so the root and a path under it are spelled alike
        # (a configured 8.3 short path or an unresolved data directory would otherwise name it as no candidate does).
        roots.append(_resolve_workspace_root(workspace).resolve())
    except Exception:
````

SEARCH:
````python
    try:
        from probos.execution.workspace import _resolve_workspace_root

        return [_resolve_workspace_root(workspace)]
    except Exception:
````
REPLACE:
````python
    try:
        from probos.execution.workspace import _resolve_workspace_root

        # BF-953 (Amendment 1): resolved as the candidate is (see ``permitted_read_roots``).
        return [_resolve_workspace_root(workspace).resolve()]
    except Exception:
````

**B4-2** `tests/test_bf953_read_floor_spellings.py`

SEARCH:
````python
POSIX rule run on every platform.
"""

from __future__ import annotations

import ctypes
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from probos.cognitive.swe_harness.tools import ReadFileTool
from probos.security import file_access
from probos.security.file_access import FileAccessDenied, protected_write_refusal, resolve_read_path
from tests.test_bf948_list_files_read_policy import _OUTSIDE, _PROTECTED, _list, _runtime, _scene

WINDOWS = pytest.mark.skipif(os.name != "nt", reason="BF-953: these are Windows path spellings")
_CONTENT = b"bf953 fixture"
_READ_PROTECTED = "read_file refused: path is protected: the runtime's data directory or a config file"
_READ_OUTSIDE = "read_file refused: path is outside every readable root"
````
REPLACE:
````python
POSIX rule run on every platform.

Amendment 1 (review round 2, T11 to T22): identity only ever adds a refusal at the floor. A share spelling is
never admitted by an exempt or a permitted root its text does not name (T1 to T3 expect the refusal), a floor
that cannot be read refuses a share spelling (T12), an exemption stands where its text puts it in the path
and not where its root is spelled, and a floor file root outranks the workspace that encloses it (T13, T17), a
configured workspace root is spelled as the path under it is (T14), the spelling ``list_files`` shows has no
namespace prefix (T15 here; BF-948's T13 and T14 through the verified reader), and the final component is
decided by the file it names: a stream suffix, trailing dots and spaces and another case do not make another
file of a floor file root or a credential name, on or off disk (T18 to T21; on POSIX the names stay distinct: T22).
"""

from __future__ import annotations

import ctypes
import os
import shutil
import tempfile
from pathlib import Path, PureWindowsPath
from types import SimpleNamespace
from typing import Any

import pytest

from probos.cognitive.swe_harness.tools import ListFilesTool, ReadFileTool
from probos.security import file_access
from probos.security.file_access import FileAccessDenied, protected_write_refusal, resolve_read_path
from tests.test_bf948_list_files_read_policy import _OUTSIDE, _PROTECTED, _link, _list, _runtime, _scene, _unlink

WINDOWS = pytest.mark.skipif(os.name != "nt", reason="BF-953: these are Windows path spellings")
_CONTENT = b"bf953 fixture"
_READ_PROTECTED = "read_file refused: path is protected: the runtime's data directory or a config file"
_READ_OUTSIDE = "read_file refused: path is outside every readable root"
_FLOOR_REASON = "path is protected: the runtime's data directory or a config file"
_OUTSIDE_REASON = "path is outside every readable root"
_UNVERIFIED_REASON = "path cannot be verified against the protected roots"
_LEAF_REASON = "that file holds credentials and is not readable"
````

SEARCH:
````python
    "UNC extended localhost", "UNC extended computer-name", "UNC localhost, dotdot",
]
_PARAMS = list(_FAMILIES)
````
REPLACE:
````python
    "UNC extended localhost", "UNC extended computer-name", "UNC localhost, dotdot",
]
# Amendment 1: a spelling that still names a share after its namespace prefix is gone. The floor refuses it by the
# identity of its own chain, and an exempt or a permitted root admits it only if the root's text names it, so where
# the ordinary spelling is admitted by one of those roots these are refused.
_SHARE_FAMILIES = frozenset({
    "UNC localhost admin share", "UNC 127.0.0.1 admin share", "UNC computer-name admin share",
    "UNC extended localhost", "UNC extended computer-name", "UNC localhost, dotdot",
})
_PARAMS = list(_FAMILIES)
````

SEARCH:
````python
        return "refused", exc.reason
    return "admitted", str(resolved)


@WINDOWS
@pytest.mark.parametrize("family", _PARAMS)
def test_every_spelling_gets_the_decision_of_the_ordinary_spelling(tmp_path: Path, family: str) -> None:
````
REPLACE:
````python
        return "refused", exc.reason
    return "admitted", str(resolved)


def _other_volume_dir(request: pytest.FixtureRequest, tmp_path: Path) -> Path:
    """A new directory on a local fixed volume other than *tmp_path*'s, removed when the test ends; a skip when there is none."""
    here = os.stat(tmp_path).st_dev
    for letter in "CDEFGHIJKLMNOPQRSTUVWXYZ":
        root = f"{letter}:\\"
        if ctypes.windll.kernel32.GetDriveTypeW(root) != 3:  # type: ignore[attr-defined]  # DRIVE_FIXED
            continue
        try:
            if os.stat(root).st_dev == here:
                continue
            made = Path(tempfile.mkdtemp(prefix="bf953-", dir=root)).resolve()
        except OSError:
            continue
        request.addfinalizer(lambda made=made: shutil.rmtree(made, ignore_errors=True))
        return made
    pytest.skip("BF-953 premise: this host has no other local volume to write to")


@WINDOWS
@pytest.mark.parametrize("family", _PARAMS)
def test_every_spelling_gets_the_decision_of_the_ordinary_spelling(tmp_path: Path, family: str) -> None:
````

SEARCH:
````python
    """T1: each spelling of a file is decided as its ordinary spelling is, against a directory root and a file root of
    the floor, an exempt root under the floor, and a permitted root; so is a file that is not on disk; and the path an
    admitted call returns is the resolved path and names the file."""
    lay = _fixture(tmp_path)
    floor = [lay.data.resolve(), lay.config.resolve()]
    exempt, permitted = [lay.work.resolve()], [lay.allowed.resolve()]
    cases = [
        (lay.floor_note, {"protected": floor, "exempt": exempt}, "refused"),
        (lay.config, {"protected": floor}, "refused"),
        (lay.neighbour, {"protected": floor}, "admitted"),
        (lay.work_note, {"protected": floor, "exempt": exempt}, "admitted"),
        (lay.allowed_note, {"permitted": permitted}, "admitted"),
        (lay.outside_note, {"permitted": permitted}, "refused"),
    ]
    for target, roots, expected in cases:
        ordinary = _decide(str(target), **roots)
        assert ordinary[0] == expected, f"premise: the ordinary spelling of {target.name}: {ordinary}"
        spelled = _decide(_spelling(family, target), **roots)
        assert spelled[0] == expected, f"{family} of {target.name}: {spelled}"
        if expected == "refused":
            assert spelled[1] == ordinary[1], f"{family} of {target.name}: another reason"
        else:
            assert Path(spelled[1]) == Path(spelled[1]).resolve(), "the path returned is a resolved path"
            assert os.path.samestat(os.stat(spelled[1]), os.stat(target)), "the path returned names the file"
    missing = [
        (lay.data, {"protected": floor}, "refused"),
        (lay.work, {"protected": floor, "exempt": exempt}, "admitted"),
        (lay.allowed, {"permitted": permitted}, "admitted"),
        (lay.outside, {"permitted": permitted}, "refused"),
    ]
    for directory, roots, expected in missing:
        absent = "missing note long name.txt"
        assert _decide(str(directory / absent), **roots)[0] == expected, "premise: the ordinary spelling"
        spelling = _spelling_or_none(family, directory)
        if spelling is not None:
            assert _decide(spelling + "\\" + absent, **roots)[0] == expected, f"{family}, not on disk"
````
REPLACE:
````python
    """T1: each spelling of a file is decided as its ordinary spelling is, against a directory root and a file root of
    the floor, an exempt root under the floor, and a permitted root; so is a file that is not on disk (a missing child of
    a directory, and a file root that is not on disk, whose share spellings are L2's); and the path an
    admitted call returns is the resolved path and names the file. The one exception is the share spellings
    (``_SHARE_FAMILIES``): only the floor decides them by identity, so where the ordinary spelling is admitted by an exempt
    or a permitted root they are refused, with the reason that root's refusal gives."""
    lay = _fixture(tmp_path)
    floor = [lay.data.resolve(), lay.config.resolve()]
    exempt, permitted = [lay.work.resolve()], [lay.allowed.resolve()]
    cases = [
        (lay.floor_note, {"protected": floor, "exempt": exempt}, "refused", None),
        (lay.config, {"protected": floor}, "refused", None),
        (lay.neighbour, {"protected": floor}, "admitted", None),
        (lay.work_note, {"protected": floor, "exempt": exempt}, "admitted", _FLOOR_REASON),
        (lay.allowed_note, {"permitted": permitted}, "admitted", _OUTSIDE_REASON),
        (lay.outside_note, {"permitted": permitted}, "refused", None),
    ]
    for target, roots, expected, share_reason in cases:
        ordinary = _decide(str(target), **roots)
        assert ordinary[0] == expected, f"premise: the ordinary spelling of {target.name}: {ordinary}"
        spelled = _decide(_spelling(family, target), **roots)
        if share_reason is not None and family in _SHARE_FAMILIES:
            assert spelled == ("refused", share_reason), f"{family} of {target.name}: {spelled}"
            continue
        assert spelled[0] == expected, f"{family} of {target.name}: {spelled}"
        if expected == "refused":
            assert spelled[1] == ordinary[1], f"{family} of {target.name}: another reason"
        else:
            assert Path(spelled[1]) == Path(spelled[1]).resolve(), "the path returned is a resolved path"
            assert os.path.samestat(os.stat(spelled[1]), os.stat(target)), "the path returned names the file"
    absent_root = lay.config.parent / "absent config long name.yaml"
    floor_absent = [*floor, absent_root.resolve()]
    missing = [
        (lay.data, {"protected": floor}, "refused", None, "missing note long name.txt"),
        (lay.work, {"protected": floor, "exempt": exempt}, "admitted", _FLOOR_REASON, "missing note long name.txt"),
        (lay.allowed, {"permitted": permitted}, "admitted", _OUTSIDE_REASON, "missing note long name.txt"),
        (lay.outside, {"permitted": permitted}, "refused", None, "missing note long name.txt"),
        (lay.config.parent, {"protected": floor_absent}, "refused", "L2", absent_root.name),  # an absent file root
    ]
    for directory, roots, expected, share_reason, absent in missing:
        assert _decide(str(directory / absent), **roots)[0] == expected, "premise: the ordinary spelling"
        if family == "default stream suffix":
            # The family is a stream of an existing file, so a directory has no spelling of it: the child's own suffix.
            assert _decide(str(directory / absent) + "::$DATA", **roots)[0] == expected, f"{family}, not on disk"
            continue
        spelling = _spelling_or_none(family, directory)
        if spelling is None:  # a premise: this host does not serve the family for a directory
            continue
        spelled = _decide(spelling + "\\" + absent, **roots)
        if share_reason == "L2" and family in _SHARE_FAMILIES:
            continue  # L2: a share spelling of a file root that is not on disk has no identity to compare
        if share_reason is not None and family in _SHARE_FAMILIES:
            assert spelled == ("refused", share_reason), f"{family}, not on disk: {spelled}"
        else:
            assert spelled[0] == expected, f"{family}, not on disk"
````

SEARCH:
````python
    """T2: ``ReadFileTool`` answers every spelling of a file as it answers the ordinary one."""
````
REPLACE:
````python
    """T2: ``ReadFileTool`` answers every spelling of a file as it answers the ordinary one; a share spelling of a file a
    permitted root admits is answered as outside every readable root."""
````

SEARCH:
````python
        spelled = await tool.invoke({"path": _spelling(family, note)})
        assert spelled.error == refusal, f"{family} of {note.name}: {spelled.error}"
        if refusal is None:
            assert "bf953 fixture" in repr(spelled.output)
````
REPLACE:
````python
        spelled = await tool.invoke({"path": _spelling(family, note)})
        want = _READ_OUTSIDE if refusal is None and family in _SHARE_FAMILIES else refusal
        assert spelled.error == want, f"{family} of {note.name}: {spelled.error}"
        if want is None:
            assert "bf953 fixture" in repr(spelled.output)
        else:
            assert spelled.output is None, family
````

SEARCH:
````python
    directory outside the permitted root is refused, and a spelling of the permitted root and of the agent
    workspace under the floor is listed."""
````
REPLACE:
````python
    directory outside the permitted root is refused, and a spelling of the permitted root and of the agent
    workspace under the floor is listed, except a share spelling of either, which is refused (the permitted root
    and the exemption name it by their text only)."""
````

SEARCH:
````python
    spelled = await _list(scene, [scene.allowed], "*", _spelling(family, scene.allowed))
    assert spelled.error is None, f"{family}: {spelled.error}"
    assert {Path(n).name for n in spelled.output["files"]} == {"allowed note long name.txt", "ok.txt", "sub"}, family
    workspace = await _list(scene, [], "*", _spelling(family, scene.workspace))
    assert workspace.error is None and [Path(n).name for n in workspace.output["files"]] == ["scratch.txt"], family
````
REPLACE:
````python
    spelled = await _list(scene, [scene.allowed], "*", _spelling(family, scene.allowed))
    workspace = await _list(scene, [], "*", _spelling(family, scene.workspace))
    if family in _SHARE_FAMILIES:
        assert spelled.error == _OUTSIDE and spelled.output is None, family
        assert workspace.error == _PROTECTED and workspace.output is None, family
        return
    assert spelled.error is None, f"{family}: {spelled.error}"
    assert {Path(n).name for n in spelled.output["files"]} == {"allowed note long name.txt", "ok.txt", "sub"}, family
    assert workspace.error is None and [Path(n).name for n in workspace.output["files"]] == ["scratch.txt"], family
````

SEARCH:
````python
    """T7: one identity for every name of a file, none for a path that names nothing, and none when the filesystem
    reports no file index."""
    note = tmp_path / "note.txt"
    note.write_bytes(_CONTENT)
    (tmp_path / "sub").mkdir()
    link = tmp_path / "note-link.txt"
    os.link(note, link)
    identity = file_access._file_identity(note)
    assert identity is not None
    assert file_access._file_identity(tmp_path / "sub" / ".." / "note.txt") == identity == file_access._file_identity(link)
    assert file_access._file_identity(tmp_path / "sub") != identity
    assert file_access._file_identity(tmp_path / "missing.txt") is None
    assert file_access._file_identity(Path("bad\x00name")) is None
    with monkeypatch.context() as patched:
        patched.setattr(file_access.os, "stat", lambda _path: SimpleNamespace(st_dev=7, st_ino=0))
        assert file_access._file_identity(note) is None
````
REPLACE:
````python
    """T7: one identity for every name of a file, none for a path that names nothing, and no answer (``_Unverifiable``,
    never ``None``) when the system cannot say: a name it rejects, a read it refuses, or no file index (zero)."""
    note = tmp_path / "note.txt"
    note.write_bytes(_CONTENT)
    (tmp_path / "sub").mkdir()
    link = tmp_path / "note-link.txt"
    os.link(note, link)
    identity = file_access._file_identity(note)
    assert identity is not None
    assert file_access._file_identity(tmp_path / "sub" / ".." / "note.txt") == identity == file_access._file_identity(link)
    assert file_access._file_identity(tmp_path / "sub") != identity
    assert file_access._file_identity(tmp_path / "missing.txt") is None
    assert file_access._file_identity(note / "child.txt") is None  # under a file: nothing is there
    with pytest.raises(file_access._Unverifiable):
        file_access._file_identity(Path("bad\x00name"))
    with monkeypatch.context() as patched:
        patched.setattr(file_access.os, "stat", lambda _path: SimpleNamespace(st_dev=7, st_ino=0))
        with pytest.raises(file_access._Unverifiable):
            file_access._file_identity(note)

    def refused(_path: Any) -> Any:
        raise PermissionError(13, "refused")

    with monkeypatch.context() as patched:
        patched.setattr(file_access.os, "stat", refused)
        with pytest.raises(file_access._Unverifiable):
            file_access._file_identity(note)
````

SEARCH:
````python
@WINDOWS
def test_a_share_path_no_root_covers_stays_admitted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """T10: containment of a share path is decided by identity. With the system's answers replaced (no host is
    contacted), a share path that is not the root and has no ancestor that is the root is not inside it, and one
    that has is."""
    root = _fixture(tmp_path).data.resolve()
    absent_root = root.parent / "no-such-root"
    same_as_root = Path("\\\\bf953-alias\\share\\floor")
    known = {root: (1, 1), same_as_root: (1, 1), absent_root: None}
    monkeypatch.setattr(file_access, "_file_identity", lambda path: known[path] if path in known else (2, hash(path)))
    elsewhere = Path("\\\\bf953-remote\\share\\dir\\note.txt")
    inside = same_as_root / "sub" / "note.txt"
    assert file_access._longest_match(elsewhere, [root]) is None
    assert file_access._longest_match(inside, [root]) == root
    assert file_access._longest_match(same_as_root, [root]) == root
    assert file_access._longest_match(inside, [absent_root]) is None
````
REPLACE:
````python
@WINDOWS
def test_a_share_path_no_root_covers_stays_admitted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """T10: containment of a share path by a floor root is decided by identity, and only for the floor. With the system's
    answers replaced (no host is contacted): a share path that is not the root, has no ancestor that is the root and does
    not reach the root's volume is not inside it; one that has is, standing at that ancestor's count of parts; one whose
    chain is on the root's volume only through a link is inside at its own count; and a root that is not on disk contains
    nothing. An exempt or a permitted root is never matched by identity."""
    root = _fixture(tmp_path).data.resolve()
    absent_root = root.parent / "no-such-root"
    same_as_root = Path("\\\\bf953-alias\\share\\floor")
    linked = Path("\\\\bf953-link\\share\\jx\\note.txt")
    known = {root: (1, 1), same_as_root: (1, 1), absent_root: None, linked.parent: (1, 5), linked: (1, 6)}
    monkeypatch.setattr(file_access, "_file_identity", lambda path: known[path] if path in known else (2, hash(path)))
    elsewhere = Path("\\\\bf953-remote\\share\\dir\\note.txt")
    inside = same_as_root / "sub" / "note.txt"
    assert file_access._match_position(elsewhere, [root], floor=True) is None
    assert file_access._match_position(inside, [root], floor=True) == len(same_as_root.parts)
    assert file_access._match_position(same_as_root, [root], floor=True) == len(same_as_root.parts)
    assert file_access._match_position(inside, [absent_root], floor=True) is None
    assert file_access._match_position(inside, [root]) is None, "an exempt or a permitted root is matched by text only"
    assert file_access._match_position(linked, [root], floor=True) == len(linked.parts)
    known[root] = (3, 1)
    assert file_access._match_position(linked, [root], floor=True) is None, "a root on a volume the chain never reaches"
    known[root] = (2, 1)
    assert file_access._match_position(elsewhere, [root], floor=True) is None, "a root on the volume of the chain's top"
    twin = Path("\\\\bf953-twin\\share\\one\\two")
    known.update({root: (1, 1), twin.parent: (1, 1), twin: (1, 1)})
    assert file_access._match_position(twin, [root], floor=True) == len(twin.parts), "the deepest part with that identity"
    deeper = same_as_root / "sub"
    for roots in ([root, deeper], [deeper, root]):
        assert file_access._match_position(inside, roots, floor=True) == len(deeper.parts), "the deepest root wins"


@WINDOWS
async def test_a_share_spelling_is_never_admitted_by_a_root_its_text_does_not_name(
    tmp_path: Path, request: pytest.FixtureRequest,
) -> None:
    """T11 (Amendment 1, review finding 1 and the second reviewer's R2): a share spelling of a path through a link to another
    volume, below a permitted root, is refused, as the ordinary spelling is: the share's text names the permitted root's
    directory, the file is not in it. The same through the floor: a link into the interior of a floor root on that other
    volume, through the policy and through ``read_file`` and ``list_files``. And a share spelling the floor cannot contain
    (the floor is on the first volume) is still admitted."""
    lay = _fixture(tmp_path)
    other = _other_volume_dir(request, tmp_path)
    (other / "target directory long name").mkdir()
    (other / "target directory long name" / "target note long name.txt").write_bytes(_CONTENT)
    (other / "floor tree long name" / "interior directory long name").mkdir(parents=True)
    (other / "floor tree long name" / "interior directory long name" / "interior note long name.txt").write_bytes(_CONTENT)
    outward = lay.allowed / "link to the other volume"
    interior = lay.allowed / "link into the floor interior"
    _link(outward, other / "target directory long name")
    _link(interior, other / "floor tree long name" / "interior directory long name")
    try:
        note, deep = outward / "target note long name.txt", interior / "interior note long name.txt"
        assert os.stat(note).st_dev != os.stat(lay.allowed).st_dev, "premise: the link leaves the volume"
        permitted, floor = [lay.allowed.resolve()], [(other / "floor tree long name").resolve()]
        for target in (note, deep):
            spelled = _spelling_or_none("UNC localhost admin share", target)
            if spelled is None:
                pytest.skip("BF-953 premise: this host does not serve the local share spelling of the linked file")
            assert _decide(str(target), permitted=permitted) == ("refused", _OUTSIDE_REASON), "premise: the ordinary spelling"
            assert _decide(spelled, permitted=permitted) == ("refused", _OUTSIDE_REASON), target.name
        assert _decide(str(deep), protected=floor) == ("refused", _FLOOR_REASON), "premise: the file is in the floor"
        spelled = _spelling("UNC localhost admin share", deep)
        assert _decide(spelled, protected=floor) == ("refused", _FLOOR_REASON), "the interior of the floor, through a link"
        here = [lay.data.resolve()]
        assert _decide(_spelling("UNC localhost admin share", note), protected=here)[0] == "admitted", "no floor root is there"
        floor_runtime = SimpleNamespace(data_dir=other / "floor tree long name", config=SimpleNamespace(
            security_infra=SimpleNamespace(read_roots=[]), execution=SimpleNamespace(workspace_root=str(lay.work)),
        ))
        read = await ReadFileTool(floor_runtime).invoke({"path": spelled})
        assert read.error == _READ_PROTECTED and read.output is None, "read_file: the interior of the floor"
        listing = await ListFilesTool(floor_runtime).invoke(
            {"pattern": "*", "path": _spelling("UNC localhost admin share", interior)},
        )
        assert listing.error == _PROTECTED and listing.output is None, "list_files: the interior of the floor"
        confined = SimpleNamespace(data_dir=lay.data, config=SimpleNamespace(
            security_infra=SimpleNamespace(read_roots=[str(lay.allowed)]), execution=SimpleNamespace(workspace_root=str(lay.work)),
        ))
        read = await ReadFileTool(confined).invoke({"path": _spelling("UNC localhost admin share", note)})
        assert read.output is None and read.error in (_READ_OUTSIDE, _READ_PROTECTED), "read_file: a permitted root"
    finally:
        _unlink(outward)
        _unlink(interior)


@WINDOWS
@pytest.mark.parametrize("failure", ["a read the system refuses", "no file index"])
async def test_a_floor_that_cannot_be_read_refuses_a_share_spelling_and_nothing_else(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str,
) -> None:
    """T12 (Amendment 1, review finding 3): the floor root's identity cannot be read (or has no file index) while a
    permitted root's can. A share spelling of a floor file is refused with the bounded reason, through the policy and
    through ``read_file``, and gives no content; the ordinary spelling is refused as before; a drive-letter path outside
    the floor asks for no identity and is admitted."""
    scene = _scene(tmp_path)
    note = scene.data / "floor note long name.txt"
    note.write_bytes(_CONTENT)
    (scene.allowed / "allowed note long name.txt").write_bytes(_CONTENT)
    floor_text = os.path.normcase(str(scene.data))
    real_stat = os.stat

    def stat(path: Any, *args: Any, **kwargs: Any) -> Any:
        info = real_stat(path, *args, **kwargs)
        if os.path.normcase(str(path)) != floor_text:
            return info
        if failure == "no file index":
            return os.stat_result((info.st_mode, 0, info.st_dev, info.st_nlink, info.st_uid, info.st_gid, info.st_size,
                                   int(info.st_atime), int(info.st_mtime), int(info.st_ctime)))
        raise PermissionError(13, "refused")

    roots = {"protected": [scene.data.resolve()], "permitted": [scene.root]}
    shared = _spelling("UNC localhost admin share", note)
    assert _decide(shared, **roots) == ("refused", _FLOOR_REASON), "premise: the floor is read"
    monkeypatch.setattr(file_access.os, "stat", stat)
    assert _decide(shared, **roots) == ("refused", _UNVERIFIED_REASON)
    assert _decide(str(note), **roots) == ("refused", _FLOOR_REASON)
    assert _decide(str(scene.allowed / "allowed note long name.txt"), **roots)[0] == "admitted"
    reader = ReadFileTool(_runtime(scene, read_roots=[scene.root]))
    answered = await reader.invoke({"path": shared})
    assert answered.error == f"read_file refused: {_UNVERIFIED_REASON}" and answered.output is None


def _device_spelling(target: Path) -> str | None:
    """The ``\\\\?\\GLOBALROOT`` spelling of the existing *target*, or None when the system names no device for its drive."""
    drive, rest = os.path.splitdrive(str(target))
    buffer = ctypes.create_unicode_buffer(512)
    if not ctypes.windll.kernel32.QueryDosDeviceW(drive, buffer, len(buffer)):  # type: ignore[attr-defined]
        return None
    return "\\\\?\\GLOBALROOT" + buffer.value.split("\0")[0] + rest


@WINDOWS
@pytest.mark.parametrize("kind", ["device", "extended prefix", "share", "extended UNC"])
def test_an_exemption_stands_where_its_text_puts_it_in_the_path_not_where_its_root_is_spelled(
    tmp_path: Path, kind: str,
) -> None:
    """T13 (Amendment 1, review finding 2): an exempt root that names the floor directory or its parent in another
    spelling never lifts the floor, for the ordinary spelling of a floor file or a share spelling of it. The exemption of
    the workspace under the floor lifts it, spelled with an extended prefix too; a root spelled so that its text does not
    name the ordinary path lifts nothing."""
    lay = _fixture(tmp_path)
    floor = [lay.data.resolve()]
    drive, rest = os.path.splitdrive(str(lay.data))
    spellings = {
        "device": _device_spelling(lay.data),
        "extended prefix": "\\\\?\\" + str(lay.data),
        "share": f"\\\\localhost\\{drive[0]}${rest}",
        "extended UNC": f"\\\\?\\UNC\\localhost\\{drive[0]}${rest}",
    }
    if spellings[kind] is None:
        pytest.skip(f"BF-953 premise: this host has no {kind} spelling")
    assert _decide(str(lay.work_note), protected=floor, exempt=[lay.work.resolve()])[0] == "admitted", "premise"
    for named in (Path(str(spellings[kind])), Path(str(spellings[kind])).parent):
        assert _decide(str(lay.floor_note), protected=floor, exempt=[named])[0] == "refused", f"{kind}: {named}"
        shared = _spelling_or_none("UNC localhost admin share", lay.floor_note)
        if shared is not None:
            assert _decide(shared, protected=floor, exempt=[named])[0] == "refused", f"{kind}, share candidate: {named}"
    workspace = "\\\\?\\" + str(lay.work)
    assert _decide(str(lay.work_note), protected=floor, exempt=[Path(workspace)])[0] == "admitted", "the prefix is only text"
    configured = SimpleNamespace(data_dir=lay.data, config=SimpleNamespace(
        security_infra=SimpleNamespace(read_roots=[]), execution=SimpleNamespace(workspace_root=spellings[kind]),
    ))
    with pytest.raises(FileAccessDenied):
        file_access.resolve_for_runtime(str(lay.floor_note), configured)


@WINDOWS
def test_a_workspace_root_configured_as_a_short_path_is_spelled_as_its_candidates_are(tmp_path: Path) -> None:
    """T14 (Amendment 1, review finding 5): a workspace root configured as an 8.3 short path is the exempt root and the
    permitted root its long path is, so the workspace is readable and listed as the ordinary configuration reads it."""
    lay = _fixture(tmp_path)
    short = _short(str(lay.work))
    if short is None:
        pytest.skip("BF-953 premise: this volume gives the workspace directory no 8.3 name")
    ordinary = SimpleNamespace(data_dir=lay.data, config=SimpleNamespace(
        security_infra=SimpleNamespace(read_roots=[str(lay.allowed)]), execution=SimpleNamespace(workspace_root=str(lay.work)),
    ))
    configured = SimpleNamespace(data_dir=lay.data, config=SimpleNamespace(
        security_infra=SimpleNamespace(read_roots=[str(lay.allowed)]), execution=SimpleNamespace(workspace_root=short),
    ))
    assert file_access.workspace_exempt_roots(configured) == file_access.workspace_exempt_roots(ordinary) == [lay.work.resolve()]
    assert file_access.permitted_read_roots(configured)[-1] == lay.work.resolve()
    assert file_access.resolve_for_runtime(str(lay.work_note), ordinary) == lay.work_note.resolve()
    assert file_access.resolve_for_runtime(str(lay.work_note), configured) == lay.work_note.resolve()
    with pytest.raises(FileAccessDenied):
        file_access.resolve_for_runtime(str(lay.floor_note), configured)


_PLAIN_CASES = [
    ("\\\\?\\C:\\data\\note.txt", "C:\\data\\note.txt"),
    ("\\\\.\\C:\\data", "C:\\data"),
    ("\\\\?\\UNC\\host\\share\\dir\\f.txt", "\\\\host\\share\\dir\\f.txt"),
    ("C:\\data\\note.txt", "C:\\data\\note.txt"),
    ("\\\\host\\share\\dir", "\\\\host\\share\\dir"),
    ("\\\\?\\Volume{4d83c44e-bb8a-4ae4-b23a-fe55aac6532d}\\data", "\\\\?\\Volume{4d83c44e-bb8a-4ae4-b23a-fe55aac6532d}\\data"),
]


@pytest.mark.parametrize(("text", "expected"), _PLAIN_CASES)
def test_the_plain_spelling_drops_the_namespace_prefix_on_windows_only(text: str, expected: str) -> None:
    """T15: the spelling a reader that rejects the prefix is given: the prefix of a drive path or an extended UNC path is
    dropped on Windows; every other path, and every path on another platform, is returned as it is."""
    assert str(file_access.plain_spelling(Path(text))) == (expected if os.name == "nt" else str(Path(text)))


@pytest.mark.parametrize("text", [case[0] for case in _NAMESPACE_CASES if case[0] and case[0] != case[1]])
def test_a_namespace_free_root_stands_at_the_same_count_of_parts(text: str) -> None:
    """T16: the position a root stands at in the path's own chain is its count of parts, and dropping a namespace prefix
    changes no count: the exemption's rank does not depend on how its root is spelled."""
    assert len(PureWindowsPath(text).parts) == len(PureWindowsPath(file_access._namespace_free(text)).parts)


@WINDOWS
@pytest.mark.parametrize("kind", ["ordinary", "extended prefix", "device", "share", "extended UNC", "link to the floor"])
def test_a_loaded_config_file_outranks_the_workspace_that_encloses_it(tmp_path: Path, kind: str) -> None:
    """T17 (the second reviewer's R1): the loaded config file is a floor file root inside the exempt workspace, which is
    inside the data directory. However the workspace root is configured (in another spelling, or as a link to the data
    directory), the file is refused in its ordinary spelling and in the extended, device and share spellings of it: a file
    root outranks the workspace that encloses it, and two roots that name one directory tie. Where the configured root is
    the workspace itself, a workspace file beside the config file is still admitted; where it names the data directory it
    is not."""
    root = tmp_path.resolve()
    data = root / "floor data directory"
    workspace = data / "workspace directory long name"
    workspace.mkdir(parents=True)
    config, note = workspace / "loaded config long name.yaml", workspace / "workspace note long name.txt"
    config.write_bytes(_CONTENT)
    note.write_bytes(_CONTENT)
    drive, rest = os.path.splitdrive(str(workspace))
    link = root / "a link directory long name"
    configured = {
        "ordinary": str(workspace),
        "extended prefix": "\\\\?\\" + str(workspace),
        "device": _device_spelling(workspace),
        "share": f"\\\\localhost\\{drive[0]}${rest}",
        "extended UNC": f"\\\\?\\UNC\\localhost\\{drive[0]}${rest}",
        "link to the floor": str(link),
    }[kind]
    if configured is None:
        pytest.skip(f"BF-953 premise: this host has no {kind} spelling")

    def runtime(workspace_root: str) -> SimpleNamespace:
        return SimpleNamespace(data_dir=data, config_path=config, config=SimpleNamespace(
            security_infra=SimpleNamespace(read_roots=[]), execution=SimpleNamespace(workspace_root=workspace_root),
        ))

    ordinary = runtime(str(workspace))
    assert config.resolve() in file_access.protected_config_files(ordinary), "premise: the config file is a floor root"
    assert file_access.resolve_for_runtime(str(note), ordinary) == note.resolve(), "premise: the workspace is lifted"
    if kind == "link to the floor":
        _link(link, data)
    try:
        candidates = {
            "ordinary": str(config),
            "extended prefix": "\\\\?\\" + str(config),
            "device": _device_spelling(config),
            "share": _spelling_or_none("UNC localhost admin share", config),
        }
        for name, candidate in candidates.items():
            if candidate is None:
                continue  # a premise: this host has no such spelling of the file
            try:
                file_access.resolve_for_runtime(candidate, runtime(configured))
            except FileAccessDenied:
                continue
            pytest.fail(f"the {name} spelling of the loaded config file was admitted with the workspace root as {kind}")
        configured_runtime = runtime(configured)
        roots = {
            "protected_roots": file_access.protected_read_roots(configured_runtime),
            "exempt_roots": file_access.workspace_exempt_roots(configured_runtime),
        }
        with pytest.raises(FileAccessDenied):
            file_access.read_verified_file(config, **roots)
        bounded = file_access.read_bounded_utf8(str(config), authorized_root=workspace, **roots)
        assert bounded.status is file_access.BoundedReadStatus.DENIED and bounded.text == ""
        if kind in ("ordinary", "extended prefix", "device"):
            assert file_access.resolve_for_runtime(str(note), runtime(configured)) == note.resolve()
        if kind == "link to the floor":
            with pytest.raises(FileAccessDenied):
                file_access.resolve_for_runtime(str(note), runtime(configured))
    finally:
        if kind == "link to the floor":
            _unlink(link)


_FINAL_COMPONENT_SPELLINGS = [":zz", ":zz:$DATA", "::$DATA", ".", " ", ". "]


@pytest.mark.parametrize(
    ("name", "base"),
    [
        ("config.yaml", "config.yaml"), ("config.yaml:zz", "config.yaml"), ("config.yaml:zz:$DATA", "config.yaml"),
        ("config.yaml::$DATA", "config.yaml"), ("config.yaml.", "config.yaml"), ("config.yaml ", "config.yaml"),
        ("config.yaml. ", "config.yaml"), ("config.yaml:zz.", "config.yaml"), ("archive.tar.gz", "archive.tar.gz"),
        (".hidden", ".hidden"), (":zz", ":zz"), ("...", "..."), ("", ""),
    ],
)
def test_the_base_name_of_a_final_component(name: str, base: str) -> None:
    """T18: the file a final component names on Windows (any platform runs the text): the text from the first colon, then
    trailing dots and spaces, are dropped; a name that would be empty stays as it is."""
    assert file_access._base_name(name) == base


@WINDOWS
@pytest.mark.parametrize("suffix", _FINAL_COMPONENT_SPELLINGS)
def test_a_stream_or_trailing_dot_or_space_spelling_of_a_floor_file_is_decided_as_the_file_is(
    tmp_path: Path, suffix: str,
) -> None:
    """T19 (the second reviewer's R3): a named stream, a stream with its type, the default stream, trailing dots and trailing
    spaces on the final component of a floor file root, or of a credential vault name, are decided as the file is, with its
    reason, in the ordinary, extended-prefix and share spellings; a neighbour in the same directory with the same suffix is
    admitted, and keeps the suffix it was given."""
    lay = _fixture(tmp_path)
    vault = lay.outside / "credential_vault.json"
    vault.write_bytes(_CONTENT)
    floor = [lay.data.resolve(), lay.config.resolve()]
    for target, reason in ((lay.config, _FLOOR_REASON), (vault, _LEAF_REASON)):
        ordinary = _decide(str(target), protected=floor)
        assert ordinary == ("refused", reason), f"premise: the ordinary spelling of {target.name}: {ordinary}"
        assert _decide(str(target) + suffix, protected=floor) == ordinary, f"{target.name}{suffix!r}"
        assert _decide("\\\\?\\" + str(target) + suffix, protected=floor) == ordinary, f"extended {target.name}{suffix!r}"
        shared = _spelling_or_none("UNC localhost admin share", target)
        if shared is not None:
            assert _decide(shared + suffix, protected=floor) == ordinary, f"share {target.name}{suffix!r}"
    admitted = _decide(str(lay.neighbour) + suffix, protected=floor)
    assert admitted[0] == "admitted", f"a neighbour with {suffix!r}: {admitted}"


@WINDOWS
async def test_a_named_stream_of_a_floor_file_is_refused_and_one_of_a_neighbour_is_read(tmp_path: Path) -> None:
    """T20 (the second reviewer's R3), through ``ReadFileTool`` with a real named stream: the loaded config file's stream
    and a credential vault name's stream are refused with the file's own reason and give no content; the write side refuses
    the same name; a neighbour's stream is read, by the path as it was given."""
    lay = _fixture(tmp_path)
    vault = lay.outside / "credential_vault.json"
    vault.write_bytes(_CONTENT)
    try:
        for note in (lay.config, vault, lay.neighbour):
            Path(str(note) + ":zz").write_bytes(b"stream fixture")
    except OSError:
        pytest.skip("BF-953 premise: this volume makes no named streams")
    runtime = SimpleNamespace(config_path=lay.config, data_dir=lay.data, config=SimpleNamespace(
        security_infra=SimpleNamespace(read_roots=[]), execution=SimpleNamespace(workspace_root=str(lay.work)),
    ))
    reader = ReadFileTool(runtime)
    config_stream = await reader.invoke({"path": str(lay.config) + ":zz"})
    assert config_stream.error == _READ_PROTECTED and config_stream.output is None
    vault_stream = await reader.invoke({"path": str(vault) + ":zz"})
    assert vault_stream.error == f"read_file refused: {_LEAF_REASON}" and vault_stream.output is None
    assert protected_write_refusal(str(lay.config) + ":zz", runtime=runtime) is not None, "the write side refuses the name"
    neighbour_stream = await reader.invoke({"path": str(lay.neighbour) + ":zz"})
    assert neighbour_stream.error is None and "stream fixture" in repr(neighbour_stream.output)


_ABSENT_SPELLINGS = [
    "forward slashes", "swapped case", "trailing dot", "trailing space", "default stream", "named stream",
    "extended prefix", "device prefix",
]


def _absent_spelling(kind: str, text: str) -> str:
    return {
        "forward slashes": text.replace("\\", "/"), "swapped case": text.swapcase(), "trailing dot": text + ".",
        "trailing space": text + " ", "default stream": text + "::$DATA", "named stream": text + ":zz",
        "extended prefix": "\\\\?\\" + text, "device prefix": "\\\\.\\" + text,
    }[kind]


@WINDOWS
@pytest.mark.parametrize("kind", _ABSENT_SPELLINGS)
def test_an_absent_file_root_and_an_absent_credential_name_are_decided_in_every_spelling_alike(
    tmp_path: Path, kind: str,
) -> None:
    """T21 (the second reviewer's R6): a floor file root that is not on disk, and a credential vault name that is not on
    disk, are refused in every spelling of the final component and of the path that this host serves (forward slashes,
    another case, trailing dot or space, a stream suffix, the extended and device prefixes), with the ordinary spelling's
    reason; an absent neighbour in the same spelling is admitted. The share spelling of an absent file root is not
    decided here: a root that is not on disk has no identity to compare (L2)."""
    lay = _fixture(tmp_path)
    absent_root = lay.config.parent / "absent config long name.yaml"
    absent_vault = lay.outside / "credential_vault.json"
    absent_neighbour = lay.config.parent / "absent neighbour long name.yaml"
    assert not any(path.exists() for path in (absent_root, absent_vault, absent_neighbour)), "premise: none is on disk"
    floor = [lay.data.resolve(), lay.config.resolve(), absent_root.resolve()]
    for target, reason in ((absent_root, _FLOOR_REASON), (absent_vault, _LEAF_REASON)):
        assert _decide(str(target), protected=floor) == ("refused", reason), "premise: the ordinary spelling"
        spelled = _decide(_absent_spelling(kind, str(target)), protected=floor)
        assert spelled == ("refused", reason), f"{kind} of {target.name}: {spelled}"
    assert _decide(str(absent_neighbour), protected=floor)[0] == "admitted", "premise"
    spelled = _decide(_absent_spelling(kind, str(absent_neighbour)), protected=floor)
    assert spelled[0] == "admitted", f"{kind} of a neighbour: {spelled}"


@pytest.mark.skipif(os.name == "nt", reason="BF-953: on Windows these names are one file")
def test_a_posix_name_that_differs_by_case_dot_space_or_colon_is_another_file_for_the_floor(tmp_path: Path) -> None:
    """T22: on POSIX the final component is compared as it is: another case, a trailing dot or space, or a colon suffix is
    another file, so none of them is a floor file root or a credential vault name; the names themselves are."""
    root = tmp_path.resolve()
    (root / "vault").mkdir()
    config_names = ["config.yaml", "Config.yaml", "config.yaml.", "config.yaml ", "config.yaml:zz"]
    vault_names = ["credential_vault.json", "Credential_vault.json", "credential_vault.json.", "credential_vault.json ",
                   "credential_vault.json:zz"]
    for name in config_names:
        (root / name).write_bytes(_CONTENT)
    for name in vault_names:
        (root / "vault" / name).write_bytes(_CONTENT)
    if len(list(root.iterdir())) != len(config_names) + 1 or len(list((root / "vault").iterdir())) != len(vault_names):
        pytest.skip("BF-953 premise: this filesystem folds case, so the names are not distinct files")
    assert _decide(str(root / "config.yaml"), protected=[root / "config.yaml"])[0] == "refused"
    for name in config_names[1:]:
        assert _decide(str(root / name), protected=[root / "config.yaml"])[0] == "admitted", name
    assert _decide(str(root / "vault" / vault_names[0])) == ("refused", _LEAF_REASON)
    for name in vault_names[1:]:
        assert _decide(str(root / "vault" / name))[0] == "admitted", name
````

### 7.5 M5 (Amendment 2)

All blocks are against `34bd9153`. **Apply B6-2 first (red, G6), then B6-1.** Where prose differs from a block, the block wins. `plain_spelling` stays public (it is `reader_spelling`'s first step and T15's subject). B6-2 adds one import to the BF-948 test module's list (`SECRET_NAME`) and edits no BF-948 file.

**B6-1** `src/probos/security/file_access.py`

SEARCH:
````
# textually name (BF-953 Amendment 1). The floor's file roots and the credential names are decided on the file the
# final component names (``_base_file``). Elsewhere containment is the textual test.
````
REPLACE:
````
# textually name (BF-953 Amendment 1). The floor's file roots and the credential names are decided on the file the
# final component names (``_base_file``), a root's as well as a candidate's (BF-953 Amendment 2). That is a rule on
# the text that only adds refusals, not a statement that the names are one file: in the extended namespace a name that
# ends in a dot or a space is another file, and it is refused too. Elsewhere containment is the textual test.
````

SEARCH:
````
    r"""BF-953: *text*, a path as ``str(WindowsPath)`` spells it, without its Windows namespace prefix.

    ``\\?\UNC\host\share\x`` is ``\\host\share\x``; ``\\?\C:\x`` and ``\\.\C:\x`` are ``C:\x``. Any other
    text (a volume or device name, a drive-relative form, a path of another platform) is returned as it is.
    Pure: it reads nothing and does not depend on the platform it runs on.
    """
````
REPLACE:
````
    r"""BF-953: *text*, a path as ``str(WindowsPath)`` spells it, without its Windows namespace prefix: the form in which
    a path and a root are compared as text.

    ``\\?\UNC\host\share\x`` is ``\\host\share\x``; ``\\?\C:\x`` and ``\\.\C:\x`` are ``C:\x``, and the bare drive
    ``\\?\C:`` is ``C:``. Any other text (a volume or device name, a drive-relative form with a path, a path of another
    platform) is returned as it is. Pure: it reads nothing and does not depend on the platform it runs on. It is a form for
    comparing text, not a statement about files: in the extended namespace a name that ends in a dot or a space is another
    file than the one the ordinary spelling names (:func:`reader_spelling`).
    """
````

SEARCH:
````
    an admitted read keeps the path as resolved. Pure: it reads nothing."""
    if os.name != "nt":
        return path
    base = _base_name(path.name)
    return path.with_name(base) if base != path.name else path


def _protected_leaf(path: Path) -> bool:
````
REPLACE:
````
    an admitted read keeps the path as resolved. It is a rule on the text that only adds refusals (L14). Pure: it reads
    nothing."""
    if os.name != "nt":
        return path
    base = _base_name(path.name)
    return path.with_name(base) if base != path.name else path


def _floor_roots(roots: Sequence[Path]) -> list[Path]:
    """BF-953 (Amendment 2): the floor roots *roots*, each root followed by the file its final component names where that is
    another spelling (:func:`_base_file`).

    A floor file root is compared by the file it names, as a candidate is, so a configuration loaded as
    ``loaded.yaml:settings`` refuses a read of ``loaded.yaml:settings`` and of ``loaded.yaml``. Each root stays as it is
    spelled, so no refusal a root made is lost: the result equals *roots* for every directory root a system resolves, for an
    ordinary file root and on another platform. A root spelled in the extended namespace with a trailing dot or space adds
    the directory or file its base names, a refusal only (L16). Pure: it reads nothing."""
    named = [_base_file(root) for root in roots]
    return [*roots, *(base for root, base in zip(roots, named) if base != root)]


def _protected_leaf(path: Path) -> bool:
````

SEARCH:
````
    (:func:`_namespace_free`); any other path, and every path on another platform, is returned as it is. Pure: it
    reads nothing. A final component that ends in a dot or a space is not the same file once the prefix is gone.
    """
    return Path(_namespace_free(str(path))) if os.name == "nt" else path
````
REPLACE:
````
    (:func:`_namespace_free`); any other path, and every path on another platform, is returned as it is. Pure: it
    reads nothing. A component that ends in a dot or a space does not name the same file once the prefix is gone:
    :func:`reader_spelling` says whether any ordinary spelling names the file.
    """
    return Path(_namespace_free(str(path))) if os.name == "nt" else path


def reader_spelling(path: Path) -> Path | None:
    """BF-953 (Amendment 2): the spelling of *path* that a reader which rejects a Windows namespace prefix opens as the file
    *path* names, or ``None`` when no ordinary spelling names it.

    On Windows it is :func:`plain_spelling` of *path* when every component of that spelling after its anchor names, as an
    ordinary path, what it names in the extended namespace: none ends in a dot or a space (the system drops both from an
    ordinary path, so such a name opens a neighbour or nothing), and no part of the spelling is a reserved device name (the
    system opens the device, and the verified reader rejects the spelling). A path that never had a prefix is held to the
    same test. Any other path, and every path on another platform, is returned as :func:`plain_spelling` returns it.
    Pure: it reads nothing."""
    shown = plain_spelling(path)
    if os.name != "nt":
        return shown
    ordinary = PureWindowsPath(str(shown))
    names = ordinary.parts[1:] if ordinary.anchor else ordinary.parts
    if any(name != name.rstrip(" .") for name in names):
        return None
    if any(part.is_reserved() for part in (ordinary, *ordinary.parents)):
        return None
    return shown
````

SEARCH:
````
    its text names that root, and a floor that cannot be read for a share or device spelling refuses it. What is
    returned is the resolved path itself, in the spelling it was resolved to, never a rewritten one: it names the file
    the decision was made on (a named stream keeps its suffix).
    """
````
REPLACE:
````
    its text names that root, and a floor that cannot be read for a share or device spelling refuses it. A floor file
    root is compared by the file its own final component names, as the candidate is (:func:`_floor_roots`). What is
    returned is the resolved path itself, as ``Path.resolve()`` spelled it, never a rewritten one: it names the file the
    decision was made on (``resolve()`` keeps a named stream's suffix and drops a trailing dot or space and the default
    stream's type from a file on disk).
    """
````

SEARCH:
````
        protect = _match_position(base_file, protected_roots, on_disk, floor=True)
````
REPLACE:
````
        protect = _match_position(base_file, _floor_roots(protected_roots), on_disk, floor=True)
````

SEARCH:
````
def permitted_read_roots(runtime: Any) -> list[Path]:
    """Operator POLICY: confine reads to these roots, or ``[]`` for no limit.
````
REPLACE:
````
def _workspace_root(runtime: Any) -> Path | None:
    """BF-758, BF-953 (Amendment 2): the agent workspace root *runtime* configures, or ``None`` when it cannot be composed.

    It is resolved as a candidate is, so the root and a path under it are spelled alike (a configured 8.3 short path or an
    unresolved data directory would otherwise name it as no candidate does). A root the system cannot resolve (a text with
    a NUL, a link that does not end) is returned as it was composed, as before BF-953: no candidate is under it, so a
    configured read policy still refuses every path outside its other roots and the exempt list lifts nothing."""
    cfg = getattr(getattr(runtime, "config", None), "execution", None)
    workspace = getattr(cfg, "workspace_root", "") or _DEFAULT_WORKSPACE_ROOT
    try:
        from probos.execution.workspace import _resolve_workspace_root

        composed = _resolve_workspace_root(workspace)
    except Exception:
        logger.debug("BF-758: workspace root unresolved", exc_info=True)
        return None
    try:
        return composed.resolve()
    except (OSError, RuntimeError, ValueError):
        logger.debug("BF-953: workspace root %r does not resolve; it is kept as composed", workspace, exc_info=True)
        return composed


def permitted_read_roots(runtime: Any) -> list[Path]:
    """Operator POLICY: confine reads to these roots, or ``[]`` for no limit.
````

SEARCH:
````
    cfg = getattr(getattr(runtime, "config", None), "execution", None)
    workspace = getattr(cfg, "workspace_root", "") or _DEFAULT_WORKSPACE_ROOT
    try:
        from probos.execution.workspace import _resolve_workspace_root

        # BF-953 (Amendment 1): resolved as the candidate is, so the root and a path under it are spelled alike
        # (a configured 8.3 short path or an unresolved data directory would otherwise name it as no candidate does).
        roots.append(_resolve_workspace_root(workspace).resolve())
    except Exception:
        logger.debug("BF-758: workspace root unresolved", exc_info=True)
    return roots
````
REPLACE:
````
    workspace = _workspace_root(runtime)
    if workspace is not None:
        roots.append(workspace)
    return roots
````

SEARCH:
````
    """The agent workspace tree, which lives under the data dir but is theirs."""
    cfg = getattr(getattr(runtime, "config", None), "execution", None)
    workspace = getattr(cfg, "workspace_root", "") or _DEFAULT_WORKSPACE_ROOT
    try:
        from probos.execution.workspace import _resolve_workspace_root

        # BF-953 (Amendment 1): resolved as the candidate is (see ``permitted_read_roots``).
        return [_resolve_workspace_root(workspace).resolve()]
    except Exception:
        logger.debug("BF-758: workspace root unresolved", exc_info=True)
        return []
````
REPLACE:
````
    """The agent workspace tree, which lives under the data dir but is theirs."""
    workspace = _workspace_root(runtime)
    return [] if workspace is None else [workspace]
````

**B6-2** `tests/test_bf953_read_floor_spellings.py`

SEARCH:
````
namespace prefix (T15 here; BF-948's T13 and T14 through the verified reader), and the final component is
decided by the file it names: a stream suffix, trailing dots and spaces and another case do not make another
file of a floor file root or a credential name, on or off disk (T18 to T21; on POSIX the names stay distinct: T22).
"""
````
REPLACE:
````
namespace prefix (T15 here; BF-948's T13 and T14 through the verified reader), and the final component is
decided by the file it names: a floor file root or a credential name is refused in every spelling of its final
component that a stream suffix, trailing dots and spaces and (for a name) another case make, on or off disk
(T18 to T21; on POSIX the names stay distinct: T22). That is a deny-side text rule, not a statement about files:
in the extended namespace a name that ends in a dot or a space can be another file, and it is refused too (L14).

Amendment 2 (review round 3, T23 to T28): a floor file root is compared by the file its own final component names,
as a candidate is (T23, T24, T28), a workspace root that does not resolve stays in the read policy's roots as it was
composed (T25), a listing shows a match only in a spelling that names it in the ordinary namespace (T26; BF-948's
T15 through the verified reader), and what T16 shows about counts of parts is pinned where the count is used (T27).
"""
````

SEARCH:
````
from tests.test_bf948_list_files_read_policy import _OUTSIDE, _PROTECTED, _link, _list, _runtime, _scene, _unlink
````
REPLACE:
````
from tests.test_bf948_list_files_read_policy import SECRET_NAME, _OUTSIDE, _PROTECTED, _link, _list, _runtime, _scene, _unlink
````

SEARCH:
````
from probos.security import file_access
````
REPLACE:
````
from probos.config import SystemConfig
from probos.security import file_access
````

SEARCH:
````
    """T5: pure text, the same on every platform: the extended and device prefixes of a drive path and the extended
    UNC prefix go; a volume or device name, a drive-relative form and a path of another platform stay."""
````
REPLACE:
````
    """T5: pure text, the same on every platform: the extended and device prefixes of a drive path and the extended
    UNC prefix go, and a bare drive after a prefix is the drive; a volume or device name, a drive-relative form with a
    path and a path of another platform stay."""
````

SEARCH:
````
    """T16: the position a root stands at in the path's own chain is its count of parts, and dropping a namespace prefix
    changes no count: the exemption's rank does not depend on how its root is spelled."""
````
REPLACE:
````
    """T16: dropping a namespace prefix changes no count of parts, so a root that is matched as text stands at the same
    count however its prefix is spelled. This is a property of the text alone: it shows that the root's own count and its
    namespace-free count are the same number, and it kills no mutant of the match (T27 pins the use of the count)."""
````

SEARCH:
````
    admitted, and keeps the suffix it was given."""
````
REPLACE:
````
    admitted, and the path returned is the one ``Path.resolve()`` spells for it (a named stream's suffix is kept there, T20;
    a trailing dot or space and the default stream's type are dropped by ``resolve()`` for a file on disk)."""
````

SEARCH:
````
    assert admitted[0] == "admitted", f"a neighbour with {suffix!r}: {admitted}"
````
REPLACE:
````
    assert admitted[0] == "admitted", f"a neighbour with {suffix!r}: {admitted}"
    assert admitted == ("admitted", str(Path(str(lay.neighbour) + suffix).resolve())), f"the path returned for {suffix!r}"
````

SEARCH:
````
    assert neighbour_stream.error is None and "stream fixture" in repr(neighbour_stream.output)
````
REPLACE:
````
    assert neighbour_stream.error is None and "stream fixture" in repr(neighbour_stream.output)
    assert str(file_access.resolve_for_runtime(str(lay.neighbour) + ":zz", runtime)).endswith(":zz"), "the stream name is kept"
````

SEARCH:
````
        assert _decide(str(root / "vault" / name))[0] == "admitted", name
````
REPLACE:
````
        assert _decide(str(root / "vault" / name))[0] == "admitted", name


_ROOT_SUFFIXES = [":settings", ":settings:$DATA", ".", " "]


@WINDOWS
@pytest.mark.parametrize("suffix", _ROOT_SUFFIXES)
def test_a_floor_file_root_spelled_with_a_suffix_is_decided_as_its_file_is(tmp_path: Path, suffix: str) -> None:
    """T23 (review round 3, A1): a floor file root whose own final component carries a stream suffix (a configuration loaded
    as ``loaded.yaml:settings``) or, spelled in the extended namespace, a trailing dot or space, is compared by the file it
    names, as a candidate is. The root's own spelling and every other spelling of its file (the ordinary one, the default
    stream, another stream, the extended prefix) are refused with the floor's reason, and a neighbour with the same suffix is
    admitted."""
    lay = _fixture(tmp_path)
    spelled = "\\\\?\\" + str(lay.config) + suffix if suffix in (".", " ") else str(lay.config) + suffix
    floor = [lay.data.resolve(), Path(spelled)]
    for candidate in (
        spelled, str(lay.config), "\\\\?\\" + str(lay.config), str(lay.config) + "::$DATA", str(lay.config) + ":other",
        "\\\\?\\" + str(lay.config) + ".",
    ):
        assert _decide(candidate, protected=floor) == ("refused", _FLOOR_REASON), f"{candidate!r}"
    assert _decide(str(lay.neighbour) + suffix, protected=floor)[0] == "admitted", "a neighbour with the same suffix"


_FLOOR_ROOT_CASES = [
    ("C:\\cfg\\loaded.yaml:settings", "C:\\cfg\\loaded.yaml"),
    ("C:\\cfg\\loaded.yaml:settings:$DATA", "C:\\cfg\\loaded.yaml"),
    ("\\\\?\\C:\\cfg\\old.yaml.", "\\\\?\\C:\\cfg\\old.yaml"),
    ("\\\\?\\C:\\cfg\\old.yaml. ", "\\\\?\\C:\\cfg\\old.yaml"),
]


@pytest.mark.parametrize(("text", "base"), _FLOOR_ROOT_CASES)
def test_the_floor_roots_include_the_file_each_final_component_names(text: str, base: str) -> None:
    """T24 (review round 3, A1): each floor root stays in the list as it is spelled and, on Windows, the file its final
    component names follows it when that is another spelling; a root that names itself (a directory root, an ordinary file
    root) adds nothing, and on another platform nothing is added."""
    directory, ordinary = Path("C:\\data"), Path("C:\\cfg\\loaded.yaml")
    assert file_access._floor_roots([directory, ordinary]) == [directory, ordinary]
    roots = [directory, Path(text), ordinary]
    assert file_access._floor_roots(roots) == ([*roots, Path(base)] if os.name == "nt" else roots)


async def test_a_workspace_root_that_does_not_resolve_stays_in_the_read_policy_as_it_was_composed(tmp_path: Path) -> None:
    """T25 (review round 3, A2): a workspace root the configuration accepts and the system cannot resolve (a text with a NUL)
    stays in both root builders as it was composed, so a configured read policy still confines reads, whether its own roots are
    usable or not; the exempt list lifts nothing for it. Through ``resolve_for_runtime``, ``read_file`` and ``list_files``."""
    scene = _scene(tmp_path)
    broken = str(scene.workspace) + "\x00"

    def runtime(read_roots: list[str], workspace: str) -> SimpleNamespace:
        config = SystemConfig(security_infra={"read_roots": read_roots}, execution={"workspace_root": workspace})
        return SimpleNamespace(data_dir=scene.data, config=config)

    with pytest.raises(ValueError):
        Path(broken).resolve()  # premise: the system refuses to resolve it
    assert file_access.permitted_read_roots(runtime(["\x00unusable"], str(scene.workspace))) == [scene.workspace.resolve()]
    assert file_access.permitted_read_roots(runtime(["\x00unusable"], broken)) == [Path(broken)]
    assert file_access.permitted_read_roots(runtime([str(scene.allowed)], broken)) == [scene.allowed.resolve(), Path(broken)]
    assert file_access.workspace_exempt_roots(runtime([], broken)) == [Path(broken)]
    outside = str(scene.outside / SECRET_NAME)
    for read_roots in (["\x00unusable"], [str(scene.allowed)]):
        policy = runtime(read_roots, broken)
        with pytest.raises(FileAccessDenied) as refused:
            file_access.resolve_for_runtime(outside, policy)
        assert refused.value.reason == _OUTSIDE_REASON, read_roots
        read = await ReadFileTool(policy).invoke({"path": outside})
        assert read.error == _READ_OUTSIDE and read.output is None, read_roots
        listing = await ListFilesTool(policy).invoke({"pattern": "*", "path": str(scene.outside)})
        assert listing.error == _OUTSIDE and listing.output is None, read_roots
    inside = scene.allowed / "ok.txt"
    assert file_access.resolve_for_runtime(str(inside), runtime([str(scene.allowed)], broken)) == inside.resolve()
    with pytest.raises(FileAccessDenied):
        file_access.resolve_for_runtime(str(scene.workspace / "scratch.txt"), runtime([], broken))


_READER_CASES = [
    ("C:\\data\\note.txt", "C:\\data\\note.txt"),
    ("\\\\?\\C:\\data\\note.txt", "C:\\data\\note.txt"),
    ("\\\\?\\UNC\\host\\share\\dir\\f.txt", "\\\\host\\share\\dir\\f.txt"),
    ("\\\\host\\share\\dir\\f.txt", "\\\\host\\share\\dir\\f.txt"),
    ("\\\\?\\C:\\data\\a b.txt", "C:\\data\\a b.txt"),
    ("\\\\?\\C:\\data\\x..y.txt", "C:\\data\\x..y.txt"),
    ("\\\\?\\C:\\data\\console.txt", "C:\\data\\console.txt"),
    ("\\\\?\\C:\\data\\confidential\\nul0.txt", "C:\\data\\confidential\\nul0.txt"),
    ("\\\\?\\C:\\data\\note.txt.", None),
    ("\\\\?\\C:\\data\\note.txt ", None),
    ("C:\\data\\note.txt. ", None),
    ("\\\\?\\C:\\data\\dir.\\deep.txt", None),
    ("\\\\?\\C:\\data\\dir \\deep.txt", None),
    ("\\\\?\\C:\\data\\up.\\down\\leaf.txt", None),
    ("\\\\?\\C:\\data\\...", None),
    ("\\\\?\\UNC\\host\\share\\dir.\\f.txt", None),
    ("\\\\?\\C:\\data\\NUL.txt", None),
    ("C:\\data\\con", None),
    ("C:\\data\\Aux.log", None),
    ("C:\\data\\COM1", None),
    ("C:\\data\\lpt9.txt", None),
    ("\\\\?\\C:\\data\\con\\g.txt", None),
    ("\\\\?\\C:\\data\\nul\\x\\y.txt", None),
]


@pytest.mark.parametrize(("text", "expected"), _READER_CASES)
def test_the_reader_spelling_is_one_that_names_the_file_in_the_ordinary_namespace(text: str, expected: str | None) -> None:
    """T26 (review round 3, A3 and B1): on Windows a path is given to a reader that rejects the namespace prefix as
    ``plain_spelling`` spells it, unless a component of that spelling names another file or none in the ordinary namespace: a
    component that ends in a dot or a space (the system drops both), or a reserved device name, in the final component or in an
    ancestor, has no such spelling and gives ``None``. A name that only starts or ends like a device name keeps its spelling.
    Every other path, and every path on another platform, is returned as ``plain_spelling`` returns it."""
    got = file_access.reader_spelling(Path(text))
    if os.name == "nt":
        assert (None if got is None else str(got)) == expected
    else:
        assert got == Path(text)


_STAND_CASES = [
    ("\\\\?\\C:\\data\\work", "C:\\data\\work\\note.txt", 3),
    ("\\\\.\\C:\\data", "C:\\data\\work\\note.txt", 2),
    ("\\\\?\\UNC\\host\\share\\data", "\\\\host\\share\\data\\note.txt", 2),
    ("C:\\data\\work", "\\\\?\\C:\\data\\work\\note.txt", 3),
]


@WINDOWS
@pytest.mark.parametrize(("root", "candidate", "count"), _STAND_CASES)
def test_a_text_match_stands_at_the_count_of_its_namespace_free_root(root: str, candidate: str, count: int) -> None:
    """T27 (review round 3, T16 strengthened): a root that contains a path as text stands at its count of parts without a
    namespace prefix, whichever of the two is spelled with one, and the deepest root wins whatever the order of the list."""
    assert file_access._match_position(Path(candidate), [Path(root)]) == count
    assert file_access._match_position(Path(candidate), [Path("C:\\"), Path(root)]) == count
    assert file_access._match_position(Path(candidate), [Path(root), Path("C:\\")]) == count


@WINDOWS
def test_an_identity_match_stands_where_the_path_names_it_not_where_its_root_is_spelled(monkeypatch: pytest.MonkeyPatch) -> None:
    """T27 (review round 3, T16 strengthened): a floor root that is the same file as a part of the path's own chain stands at
    that part's count of parts, never at the count of the root as it is spelled; an exempt or a permitted root is not matched
    by identity."""
    spelled = Path("\\\\?\\GLOBALROOT\\Device\\HarddiskVolume3\\floor\\a\\b\\c\\d\\e")
    alias = Path("\\\\bf953-alias\\share\\floor")
    candidate = alias / "sub" / "note.txt"
    known = {spelled: (1, 1), alias: (1, 1)}
    monkeypatch.setattr(file_access, "_file_identity", lambda path: known.get(path, (2, hash(path))))
    assert len(spelled.parts) > len(alias.parts), "premise: the root is spelled with more parts than the part it names"
    assert file_access._match_position(candidate, [spelled], floor=True) == len(alias.parts)
    assert file_access._match_position(candidate, [spelled]) is None


@WINDOWS
async def test_a_configuration_loaded_as_a_stream_is_refused_for_every_spelling_of_its_file(tmp_path: Path) -> None:
    """T28 (review round 3, A1): the configuration the vessel loaded is the stream ``loaded.yaml:settings`` of a file. The
    floor lists it as spelled, and ``resolve_for_runtime`` and ``read_file`` refuse that spelling and the ordinary spelling of
    the file with the floor's reason and give no content; a neighbour's stream is read."""
    lay = _fixture(tmp_path)
    spelled = str(lay.config) + ":settings"
    try:
        Path(spelled).write_bytes(b"stream fixture")
        Path(str(lay.neighbour) + ":settings").write_bytes(b"stream fixture")
    except OSError:
        pytest.skip("BF-953 premise: this volume makes no named streams")
    runtime = SimpleNamespace(config_path=spelled, data_dir=lay.data, config=SimpleNamespace(
        security_infra=SimpleNamespace(read_roots=[]), execution=SimpleNamespace(workspace_root=str(lay.work)),
    ))
    assert any(str(root).endswith(":settings") for root in file_access.protected_config_files(runtime)), "premise: as loaded"
    reader = ReadFileTool(runtime)
    for raw in (spelled, str(lay.config)):
        with pytest.raises(FileAccessDenied) as refused:
            file_access.resolve_for_runtime(raw, runtime)
        assert refused.value.reason == _FLOOR_REASON, raw
        read = await reader.invoke({"path": raw})
        assert read.error == _READ_PROTECTED and read.output is None, raw
    neighbour = await reader.invoke({"path": str(lay.neighbour) + ":settings"})
    assert neighbour.error is None and "stream fixture" in repr(neighbour.output)
````

### 7.6 M6 (Amendment 3)

All blocks are against `a0857b08`. **Apply B8-2 first (red, G7), then B8-1.** Where prose differs from a block, the block wins. `plain_spelling` stays public; `reader_spelling` calls `validate_read_location` as it is. BF-948's M7 (P8-1: a docstring and two comments in `tools.py`) is built after M6 and its block stands in BF-948's contract, section 7.7.

**B8-1** `src/probos/security/file_access.py` (`plain_spelling`'s docstring, `reader_spelling`)

SEARCH:
````
    :func:`reader_spelling` says whether any ordinary spelling names the file.
````
REPLACE:
````
    :func:`reader_spelling` says whether a listing may name the file.
````

SEARCH:
````
def reader_spelling(path: Path) -> Path | None:
    """BF-953 (Amendment 2): the spelling of *path* that a reader which rejects a Windows namespace prefix opens as the file
    *path* names, or ``None`` when no ordinary spelling names it.

    On Windows it is :func:`plain_spelling` of *path* when every component of that spelling after its anchor names, as an
    ordinary path, what it names in the extended namespace: none ends in a dot or a space (the system drops both from an
    ordinary path, so such a name opens a neighbour or nothing), and no part of the spelling is a reserved device name (the
    system opens the device, and the verified reader rejects the spelling). A path that never had a prefix is held to the
    same test. Any other path, and every path on another platform, is returned as :func:`plain_spelling` returns it.
    Pure: it reads nothing."""
    shown = plain_spelling(path)
    if os.name != "nt":
        return shown
    ordinary = PureWindowsPath(str(shown))
````
REPLACE:
````
def reader_spelling(path: Path) -> Path | None:
    """BF-953 (Amendments 2 and 3): the spelling of *path* a listing may name, or ``None``.

    It is :func:`plain_spelling` of *path* when the verified reader's rules on the text of a path admit that spelling and,
    on Windows, every component of it after its anchor names, as an ordinary path, what it names in the extended namespace.

    The verified reader applies two rules to the text alone, and they are applied here on every platform. Its location gate,
    :func:`validate_read_location`, is called as it is: text that is not strict UTF-8, a ``:`` after the drive or a character
    below 32 anywhere, a reserved device name as the final component, a namespace prefix that :func:`plain_spelling` does
    not remove and a location that is not absolute have no spelling. Its child-name rule for the final component (a pinned
    directory's ``_leaf``) is applied to the final name: a backslash, a trailing dot or a trailing space have none. So a name
    only the plain reader opens (on POSIX a colon, a control character or a reserved device stem such as ``aux.py``) has no
    spelling either. On Windows a component after the anchor that ends in a dot or a space has none (the system drops both
    from an ordinary path, so such a name opens a neighbour or nothing), nor has a spelling with a reserved device name in
    any part (the system opens the device).

    Pure: it calls no filesystem function; it builds path objects and strings for each call (BF-953 L20). It does not say
    that the file opens: a directory, a link or reparse point, a path past the host's ordinary length on a host without
    long-path support and a file changed after the listing are decided when it is read (BF-953 L18)."""
    shown = plain_spelling(path)
    try:
        validate_read_location(str(shown))
    except ValueError:  # the reader's own refusal of the text, whatever its class (UnicodeEncodeError is one): no spelling
        return None
    final = shown.name
    if "\\" in final or final != final.rstrip(" ."):
        return None
    if os.name != "nt":
        return shown
    ordinary = PureWindowsPath(str(shown))
````

**B8-2** `tests/test_bf953_read_floor_spellings.py` (the module docstring, the import, T26, T29 to T33)

SEARCH:
````
composed (T25), a listing shows a match only in a spelling that names it in the ordinary namespace (T26; BF-948's
T15 through the verified reader), and what T16 shows about counts of parts is pinned where the count is used (T27).
"""
````
REPLACE:
````
composed (T25), a listing shows a match only in a spelling that names it in the ordinary namespace (T26; BF-948's
T15 through the verified reader), and what T16 shows about counts of parts is pinned where the count is used (T27).

Amendment 3 (review round 4, T29 to T33): a listing shows a match only in a spelling the verified reader's rules on the
text admit, on every platform (T29, T30: the reader's location gate and its final-name rule; T31: the pinned directory's
own verdict), the function calls no filesystem function (T32), and a directory that holds names the reader's gate refuses
is listed without them, from an ordinary and an extended-prefix base, with every name it lists opened by the verified
reader (T33, Windows). None of these says that a listed name opens: BF-953 L18 lists what a listing cannot promise.
"""
````

SEARCH:
````
from pathlib import Path, PureWindowsPath
````
REPLACE:
````
from pathlib import Path, PurePosixPath, PureWindowsPath
````

SEARCH:
````
@pytest.mark.parametrize(("text", "expected"), _READER_CASES)
def test_the_reader_spelling_is_one_that_names_the_file_in_the_ordinary_namespace(text: str, expected: str | None) -> None:
    """T26 (review round 3, A3 and B1): on Windows a path is given to a reader that rejects the namespace prefix as
    ``plain_spelling`` spells it, unless a component of that spelling names another file or none in the ordinary namespace: a
    component that ends in a dot or a space (the system drops both), or a reserved device name, in the final component or in an
    ancestor, has no such spelling and gives ``None``. A name that only starts or ends like a device name keeps its spelling.
    Every other path, and every path on another platform, is returned as ``plain_spelling`` returns it."""
    got = file_access.reader_spelling(Path(text))
    if os.name == "nt":
        assert (None if got is None else str(got)) == expected
    else:
        assert got == Path(text)
````
REPLACE:
````
@WINDOWS
@pytest.mark.parametrize(("text", "expected"), _READER_CASES)
def test_the_reader_spelling_is_one_that_names_the_file_in_the_ordinary_namespace(text: str, expected: str | None) -> None:
    """T26 (review round 3, A3 and B1; Windows only since review round 4): a path is given to a reader that rejects the
    namespace prefix as ``plain_spelling`` spells it, unless a component of that spelling names another file or none in the
    ordinary namespace: a component that ends in a dot or a space (the system drops both), or a reserved device name, in the
    final component or in an ancestor, has no such spelling and gives ``None``. A name that only starts or ends like a device
    name keeps its spelling. The rules of the verified reader on the text, which apply on every platform, are T29 to T31."""
    got = file_access.reader_spelling(Path(text))
    assert (None if got is None else str(got)) == expected
````

SEARCH:
````
    neighbour = await reader.invoke({"path": str(lay.neighbour) + ":settings"})
    assert neighbour.error is None and "stream fixture" in repr(neighbour.output)
````
REPLACE:
````
    neighbour = await reader.invoke({"path": str(lay.neighbour) + ":settings"})
    assert neighbour.error is None and "stream fixture" in repr(neighbour.output)


# --- M6 (Amendment 3, review round 4): a listing names only a spelling the verified reader's rules on the text admit ---


def _listed(*parts: str) -> Path:
    """An absolute path of this platform, ``C:\\data`` or ``/data`` joined with *parts*, built as text: nothing is created."""
    return Path("C:\\data" if os.name == "nt" else "/data").joinpath(*parts)


# (label, parts, given on Windows, given on another platform). A row whose two answers differ is a rule only Windows has:
# the system drops a trailing dot or space from an ordinary path and opens a device for a reserved name, in an ancestor.
_TEXT_CASES = [
    ("an ordinary name", ("note.txt",), True, True),
    ("a space inside a name", ("a b.txt",), True, True),
    ("a non-ASCII name", ("caf\u00e9.txt",), True, True),
    ("an astral name", ("music-\U0001d11e.txt",), True, True),
    ("a name that only starts like a device name", ("console.txt",), True, True),
    ("a lone high surrogate", ("\ud800.txt",), False, False),
    ("a lone low surrogate inside a name", ("a\udcffb",), False, False),
    ("a lone surrogate in an ancestor", ("d\ud800", "note.txt"), False, False),
    ("a colon in the final name", ("run-12:30.txt",), False, False),
    ("a colon in an ancestor", ("12:30", "note.txt"), False, False),
    ("a newline in the final name", ("a\nb.txt",), False, False),
    ("a character below 32 in an ancestor", ("d\x01", "note.txt"), False, False),
    ("a reserved device stem as the final name", ("aux.py",), False, False),
    ("a reserved device name in another case", ("Con",), False, False),
    ("a trailing dot in the final name", ("note.txt.",), False, False),
    ("a trailing space in the final name", ("note.txt ",), False, False),
    ("a reserved device name as a directory", ("con", "g.txt"), False, True),
    ("a trailing dot on an ancestor", ("dir.", "deep.txt"), False, True),
    ("a trailing space on an ancestor", ("dir ", "deep.txt"), False, True),
]


@pytest.mark.parametrize(("label", "parts", "on_windows", "elsewhere"), _TEXT_CASES, ids=[row[0] for row in _TEXT_CASES])
def test_the_reader_spelling_follows_the_verified_readers_rules_on_the_text(
    label: str, parts: tuple[str, ...], on_windows: bool, elsewhere: bool,
) -> None:
    """T29 (review round 4, F1; any platform): ``reader_spelling`` gives a spelling only where the verified reader's rules on
    the text admit it. Text that is not strict UTF-8 (a lone surrogate in the final name or an ancestor), a colon or a
    character below 32 anywhere, a reserved device name as the final name, and a trailing dot or space in the final name give
    none, on every platform; an ordinary, a non-ASCII and an astral name give the path itself. A reserved device name or a
    trailing dot or space in an ancestor gives none on Windows only. Whatever the reader's own location gate refuses gives
    none."""
    path = _listed(*parts)
    got = file_access.reader_spelling(path)
    assert (got is not None) == (on_windows if os.name == "nt" else elsewhere), f"{label}: {got}"
    if got is not None:
        assert got == path
    try:
        file_access.validate_read_location(str(path))
    except ValueError:
        assert got is None, f"{label}: the reader's location gate refuses it, so there is no spelling"


# (label, text, given). Windows-shaped texts are not used: with ``os.name`` set to ``posix`` a host takes the branch a POSIX host takes.
_POSIX_CASES = [
    ("an ordinary name", "/data/note.txt", True),
    ("a reserved device name as a directory", "/data/con/g.txt", True),
    ("a trailing dot on an ancestor", "/data/dir./deep.txt", True),
    ("a trailing space on an ancestor", "/data/dir /deep.txt", True),
    ("a colon in the final name", "/data/a:b.txt", False),
    ("a timestamp in the final name", "/data/run-2026-11-04T16:20:00Z.log", False),
    ("a newline in the final name", "/data/a\nb.txt", False),
    ("a reserved device stem as the final name", "/data/aux.py", False),
    ("a backslash in the final name", "/data/a\\b.txt", False),
    ("a trailing dot in the final name", "/data/note.", False),
    ("a trailing space in the final name", "/data/note ", False),
    ("a name decoded with surrogateescape", "/data/\udcff.txt", False),
    ("a relative spelling", "data/note.txt", False),
]


@pytest.mark.parametrize(("label", "text", "given"), _POSIX_CASES, ids=[row[0] for row in _POSIX_CASES])
def test_the_reader_spelling_applies_the_readers_rules_off_windows_too(
    monkeypatch: pytest.MonkeyPatch, label: str, text: str, given: bool,
) -> None:
    """T30 (review round 4, F1; any platform): with ``os.name`` set to ``posix`` for the one call (a no-op on a POSIX host),
    the function takes the branch a POSIX host takes, and the reader's rules on the text still apply in it: a colon, a
    newline, a reserved device stem, a backslash, a trailing dot or space in the final name, a name decoded with
    ``surrogateescape`` and a relative spelling give none, and a reserved device name or a trailing dot or space in an
    ancestor, which only Windows refuses, gives the path itself."""
    path = PurePosixPath(text)
    with monkeypatch.context() as patch:
        patch.setattr(os, "name", "posix")
        got = file_access.reader_spelling(path)  # type: ignore[arg-type]
    assert (got is not None) == given, f"{label}: {got}"
    if got is not None:
        assert got == path


@pytest.mark.parametrize("name", [
    "note.txt", "a b.txt", "caf\u00e9", ".hidden", "x..y", "note.", "note ", "note. ", "...",
    pytest.param("a\\b", marks=pytest.mark.skipif(os.name == "nt", reason="BF-953: on Windows a backslash separates components")),
])
def test_the_reader_spelling_agrees_with_the_pinned_directory_on_the_final_name(tmp_path: Path, name: str) -> None:
    """T31 (review round 4, F1; any platform): for one final name, a real pinned directory's ``read_bytes`` and
    ``reader_spelling`` agree. A name the pinned directory refuses as a child name (``invalid child name``) has no
    spelling, and a name it admits (the read goes on to the file that is not there) has one, so the lister's restatement of
    that rule is the reader's."""
    root = tmp_path.resolve()
    with file_access.pin_directory(root) as directory:
        try:
            directory.read_bytes(name)
        except FileAccessDenied as refused:
            assert refused.reason == "invalid child name", name
            admitted = False
        except FileNotFoundError:
            admitted = True
    assert (file_access.reader_spelling(root / name) is not None) == admitted, name


def test_the_reader_spelling_calls_no_filesystem_function(monkeypatch: pytest.MonkeyPatch) -> None:
    """T32 (review round 4, F2; any platform): ``reader_spelling`` calls none of ``os.stat``, ``os.lstat``, ``os.scandir``,
    ``os.listdir``, ``os.getcwd`` and ``open``, for a spelling it gives and for one it refuses, for an extended-prefix
    spelling and for a relative one. It builds path objects and strings, which is work for each match and is not a
    filesystem call (BF-953 L20)."""
    inputs = [_listed(*parts) for _, parts, _, _ in _TEXT_CASES] + [Path("note.txt")]
    if os.name == "nt":
        inputs += [Path("\\\\?\\C:\\data\\note.txt"), Path("\\\\?\\UNC\\host\\share\\dir\\f.txt")]

    def refused(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("reader_spelling called a filesystem function")

    with monkeypatch.context() as patch:
        for function in ("stat", "lstat", "scandir", "listdir", "getcwd"):
            patch.setattr(os, function, refused)
        patch.setattr("builtins.open", refused)
        results = [file_access.reader_spelling(path) for path in inputs]
    assert any(result is not None for result in results), "premise: some spellings were given"
    assert any(result is None for result in results), "premise: some were refused"


_CARRIED = {
    "note.txt": b"ordinary file", "caf\u00e9.txt": b"non-ASCII file", "music-\U0001d11e.txt": b"astral file",
    "ok\\inner.txt": b"file in an ordinary directory",
}
_UNCARRIED = {
    "\ud800.txt": b"lone high surrogate", "a\udcffb.txt": b"lone low surrogate", "\ud800dir\\inner.txt": b"file in a surrogate directory",
}


@WINDOWS
@pytest.mark.parametrize("spelling", ["ordinary base", "extended-prefix base"])
async def test_a_listing_leaves_out_a_name_the_verified_reader_cannot_carry(
    tmp_path: Path, request: pytest.FixtureRequest, spelling: str,
) -> None:
    """T33 (review round 4, F1; Windows): a directory holds names that the plain reader opens and the verified reader's
    location gate refuses (an unpaired surrogate in a file's name, in another file's name and in a directory's name) beside an
    ordinary, a non-ASCII and an astral name and a file in an ordinary directory. ``list_files`` of its ordinary and of its
    extended-prefix spelling leaves the first kind out and lists the second, and every file it lists is opened by the verified
    reader with the bytes of the file it matched. The plain reader reads the first kind: that is the cost of listing by the
    verified reader's rules, and it is recorded (BF-953 L19)."""
    root = tmp_path.resolve() / "d"
    root.mkdir()
    prefixed = "\\\\?\\" + str(root)
    request.addfinalizer(lambda: shutil.rmtree(prefixed, ignore_errors=True))
    for name, data in {**_CARRIED, **_UNCARRIED}.items():
        target = prefixed + "\\" + name
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "wb") as handle:
            handle.write(data)
    runtime = _runtime(_scene(tmp_path), read_roots=[])
    reader = ReadFileTool(runtime)
    roots: dict[str, Any] = {
        "protected_roots": file_access.protected_read_roots(runtime), "exempt_roots": file_access.workspace_exempt_roots(runtime),
        "permitted_roots": file_access.permitted_read_roots(runtime) or None,
    }
    for name, data in _UNCARRIED.items():  # premise: the verified reader's gate refuses each, and the plain reader reads each
        with pytest.raises(ValueError):
            file_access.read_verified_file(Path(str(root) + "\\" + name), **roots)
        with open(prefixed + "\\" + name, "rb") as handle:
            assert handle.read() == data, name
    plain = await reader.invoke({"path": str(root) + "\\" + "\ud800.txt"})
    assert plain.error is None and "lone high surrogate" in repr(plain.output), "premise: the unarmed read_file opens it"
    listed = await ListFilesTool(runtime).invoke(
        {"pattern": "**/*", "path": prefixed if spelling == "extended-prefix base" else str(root)},
    )
    assert listed.error is None and set(listed.output) == {"files"}, f"{spelling}: {listed.error}"
    expected = sorted(str(root / name) for name in (*_CARRIED, "ok"))
    assert sorted(listed.output["files"]) == expected, f"{spelling}: the names the verified reader's gate admits"
    for name in expected:
        if Path(name).is_dir():
            continue
        snapshot = file_access.read_verified_file(reader.resolve_source_path(name), **roots)
        with open(prefixed + "\\" + str(Path(name).relative_to(root)), "rb") as source:
            assert snapshot.data == source.read(), f"{spelling}: the verified reader opened {name!r}"
````

### 7.7 M7 (Amendment 4)

All blocks are against `8c83093b`. **Apply B10-2 first (red, G8), then B10-1.** Where prose differs from a block, the block wins. B10-1 and B10-2 replace the text of B8-1 and B8-2 where it differs (they apply to the head, which holds M6): §7.6 stays as the record of what M6 built, and its blocks are not applied again. `plain_spelling` stays public; `reader_spelling` calls `validate_read_location` as it is, on the file and on its direct parent. BF-948's M8 (P9-1: the `ListFilesTool` docstring) is built after M7 and its block stands in BF-948's contract, section 7.8.

**B10-1** `src/probos/security/file_access.py` (`reader_spelling`: the direct parent's gate, and its docstring)

SEARCH:
````
    """
    return Path(_namespace_free(str(path))) if os.name == "nt" else path


def reader_spelling(path: Path) -> Path | None:
    """BF-953 (Amendments 2 and 3): the spelling of *path* a listing may name, or ``None``.

    It is :func:`plain_spelling` of *path* when the verified reader's rules on the text of a path admit that spelling and,
    on Windows, every component of it after its anchor names, as an ordinary path, what it names in the extended namespace.

    The verified reader applies two rules to the text alone, and they are applied here on every platform. Its location gate,
    :func:`validate_read_location`, is called as it is: text that is not strict UTF-8, a ``:`` after the drive or a character
    below 32 anywhere, a reserved device name as the final component, a namespace prefix that :func:`plain_spelling` does
    not remove and a location that is not absolute have no spelling. Its child-name rule for the final component (a pinned
    directory's ``_leaf``) is applied to the final name: a backslash, a trailing dot or a trailing space have none. So a name
    only the plain reader opens (on POSIX a colon, a control character or a reserved device stem such as ``aux.py``) has no
    spelling either. On Windows a component after the anchor that ends in a dot or a space has none (the system drops both
    from an ordinary path, so such a name opens a neighbour or nothing), nor has a spelling with a reserved device name in
    any part (the system opens the device).

    Pure: it calls no filesystem function; it builds path objects and strings for each call (BF-953 L20). It does not say
    that the file opens: a directory, a link or reparse point, a path past the host's ordinary length on a host without
    long-path support and a file changed after the listing are decided when it is read (BF-953 L18)."""
````
REPLACE:
````
    """
    return Path(_namespace_free(str(path))) if os.name == "nt" else path


def reader_spelling(path: Path) -> Path | None:
    """BF-953 (Amendments 2 to 4): the spelling of *path* a listing may name, or ``None``.

    It is :func:`plain_spelling` of *path* when the verified reader's rules on the text of a path admit that spelling and,
    on Windows, every component of it after its anchor names, as an ordinary path, what it names in the extended namespace.

    The verified reader applies three rules to the text alone, and they are applied here on every platform. Its location
    gate, :func:`validate_read_location`, is called as it is, on the file and on the file's direct parent (``read_verified_file``
    gives the file to the gate, and the directory it pins gives its path to the gate): text that is not strict UTF-8, a ``:``
    after the drive or a character below 32 anywhere, a reserved device name as the final component of either, a namespace
    prefix that :func:`plain_spelling` does not remove and a location that is not absolute have no spelling. Its child-name
    rule for the final component (a pinned directory's ``_leaf``) is applied to the final name: a backslash, a trailing dot
    or a trailing space have none. So a name only the plain reader opens (on POSIX a colon, a control character, or a
    reserved device stem such as ``aux.py`` as the final name or as the direct parent's name) has no spelling either. The
    reader opens the directories above the direct parent without the gate: a reserved device name, or a trailing dot or
    space, there does not refuse a name off Windows (BF-953 L21). On Windows a component after the anchor that ends in a dot
    or a space has none (the system drops both from an ordinary path, so such a name opens a neighbour or nothing), nor has
    a spelling with a reserved device name in any part, which is wider than the reader's text path (BF-953 L21).

    Pure: it calls no filesystem function; it builds path objects and strings for each call (BF-953 L20). It does not say
    that the file opens: a directory, a link or reparse point, a path past the host's ordinary length on a host without
    long-path support and a file changed after the listing are decided when it is read (BF-953 L18)."""
````

SEARCH:
````
    shown = plain_spelling(path)
    try:
        validate_read_location(str(shown))
    except ValueError:  # the reader's own refusal of the text, whatever its class (UnicodeEncodeError is one): no spelling
        return None
    final = shown.name
````
REPLACE:
````
    shown = plain_spelling(path)
    try:
        validate_read_location(str(shown))
        validate_read_location(str(shown.parent))  # the directory read_verified_file pins is given to the gate as well
    except ValueError:  # the reader's own refusal of the text, whatever its class (UnicodeEncodeError is one): no spelling
        return None
    final = shown.name
````

**B10-2** `tests/test_bf953_read_floor_spellings.py` (the module docstring, the import, T29 and T30 corrected, T34 and T35)

SEARCH:
````
own verdict), the function calls no filesystem function (T32), and a directory that holds names the reader's gate refuses
is listed without them, from an ordinary and an extended-prefix base, with every name it lists opened by the verified
reader (T33, Windows). None of these says that a listed name opens: BF-953 L18 lists what a listing cannot promise.
"""

from __future__ import annotations

import ctypes
import os
import shutil
import tempfile
````
REPLACE:
````
own verdict), the function calls no filesystem function (T32), and a directory that holds names the reader's gate refuses
is listed without them, from an ordinary and an extended-prefix base, with every name it lists opened by the verified
reader (T33, Windows). None of these says that a listed name opens: BF-953 L18 lists what a listing cannot promise.

Amendment 4 (review round 5, T34 and T35): the listing admits exactly what the verified reader's text path admits: its
location gate on the file, its location gate on the file's direct parent (the directory the reader pins), and its
child-name rule on the final name. T34 checks that as a property over a generated corpus against the reader's own gate and
child-name rule (the POSIX shape on every platform, the Windows shape on Windows); T35 crosses the seam with real files and
the real reader and tool (a reserved device name as the direct parent is neither listed nor read; one above it is read, and
listed off Windows). T29 and T30 are corrected: only the direct parent is refused, not every ancestor.
"""

from __future__ import annotations

import ctypes
import itertools
import os
import shutil
import tempfile
````

SEARCH:
````
    """An absolute path of this platform, ``C:\\data`` or ``/data`` joined with *parts*, built as text: nothing is created."""
    return Path("C:\\data" if os.name == "nt" else "/data").joinpath(*parts)


# (label, parts, given on Windows, given on another platform). A row whose two answers differ is a rule only Windows has:
# the system drops a trailing dot or space from an ordinary path and opens a device for a reserved name, in an ancestor.
_TEXT_CASES = [
    ("an ordinary name", ("note.txt",), True, True),
    ("a space inside a name", ("a b.txt",), True, True),
````
REPLACE:
````
    """An absolute path of this platform, ``C:\\data`` or ``/data`` joined with *parts*, built as text: nothing is created."""
    return Path("C:\\data" if os.name == "nt" else "/data").joinpath(*parts)


# (label, parts, given on Windows, given on another platform). A row whose two answers differ is a rule only Windows has:
# its same-file rule withholds a trailing dot or space and a reserved device name in any ancestor, which is wider than the
# reader's text path (BF-953 L21).
_TEXT_CASES = [
    ("an ordinary name", ("note.txt",), True, True),
    ("a space inside a name", ("a b.txt",), True, True),
````

SEARCH:
````
    ("a reserved device name in another case", ("Con",), False, False),
    ("a trailing dot in the final name", ("note.txt.",), False, False),
    ("a trailing space in the final name", ("note.txt ",), False, False),
    ("a reserved device name as a directory", ("con", "g.txt"), False, True),
    ("a trailing dot on an ancestor", ("dir.", "deep.txt"), False, True),
    ("a trailing space on an ancestor", ("dir ", "deep.txt"), False, True),
]
````
REPLACE:
````
    ("a reserved device name in another case", ("Con",), False, False),
    ("a trailing dot in the final name", ("note.txt.",), False, False),
    ("a trailing space in the final name", ("note.txt ",), False, False),
    ("a reserved device name as the direct parent", ("con", "g.txt"), False, False),
    ("a reserved device stem as the direct parent", ("aux.py", "g.txt"), False, False),
    ("a reserved device name above the direct parent", ("con", "sub", "g.txt"), False, True),
    ("a trailing dot on an ancestor", ("dir.", "deep.txt"), False, True),
    ("a trailing space on an ancestor", ("dir ", "deep.txt"), False, True),
]
````

SEARCH:
````
def test_the_reader_spelling_follows_the_verified_readers_rules_on_the_text(
    label: str, parts: tuple[str, ...], on_windows: bool, elsewhere: bool,
) -> None:
    """T29 (review round 4, F1; any platform): ``reader_spelling`` gives a spelling only where the verified reader's rules on
    the text admit it. Text that is not strict UTF-8 (a lone surrogate in the final name or an ancestor), a colon or a
    character below 32 anywhere, a reserved device name as the final name, and a trailing dot or space in the final name give
    none, on every platform; an ordinary, a non-ASCII and an astral name give the path itself. A reserved device name or a
    trailing dot or space in an ancestor gives none on Windows only. Whatever the reader's own location gate refuses gives
    none."""
    path = _listed(*parts)
    got = file_access.reader_spelling(path)
    assert (got is not None) == (on_windows if os.name == "nt" else elsewhere), f"{label}: {got}"
````
REPLACE:
````
def test_the_reader_spelling_follows_the_verified_readers_rules_on_the_text(
    label: str, parts: tuple[str, ...], on_windows: bool, elsewhere: bool,
) -> None:
    """T29 (review round 4, F1; corrected by review round 5; any platform): ``reader_spelling`` gives a spelling only where
    the verified reader's rules on the text admit it. Text that is not strict UTF-8 (a lone surrogate in the final name or an
    ancestor), a colon or a character below 32 anywhere, a reserved device name as the final name or as the direct parent
    (the reader gives both the file and the directory it pins to its location gate), and a trailing dot or space in the final
    name give none, on every platform; an ordinary, a non-ASCII and an astral name give the path itself. A reserved device
    name above the direct parent, or a trailing dot or space in an ancestor, gives none on Windows only: the reader opens
    the directories above the direct parent without the gate (BF-953 L21). Whatever the reader's own location gate refuses
    gives none."""
    path = _listed(*parts)
    got = file_access.reader_spelling(path)
    assert (got is not None) == (on_windows if os.name == "nt" else elsewhere), f"{label}: {got}"
````

SEARCH:
````
# (label, text, given). Windows-shaped texts are not used: with ``os.name`` set to ``posix`` a host takes the branch a POSIX host takes.
_POSIX_CASES = [
    ("an ordinary name", "/data/note.txt", True),
    ("a reserved device name as a directory", "/data/con/g.txt", True),
    ("a trailing dot on an ancestor", "/data/dir./deep.txt", True),
    ("a trailing space on an ancestor", "/data/dir /deep.txt", True),
    ("a colon in the final name", "/data/a:b.txt", False),
````
REPLACE:
````
# (label, text, given). Windows-shaped texts are not used: with ``os.name`` set to ``posix`` a host takes the branch a POSIX host takes.
_POSIX_CASES = [
    ("an ordinary name", "/data/note.txt", True),
    ("a reserved device name as the direct parent", "/data/con/g.txt", False),
    ("a reserved device stem as the direct parent", "/data/aux.py/g.txt", False),
    ("a reserved device name above the direct parent", "/data/con/sub/g.txt", True),
    ("a trailing dot on an ancestor", "/data/dir./deep.txt", True),
    ("a trailing space on an ancestor", "/data/dir /deep.txt", True),
    ("a colon in the final name", "/data/a:b.txt", False),
````

SEARCH:
````
def test_the_reader_spelling_applies_the_readers_rules_off_windows_too(
    monkeypatch: pytest.MonkeyPatch, label: str, text: str, given: bool,
) -> None:
    """T30 (review round 4, F1; any platform): with ``os.name`` set to ``posix`` for the one call (a no-op on a POSIX host),
    the function takes the branch a POSIX host takes, and the reader's rules on the text still apply in it: a colon, a
    newline, a reserved device stem, a backslash, a trailing dot or space in the final name, a name decoded with
    ``surrogateescape`` and a relative spelling give none, and a reserved device name or a trailing dot or space in an
    ancestor, which only Windows refuses, gives the path itself."""
    path = PurePosixPath(text)
    with monkeypatch.context() as patch:
        patch.setattr(os, "name", "posix")
````
REPLACE:
````
def test_the_reader_spelling_applies_the_readers_rules_off_windows_too(
    monkeypatch: pytest.MonkeyPatch, label: str, text: str, given: bool,
) -> None:
    """T30 (review round 4, F1; corrected by review round 5; any platform): with ``os.name`` set to ``posix`` for the one call
    (a no-op on a POSIX host), the function takes the branch a POSIX host takes, and the reader's rules on the text still
    apply in it: a colon, a newline, a reserved device stem as the final name or as the direct parent, a backslash, a
    trailing dot or space in the final name, a name decoded with ``surrogateescape`` and a relative spelling give none, and
    a reserved device name above the direct parent, or a trailing dot or space in an ancestor, which only Windows refuses,
    gives the path itself."""
    path = PurePosixPath(text)
    with monkeypatch.context() as patch:
        patch.setattr(os, "name", "posix")
````

SEARCH:
````
        snapshot = file_access.read_verified_file(reader.resolve_source_path(name), **roots)
        with open(prefixed + "\\" + str(Path(name).relative_to(root)), "rb") as source:
            assert snapshot.data == source.read(), f"{spelling}: the verified reader opened {name!r}"
````
REPLACE:
````
        snapshot = file_access.read_verified_file(reader.resolve_source_path(name), **roots)
        with open(prefixed + "\\" + str(Path(name).relative_to(root)), "rb") as source:
            assert snapshot.data == source.read(), f"{spelling}: the verified reader opened {name!r}"


# --- M7 (Amendment 4, review round 5): the listing admits exactly what the verified reader's text path admits ---


class _TextOnlyDirectory(file_access.PinnedDirectory):
    """A pinned directory with no handle: ``verify`` does nothing, so the real ``_leaf`` runs on a text."""

    def verify(self) -> None:
        return None


class _PosixParent(str):
    """A parent text that joins a child name as a POSIX path does, so the real ``_leaf`` runs its location gate on a ``str``."""

    def __truediv__(self, name: str) -> str:
        return str(PurePosixPath(self) / name)


class _WindowsParent(str):
    """The same for a Windows path."""

    def __truediv__(self, name: str) -> str:
        return str(PureWindowsPath(self) / name)


_TEXT_SHAPES = {"posix": (PurePosixPath, _PosixParent, "/data", "/"), "windows": (PureWindowsPath, _WindowsParent, "C:\\data", "\\")}

# (component, withheld by Windows' same-file rule wherever it stands: a reserved device name, a trailing dot or a trailing space)
_CORPUS_DIRS = [
    ("src", False), ("x..y", False), ("a:b", False),
    ("con", True), ("aux.py", True), ("dot.", True), ("space ", True),
]
_CORPUS_FILES = ["g.txt", "note", "x..y", "dot.", "space ", "a:b", "back\\slash", "aux.py", "con", "\ud800.txt"]


def _corpus(base: str, sep: str) -> list[tuple[str, bool]]:
    """Every file text from zero to three directories below *base*, each directory from ``_CORPUS_DIRS``, each final name
    from ``_CORPUS_FILES``; with whether Windows' same-file rule withholds a directory of it."""
    texts = []
    for depth in range(4):
        for dirs in itertools.product(_CORPUS_DIRS, repeat=depth):
            prefix = base + "".join(sep + name for name, _ in dirs)
            texts += [(f"{prefix}{sep}{name}", any(flag for _, flag in dirs)) for name in _CORPUS_FILES]
    return texts


def _reader_admits(text: str, shape: str, *, parent_gate: bool = True) -> bool:
    """Whether the steps the armed reader takes on a text alone admit *text*, each one the reader's own call, in the order
    ``read_verified_file`` takes them: its location gate on the file; its location gate on the file's direct parent, which
    ``PinnedDirectory.open`` applies to the path ``pin_directory(candidate.parent)`` gives it; then the child-name rule and
    the location gate of ``read_bytes``, run by the real ``PinnedDirectory._leaf`` on a directory with no handle. Nothing in
    the reader reads the text again: the directories above the direct parent are opened by name."""
    pure, parent_type, _, _ = _TEXT_SHAPES[shape]
    parsed = pure(text)
    directory = _TextOnlyDirectory()
    directory._paths = [parent_type(str(parsed.parent))]  # type: ignore[list-item]
    try:
        file_access.validate_read_location(text)
        if parent_gate:
            file_access.validate_read_location(str(parsed.parent))
        directory._leaf(parsed.name)
    except (ValueError, FileAccessDenied):
        return False
    return True


@pytest.mark.parametrize("shape", ["posix", pytest.param("windows", marks=WINDOWS)])
def test_the_listing_admits_exactly_what_the_verified_readers_text_path_admits(
    monkeypatch: pytest.MonkeyPatch, shape: str,
) -> None:
    """T34 (review round 5, A; the POSIX shape on any platform with ``os.name`` set to ``posix`` for the calls, the Windows
    shape on Windows): over a generated corpus of file texts (a reserved device name, a trailing dot or space, a colon and an
    ordinary name as a directory from zero to three deep, and as the final name, with a lone surrogate and a backslash among
    the final names), ``reader_spelling``
    gives a spelling for no text the verified reader's text path refuses, and for every text it admits, except on Windows
    one that the same-file rule withholds (a reserved device name, a trailing dot or a trailing space in a directory). The
    reader's text path is its own functions: ``validate_read_location`` on the file and on the file's direct parent, and the
    real ``PinnedDirectory._leaf``. Premises: the corpus is large, the reader's text path admits and refuses a share of it,
    and the corpus holds texts that only the parent's gate refuses."""
    pure, _, base, sep = _TEXT_SHAPES[shape]
    texts = _corpus(base, sep)
    holes: list[str] = []
    misses: list[str] = []
    admitted_count = only_the_parent_gate_refuses = 0
    with monkeypatch.context() as patch:
        if shape == "posix":
            patch.setattr(os, "name", "posix")
        for text, same_file_withholds in texts:
            admitted = _reader_admits(text, shape)
            admitted_count += admitted
            only_the_parent_gate_refuses += (not admitted) and _reader_admits(text, shape, parent_gate=False)
            listed = file_access.reader_spelling(PurePosixPath(text) if shape == "posix" else Path(text)) is not None
            if listed and not admitted:
                holes.append(text)
            if admitted and not listed and not (shape == "windows" and same_file_withholds):
                misses.append(text)
    assert len(texts) >= 3500, "premise: the corpus is large"
    assert 0.05 * len(texts) < admitted_count < 0.95 * len(texts), "premise: the reader's text path admits and refuses a share"
    assert only_the_parent_gate_refuses >= 100, "premise: the corpus holds texts only the parent's gate refuses"
    assert not holes, f"{len(holes)} listed texts the reader's text path refuses, for example {holes[:3]!r}"
    assert not misses, f"{len(misses)} texts the reader's text path admits and the listing withholds, for example {misses[:3]!r}"


def _make_file(root: Path, rel: tuple[str, ...], data: bytes) -> None:
    base = ("\\\\?\\" + str(root)) if os.name == "nt" else str(root)
    target = base + os.sep + os.sep.join(rel)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "wb") as handle:
        handle.write(data)


async def test_a_listing_and_the_verified_reader_agree_about_a_reserved_direct_parent(
    tmp_path: Path, request: pytest.FixtureRequest,
) -> None:
    """T35 (review round 5, A; any platform, real files): a directory named ``con`` and one named ``aux.py`` (made through the
    extended namespace on Windows) each hold ``g.txt``, as does an ordinary directory and ``con/sub``. The real
    ``read_verified_file`` refuses a file whose direct parent is a reserved device name before it reads the disk
    (``ValueError``), and reads the ordinary one and the one a reserved name above its direct parent. ``list_files`` lists the
    ordinary one and, off Windows, the one above, and each file it lists is read by the verified reader with its own bytes;
    on Windows the same-file rule also withholds the one above (BF-953 L21)."""
    root = tmp_path.resolve() / "d"
    root.mkdir()
    cleanup = ("\\\\?\\" + str(root)) if os.name == "nt" else str(root)
    request.addfinalizer(lambda: shutil.rmtree(cleanup, ignore_errors=True))
    files = {
        ("ok", "g.txt"): b"ordinary", ("con", "g.txt"): b"under con", ("aux.py", "g.txt"): b"under aux.py",
        ("con", "sub", "g.txt"): b"above the direct parent",
    }
    for rel, data in files.items():
        _make_file(root, rel, data)
    runtime = _runtime(_scene(tmp_path), read_roots=[])
    reader = ReadFileTool(runtime)
    roots: dict[str, Any] = {
        "protected_roots": file_access.protected_read_roots(runtime), "exempt_roots": file_access.workspace_exempt_roots(runtime),
        "permitted_roots": file_access.permitted_read_roots(runtime) or None,
    }

    def verified(name: str) -> bytes:
        return file_access.read_verified_file(reader.resolve_source_path(name), **roots).data

    for rel in (("con", "g.txt"), ("aux.py", "g.txt")):  # premise: the reader refuses a reserved direct parent as text
        with pytest.raises(ValueError):
            verified(str(root.joinpath(*rel)))
    assert verified(str(root / "ok" / "g.txt")) == b"ordinary"
    assert verified(str(root / "con" / "sub" / "g.txt")) == b"above the direct parent", "premise: a reserved name above is read"
    listed = await ListFilesTool(runtime).invoke({"pattern": "**/g.txt", "path": str(root)})
    assert listed.error is None and set(listed.output) == {"files"}, listed.error
    expected = [("ok", "g.txt")] if os.name == "nt" else [("ok", "g.txt"), ("con", "sub", "g.txt")]
    assert sorted(listed.output["files"]) == sorted(str(root.joinpath(*rel)) for rel in expected)
    for name in listed.output["files"]:
        assert verified(name) == files[Path(name).relative_to(root).parts], f"the verified reader opened {name!r}"
````

### 7.8 M8 (Amendment 5)

All blocks are against `bd67126a`. **Apply B12-2 first (red, G9), then B12-1.** Where prose differs from a block, the block wins. B12-1 and B12-2 replace the text of B10-1 and B10-2 where it differs (they apply to the head, which holds M7): §7.7 stays as the record of what M7 built, and its blocks are not applied again. `reader_spelling` keeps its signature; the two new statements sit before `final = shown.name`. BF-948's M9 (P10-1: the `ListFilesTool` docstring) is built after M8 and its block stands in BF-948's contract, section 7.9.

**B12-1** `src/probos/security/file_access.py` (`reader_spelling`: two clauses and its docstring)

SEARCH:
````
    """
    return Path(_namespace_free(str(path))) if os.name == "nt" else path


def reader_spelling(path: Path) -> Path | None:
    """BF-953 (Amendments 2 to 4): the spelling of *path* a listing may name, or ``None``.

    It is :func:`plain_spelling` of *path* when the verified reader's rules on the text of a path admit that spelling and,
    on Windows, every component of it after its anchor names, as an ordinary path, what it names in the extended namespace.

    The verified reader applies three rules to the text alone, and they are applied here on every platform. Its location
    gate, :func:`validate_read_location`, is called as it is, on the file and on the file's direct parent (``read_verified_file``
    gives the file to the gate, and the directory it pins gives its path to the gate): text that is not strict UTF-8, a ``:``
    after the drive or a character below 32 anywhere, a reserved device name as the final component of either, a namespace
    prefix that :func:`plain_spelling` does not remove and a location that is not absolute have no spelling. Its child-name
    rule for the final component (a pinned directory's ``_leaf``) is applied to the final name: a backslash, a trailing dot
    or a trailing space have none. So a name only the plain reader opens (on POSIX a colon, a control character, or a
    reserved device stem such as ``aux.py`` as the final name or as the direct parent's name) has no spelling either. The
    reader opens the directories above the direct parent without the gate: a reserved device name, or a trailing dot or
    space, there does not refuse a name off Windows (BF-953 L21). On Windows a component after the anchor that ends in a dot
    or a space has none (the system drops both from an ordinary path, so such a name opens a neighbour or nothing), nor has
    a spelling with a reserved device name in any part, which is wider than the reader's text path (BF-953 L21).

    Pure: it calls no filesystem function; it builds path objects and strings for each call (BF-953 L20). It does not say
    that the file opens: a directory, a link or reparse point, a path past the host's ordinary length on a host without
    long-path support and a file changed after the listing are decided when it is read (BF-953 L18)."""
    shown = plain_spelling(path)
    try:
        validate_read_location(str(shown))
        validate_read_location(str(shown.parent))  # the directory read_verified_file pins is given to the gate as well
    except ValueError:  # the reader's own refusal of the text, whatever its class (UnicodeEncodeError is one): no spelling
        return None
    final = shown.name
    if "\\" in final or final != final.rstrip(" ."):
````
REPLACE:
````
    """
    return Path(_namespace_free(str(path))) if os.name == "nt" else path


def reader_spelling(path: Path) -> Path | None:
    """BF-953 (Amendments 2 to 5): the spelling of *path* a listing may name, or ``None``.

    The input is a path as ``glob`` yields it: absolute, with no ``..`` part. The result is :func:`plain_spelling` of *path*
    where the verified reader's own functions admit its text, and ``None`` otherwise: :func:`validate_read_location`, called
    as it is on the file and on the file's direct parent (the two texts ``read_verified_file`` gives it), and the final-name
    rule of ``PinnedDirectory._leaf``, restated below (BF-953 D15; T31 and T36 compare it with a real pinned directory). A path
    with no final name or with a ``..`` part has no spelling: the reader decides on the candidate ``validate_read_location``
    returns, and that resolves ``..``. What the armed reader answers for a refused text is recorded in BF-953 L22; the reader
    gives its location gate no directory above the direct parent (BF-953 L21). On Windows the rule of BF-953 D14 also gives
    ``None``: it is wider than the reader's text path (BF-953 L21).

    Pure: it calls no filesystem function (BF-953 T32). It does not say that the file opens (BF-953 L18). Its cost is
    recorded in BF-953 L20."""
    shown = plain_spelling(path)
    try:
        validate_read_location(str(shown))
        validate_read_location(str(shown.parent))  # the directory read_verified_file pins is given to the gate as well
    except ValueError:  # the reader's own refusal of the text, whatever its class (UnicodeEncodeError is one): no spelling
        return None
    if not shown.name:  # a root has no child name: PinnedDirectory._leaf refuses an empty one
        return None
    if ".." in shown.parts:  # the reader decides on the candidate validate_read_location returns, and that resolves '..'
        return None
    final = shown.name
    if "\\" in final or final != final.rstrip(" ."):
````

**B12-2** `tests/test_bf953_read_floor_spellings.py` (the module docstring, two imports, T29 and T30 rows and docstrings, T34 rewritten, T35's docstring, T36 to T38)

SEARCH:
````
own verdict), the function calls no filesystem function (T32), and a directory that holds names the reader's gate refuses
is listed without them, from an ordinary and an extended-prefix base, with every name it lists opened by the verified
reader (T33, Windows). None of these says that a listed name opens: BF-953 L18 lists what a listing cannot promise.

Amendment 4 (review round 5, T34 and T35): the listing admits exactly what the verified reader's text path admits: its
location gate on the file, its location gate on the file's direct parent (the directory the reader pins), and its
child-name rule on the final name. T34 checks that as a property over a generated corpus against the reader's own gate and
child-name rule (the POSIX shape on every platform, the Windows shape on Windows); T35 crosses the seam with real files and
the real reader and tool (a reserved device name as the direct parent is neither listed nor read; one above it is read, and
listed off Windows). T29 and T30 are corrected: only the direct parent is refused, not every ancestor.
"""

from __future__ import annotations

import ctypes
import itertools
import os
import shutil
import tempfile
from pathlib import Path, PurePosixPath, PureWindowsPath
````
REPLACE:
````
own verdict), the function calls no filesystem function (T32), and a directory that holds names the reader's gate refuses
is listed without them, from an ordinary and an extended-prefix base, with every name it lists opened by the verified
reader (T33, Windows). None of these says that a listed name opens: BF-953 L18 lists what a listing cannot promise.

Amendment 4 (review round 5, T34 and T35): T34 compares ``reader_spelling`` with the verified reader's own functions over a
generated corpus of file texts (the POSIX shape on every platform, the Windows shape on Windows); T35 reads and lists real
files with the real reader and tool (a reserved device name as the direct parent is neither listed nor read; one above it
is read, and listed off Windows). T29 and T30 are corrected: only the direct parent is refused, not every ancestor.

Amendment 5 (review round 6, T36 to T38): a path with no final name (a root) has no spelling, and a real pinned directory
refuses its empty name (T36; T38 lists a drive root through the real tool, Windows); a path with a ``..`` part has none (T29,
T30, and T34's corpus holds both kinds of text). T34 takes the location gate from ``validate_read_location`` and the
child-name verdict from a real pinned directory's public ``read_bytes``; it no longer reaches into the pinned directory. T37
records the texts a real ``read_verified_file`` gives the location gate, and fails if they change: T34's oracle and the
probes of the review encode that sequence by hand, and T37 is what ties it to the reader (BF-953 L18).
"""

from __future__ import annotations

import ctypes
import itertools
import ntpath
import os
import posixpath
import shutil
import tempfile
from pathlib import Path, PurePosixPath, PureWindowsPath
````

SEARCH:
````
    ("a reserved device name above the direct parent", ("con", "sub", "g.txt"), False, True),
    ("a trailing dot on an ancestor", ("dir.", "deep.txt"), False, True),
    ("a trailing space on an ancestor", ("dir ", "deep.txt"), False, True),
]


@pytest.mark.parametrize(("label", "parts", "on_windows", "elsewhere"), _TEXT_CASES, ids=[row[0] for row in _TEXT_CASES])
def test_the_reader_spelling_follows_the_verified_readers_rules_on_the_text(
````
REPLACE:
````
    ("a reserved device name above the direct parent", ("con", "sub", "g.txt"), False, True),
    ("a trailing dot on an ancestor", ("dir.", "deep.txt"), False, True),
    ("a trailing space on an ancestor", ("dir ", "deep.txt"), False, True),
    ("a '..' as the final name", ("sub", ".."), False, False),
    ("a '..' that leaves a reserved device name as the direct parent", ("con", "sub", "..", "g.txt"), False, False),
    ("a '..' that leaves an admitted name", ("src", "..", "g.txt"), False, False),
]


@pytest.mark.parametrize(("label", "parts", "on_windows", "elsewhere"), _TEXT_CASES, ids=[row[0] for row in _TEXT_CASES])
def test_the_reader_spelling_follows_the_verified_readers_rules_on_the_text(
````

SEARCH:
````
def test_the_reader_spelling_follows_the_verified_readers_rules_on_the_text(
    label: str, parts: tuple[str, ...], on_windows: bool, elsewhere: bool,
) -> None:
    """T29 (review round 4, F1; corrected by review round 5; any platform): ``reader_spelling`` gives a spelling only where
    the verified reader's rules on the text admit it. Text that is not strict UTF-8 (a lone surrogate in the final name or an
    ancestor), a colon or a character below 32 anywhere, a reserved device name as the final name or as the direct parent
    (the reader gives both the file and the directory it pins to its location gate), and a trailing dot or space in the final
    name give none, on every platform; an ordinary, a non-ASCII and an astral name give the path itself. A reserved device
    name above the direct parent, or a trailing dot or space in an ancestor, gives none on Windows only: the reader opens
    the directories above the direct parent without the gate (BF-953 L21). Whatever the reader's own location gate refuses
    gives none."""
    path = _listed(*parts)
    got = file_access.reader_spelling(path)
    assert (got is not None) == (on_windows if os.name == "nt" else elsewhere), f"{label}: {got}"
````
REPLACE:
````
def test_the_reader_spelling_follows_the_verified_readers_rules_on_the_text(
    label: str, parts: tuple[str, ...], on_windows: bool, elsewhere: bool,
) -> None:
    """T29 (review round 4, F1; corrected by rounds 5 and 6; any platform): ``reader_spelling`` of the path built from the
    row's parts gives a spelling only where the verified reader's own functions admit its text, as the row's label says;
    a row's two answers differ only where Windows' same-file rule is wider than the reader's text path (BF-953 L21). A path
    whose text the reader's location gate refuses gives none, and an answer that is a spelling is the path itself."""
    path = _listed(*parts)
    got = file_access.reader_spelling(path)
    assert (got is not None) == (on_windows if os.name == "nt" else elsewhere), f"{label}: {got}"
````

SEARCH:
````
    ("a trailing space in the final name", "/data/note ", False),
    ("a name decoded with surrogateescape", "/data/\udcff.txt", False),
    ("a relative spelling", "data/note.txt", False),
]


@pytest.mark.parametrize(("label", "text", "given"), _POSIX_CASES, ids=[row[0] for row in _POSIX_CASES])
def test_the_reader_spelling_applies_the_readers_rules_off_windows_too(
````
REPLACE:
````
    ("a trailing space in the final name", "/data/note ", False),
    ("a name decoded with surrogateescape", "/data/\udcff.txt", False),
    ("a relative spelling", "data/note.txt", False),
    ("a filesystem root", "/", False),
    ("a root with two leading separators", "//", False),
    ("a '..' as the final name", "/data/src/..", False),
    ("a '..' that leaves a reserved device name as the direct parent", "/data/con/sub/../g.txt", False),
    ("a '..' that leaves a reserved device stem as the direct parent", "/data/aux.py/sub/../g.txt", False),
    ("a '..' that leaves an admitted name", "/data/sub/../g.txt", False),
]


@pytest.mark.parametrize(("label", "text", "given"), _POSIX_CASES, ids=[row[0] for row in _POSIX_CASES])
def test_the_reader_spelling_applies_the_readers_rules_off_windows_too(
````

SEARCH:
````
def test_the_reader_spelling_applies_the_readers_rules_off_windows_too(
    monkeypatch: pytest.MonkeyPatch, label: str, text: str, given: bool,
) -> None:
    """T30 (review round 4, F1; corrected by review round 5; any platform): with ``os.name`` set to ``posix`` for the one call
    (a no-op on a POSIX host), the function takes the branch a POSIX host takes, and the reader's rules on the text still
    apply in it: a colon, a newline, a reserved device stem as the final name or as the direct parent, a backslash, a
    trailing dot or space in the final name, a name decoded with ``surrogateescape`` and a relative spelling give none, and
    a reserved device name above the direct parent, or a trailing dot or space in an ancestor, which only Windows refuses,
    gives the path itself."""
    path = PurePosixPath(text)
    with monkeypatch.context() as patch:
        patch.setattr(os, "name", "posix")
````
REPLACE:
````
def test_the_reader_spelling_applies_the_readers_rules_off_windows_too(
    monkeypatch: pytest.MonkeyPatch, label: str, text: str, given: bool,
) -> None:
    """T30 (review round 4, F1; corrected by rounds 5 and 6; any platform): with ``os.name`` set to ``posix`` for the one call
    (a no-op on a POSIX host), the function takes the branch a POSIX host takes, and ``reader_spelling`` of the row's POSIX
    text gives a spelling only where the verified reader's own functions admit it, as the row's label says; a rule only
    Windows has gives the path itself here (BF-953 L21). An answer that is a spelling is the path itself."""
    path = PurePosixPath(text)
    with monkeypatch.context() as patch:
        patch.setattr(os, "name", "posix")
````

SEARCH:
````
        snapshot = file_access.read_verified_file(reader.resolve_source_path(name), **roots)
        with open(prefixed + "\\" + str(Path(name).relative_to(root)), "rb") as source:
            assert snapshot.data == source.read(), f"{spelling}: the verified reader opened {name!r}"


# --- M7 (Amendment 4, review round 5): the listing admits exactly what the verified reader's text path admits ---


class _TextOnlyDirectory(file_access.PinnedDirectory):
    """A pinned directory with no handle: ``verify`` does nothing, so the real ``_leaf`` runs on a text."""

    def verify(self) -> None:
        return None


class _PosixParent(str):
    """A parent text that joins a child name as a POSIX path does, so the real ``_leaf`` runs its location gate on a ``str``."""

    def __truediv__(self, name: str) -> str:
        return str(PurePosixPath(self) / name)


class _WindowsParent(str):
    """The same for a Windows path."""

    def __truediv__(self, name: str) -> str:
        return str(PureWindowsPath(self) / name)


_TEXT_SHAPES = {"posix": (PurePosixPath, _PosixParent, "/data", "/"), "windows": (PureWindowsPath, _WindowsParent, "C:\\data", "\\")}

# (component, withheld by Windows' same-file rule wherever it stands: a reserved device name, a trailing dot or a trailing space)
_CORPUS_DIRS = [
    ("src", False), ("x..y", False), ("a:b", False),
    ("con", True), ("aux.py", True), ("dot.", True), ("space ", True),
]
_CORPUS_FILES = ["g.txt", "note", "x..y", "dot.", "space ", "a:b", "back\\slash", "aux.py", "con", "\ud800.txt"]


def _corpus(base: str, sep: str) -> list[tuple[str, bool]]:
    """Every file text from zero to three directories below *base*, each directory from ``_CORPUS_DIRS``, each final name
    from ``_CORPUS_FILES``; with whether Windows' same-file rule withholds a directory of it."""
    texts = []
    for depth in range(4):
        for dirs in itertools.product(_CORPUS_DIRS, repeat=depth):
            prefix = base + "".join(sep + name for name, _ in dirs)
            texts += [(f"{prefix}{sep}{name}", any(flag for _, flag in dirs)) for name in _CORPUS_FILES]
    return texts


def _reader_admits(text: str, shape: str, *, parent_gate: bool = True) -> bool:
    """Whether the steps the armed reader takes on a text alone admit *text*, each one the reader's own call, in the order
    ``read_verified_file`` takes them: its location gate on the file; its location gate on the file's direct parent, which
    ``PinnedDirectory.open`` applies to the path ``pin_directory(candidate.parent)`` gives it; then the child-name rule and
    the location gate of ``read_bytes``, run by the real ``PinnedDirectory._leaf`` on a directory with no handle. Nothing in
    the reader reads the text again: the directories above the direct parent are opened by name."""
    pure, parent_type, _, _ = _TEXT_SHAPES[shape]
    parsed = pure(text)
    directory = _TextOnlyDirectory()
    directory._paths = [parent_type(str(parsed.parent))]  # type: ignore[list-item]
    try:
        file_access.validate_read_location(text)
        if parent_gate:
            file_access.validate_read_location(str(parsed.parent))
        directory._leaf(parsed.name)
    except (ValueError, FileAccessDenied):
        return False
    return True


@pytest.mark.parametrize("shape", ["posix", pytest.param("windows", marks=WINDOWS)])
def test_the_listing_admits_exactly_what_the_verified_readers_text_path_admits(
    monkeypatch: pytest.MonkeyPatch, shape: str,
) -> None:
    """T34 (review round 5, A; the POSIX shape on any platform with ``os.name`` set to ``posix`` for the calls, the Windows
    shape on Windows): over a generated corpus of file texts (a reserved device name, a trailing dot or space, a colon and an
    ordinary name as a directory from zero to three deep, and as the final name, with a lone surrogate and a backslash among
    the final names), ``reader_spelling``
    gives a spelling for no text the verified reader's text path refuses, and for every text it admits, except on Windows
    one that the same-file rule withholds (a reserved device name, a trailing dot or a trailing space in a directory). The
    reader's text path is its own functions: ``validate_read_location`` on the file and on the file's direct parent, and the
    real ``PinnedDirectory._leaf``. Premises: the corpus is large, the reader's text path admits and refuses a share of it,
    and the corpus holds texts that only the parent's gate refuses."""
    pure, _, base, sep = _TEXT_SHAPES[shape]
    texts = _corpus(base, sep)
    holes: list[str] = []
    misses: list[str] = []
    admitted_count = only_the_parent_gate_refuses = 0
    with monkeypatch.context() as patch:
        if shape == "posix":
            patch.setattr(os, "name", "posix")
        for text, same_file_withholds in texts:
            admitted = _reader_admits(text, shape)
            admitted_count += admitted
            only_the_parent_gate_refuses += (not admitted) and _reader_admits(text, shape, parent_gate=False)
            listed = file_access.reader_spelling(PurePosixPath(text) if shape == "posix" else Path(text)) is not None
            if listed and not admitted:
                holes.append(text)
            if admitted and not listed and not (shape == "windows" and same_file_withholds):
                misses.append(text)
    assert len(texts) >= 3500, "premise: the corpus is large"
    assert 0.05 * len(texts) < admitted_count < 0.95 * len(texts), "premise: the reader's text path admits and refuses a share"
    assert only_the_parent_gate_refuses >= 100, "premise: the corpus holds texts only the parent's gate refuses"
    assert not holes, f"{len(holes)} listed texts the reader's text path refuses, for example {holes[:3]!r}"
    assert not misses, f"{len(misses)} texts the reader's text path admits and the listing withholds, for example {misses[:3]!r}"


def _make_file(root: Path, rel: tuple[str, ...], data: bytes) -> None:
    base = ("\\\\?\\" + str(root)) if os.name == "nt" else str(root)
    target = base + os.sep + os.sep.join(rel)
````
REPLACE:
````
        snapshot = file_access.read_verified_file(reader.resolve_source_path(name), **roots)
        with open(prefixed + "\\" + str(Path(name).relative_to(root)), "rb") as source:
            assert snapshot.data == source.read(), f"{spelling}: the verified reader opened {name!r}"


# --- M7 and M8 (Amendments 4 and 5, review rounds 5 and 6): the listing is compared with the verified reader's own functions ---


_TEXT_SHAPES = {
    "posix": (posixpath, PurePosixPath, "/data", "/"),
    "windows": (ntpath, PureWindowsPath, "C:\\data", "C:\\"),
}

# (component, withheld by Windows' same-file rule wherever it stands: a reserved device name, a trailing dot or a trailing space)
_CORPUS_DIRS = [
    ("src", False), ("x..y", False), ("a:b", False), ("..", False), (".hidden", False),
    ("con", True), ("aux.py", True), ("dot.", True), ("space ", True),
]
_CORPUS_FILES = ["g.txt", "note", "x..y", "dot.", "space ", "a:b", "back\\slash", "aux.py", "con", "\ud800.txt", ".hidden"]


def _corpus(shape: str) -> list[tuple[str, bool]]:
    """Every file text of the shape: the root itself, each final name of ``_CORPUS_FILES`` directly under the root, and each
    final name from zero to three directories of ``_CORPUS_DIRS`` below the base; with whether Windows' same-file rule withholds a
    directory of it. Each text is the text of a path object, as a listing gives it."""
    _, pure, base, root = _TEXT_SHAPES[shape]
    sep = root[-1]
    texts = [(root, False)] + [(str(pure(root + name)), False) for name in _CORPUS_FILES]
    for depth in range(4):
        for dirs in itertools.product(_CORPUS_DIRS, repeat=depth):
            prefix = base + "".join(sep + name for name, _ in dirs)
            texts += [(str(pure(f"{prefix}{sep}{name}")), any(flag for _, flag in dirs)) for name in _CORPUS_FILES]
    return texts


def _name_refused(directory: file_access.PinnedDirectory, name: str) -> bool:
    """Whether a real pinned directory refuses *name* as a child, through its public ``read_bytes``: by its own rule
    (``FileAccessDenied``) or by its location gate (``ValueError``). A name both admit is read as far as the file that is not there."""
    try:
        directory.read_bytes(name)
    except (FileAccessDenied, ValueError):
        return True
    except FileNotFoundError:
        return False
    raise AssertionError(f"premise: {name!r} is not a file of the pinned directory")


def _reader_admits(
    text: str, shape: str, refused_names: dict[str, bool], *, parent_gate: bool = True, normalise: bool = True,
) -> bool:
    """Whether the verified reader's text path admits *text*, as the reader's own functions answer, in the order
    ``read_verified_file`` takes them, on the candidate ``validate_read_location`` returns for an absolute text (the normal
    form of the shape, which is what ``os.path.abspath`` gives it): the location gate on the text; the location gate on the
    candidate's direct parent (``PinnedDirectory.open``); and a real pinned directory's verdict on the candidate's final name
    (``read_bytes``: its child-name rule and the gate it applies to the file; the verdicts are in *refused_names*). The sequence
    is encoded here by hand: BF-953 T37 records it from the reader."""
    pathmod = _TEXT_SHAPES[shape][0]
    candidate = pathmod.normpath(text) if normalise else text
    parent, name = pathmod.split(candidate)
    try:
        file_access.validate_read_location(text)
        if parent_gate:
            file_access.validate_read_location(parent)
    except ValueError:
        return False
    return not refused_names[name]


@pytest.mark.parametrize("shape", ["posix", pytest.param("windows", marks=WINDOWS)])
def test_the_listing_agrees_with_the_verified_readers_text_path_over_a_generated_corpus(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, shape: str,
) -> None:
    """T34 (review round 5, A; review round 6, F1 to F3; the POSIX shape on any platform with ``os.name`` set to ``posix`` for
    the calls, the Windows shape on Windows): over a generated corpus of file texts (each row of ``_CORPUS_DIRS`` and
    ``_CORPUS_FILES`` from zero to three directories deep, the root itself and each final name directly under it),
    ``reader_spelling`` gives a spelling for no text that the oracle refuses and for no text that is not its own normal
    form, and withholds no text the oracle admits except one the same-file rule withholds (Windows) or one that is not its own
    normal form (a ``..`` part). The oracle is the reader's own functions, from the public API only: ``validate_read_location``
    and a real pinned directory's ``read_bytes`` (``_reader_admits``). Premises: the corpus is large; the oracle admits and
    refuses a share of it; some texts are refused only by the parent's gate and some only by normalising; the corpus holds a
    path with no final name and the oracle refuses it; some texts the oracle admits are not their own normal form."""
    pathmod, _, _, root = _TEXT_SHAPES[shape]
    texts = _corpus(shape)
    with file_access.pin_directory(tmp_path.resolve()) as directory:  # the child verdicts, on the real platform
        names = {pathmod.split(form)[1] for text, _ in texts for form in (text, pathmod.normpath(text))}
        refused_names = {name: _name_refused(directory, name) for name in names}
    holes: list[str] = []
    misses: list[str] = []
    admitted_count = only_the_parent_gate_refuses = only_normalising_refuses = admitted_not_normal = 0
    with monkeypatch.context() as patch:
        if shape == "posix":
            patch.setattr(os, "name", "posix")
        assert not _reader_admits(root, shape, refused_names), "premise: the oracle refuses a root"
        for text, same_file_withholds in texts:
            normal = pathmod.normpath(text) == text
            admitted = _reader_admits(text, shape, refused_names)
            admitted_count += admitted
            if not admitted:
                only_the_parent_gate_refuses += _reader_admits(text, shape, refused_names, parent_gate=False)
                only_normalising_refuses += _reader_admits(text, shape, refused_names, normalise=False)
            admitted_not_normal += admitted and not normal
            listed = file_access.reader_spelling(PurePosixPath(text) if shape == "posix" else Path(text)) is not None
            if listed and not (admitted and normal):
                holes.append(text)
            if admitted and not listed and normal and not (shape == "windows" and same_file_withholds):
                misses.append(text)
    assert len(texts) >= 6000, "premise: the corpus is large"
    assert any(not pathmod.split(text)[1] for text, _ in texts), "premise: the corpus holds a path with no final name"
    assert 0.05 * len(texts) < admitted_count < 0.95 * len(texts), "premise: the oracle admits and refuses a share"
    assert only_the_parent_gate_refuses >= 100, "premise: the corpus holds texts only the parent's gate refuses"
    assert only_normalising_refuses >= 20, "premise: the corpus holds texts only normalising refuses"
    assert admitted_not_normal >= 100, "premise: the corpus holds admitted texts that are not their own normal form"
    assert not holes, f"{len(holes)} listed texts the oracle refuses or that are not their own normal form, for example {holes[:3]!r}"
    assert not misses, f"{len(misses)} texts the oracle admits and the listing withholds, for example {misses[:3]!r}"


def _make_file(root: Path, rel: tuple[str, ...], data: bytes) -> None:
    base = ("\\\\?\\" + str(root)) if os.name == "nt" else str(root)
    target = base + os.sep + os.sep.join(rel)
````

SEARCH:
````
) -> None:
    """T35 (review round 5, A; any platform, real files): a directory named ``con`` and one named ``aux.py`` (made through the
    extended namespace on Windows) each hold ``g.txt``, as does an ordinary directory and ``con/sub``. The real
    ``read_verified_file`` refuses a file whose direct parent is a reserved device name before it reads the disk
    (``ValueError``), and reads the ordinary one and the one a reserved name above its direct parent. ``list_files`` lists the
    ordinary one and, off Windows, the one above, and each file it lists is read by the verified reader with its own bytes;
    on Windows the same-file rule also withholds the one above (BF-953 L21)."""
    root = tmp_path.resolve() / "d"
````
REPLACE:
````
) -> None:
    """T35 (review round 5, A; any platform, real files): a directory named ``con`` and one named ``aux.py`` (made through the
    extended namespace on Windows) each hold ``g.txt``, as does an ordinary directory and ``con/sub``. The real
    ``read_verified_file`` refuses a file whose direct parent is a reserved device name (``ValueError``), and reads the ordinary
    one and the one a reserved name above its direct parent. ``list_files`` lists the
    ordinary one and, off Windows, the one above, and each file it lists is read by the verified reader with its own bytes;
    on Windows the same-file rule also withholds the one above (BF-953 L21)."""
    root = tmp_path.resolve() / "d"
````

SEARCH:
````
    assert sorted(listed.output["files"]) == sorted(str(root.joinpath(*rel)) for rel in expected)
    for name in listed.output["files"]:
        assert verified(name) == files[Path(name).relative_to(root).parts], f"the verified reader opened {name!r}"
````
REPLACE:
````
    assert sorted(listed.output["files"]) == sorted(str(root.joinpath(*rel)) for rel in expected)
    for name in listed.output["files"]:
        assert verified(name) == files[Path(name).relative_to(root).parts], f"the verified reader opened {name!r}"


@pytest.mark.parametrize("kind", ["the root of this platform's base", pytest.param("a share root", marks=WINDOWS)])
def test_a_path_with_no_final_name_has_no_spelling_and_the_pinned_directory_refuses_its_empty_name(
    tmp_path: Path, kind: str,
) -> None:
    """T36 (review round 6, F1; any platform): a root has no final name. A real pinned directory's ``read_bytes`` refuses the
    empty name as a child name (``invalid child name``), and ``reader_spelling`` of the root gives none, so the lister's
    restatement of that rule includes it. The root is the anchor of this platform's base, or (Windows) a share root."""
    root = Path(_listed().anchor) if kind == "the root of this platform's base" else Path("\\\\host\\share\\")
    assert root.name == "", "premise: the path has no final name"
    with file_access.pin_directory(tmp_path.resolve()) as directory:
        with pytest.raises(FileAccessDenied) as refused:
            directory.read_bytes(root.name)
    assert refused.value.reason == "invalid child name"
    assert file_access.reader_spelling(root) is None


@WINDOWS
async def test_a_listing_whose_only_match_is_a_drive_root_lists_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """T38 (review round 6, F1; Windows): the real ``list_files`` of this platform's drive root, with ``Path.glob`` yielding only
    the base (the pattern ``**`` yields the base first; a listing of a whole drive is not run), lists nothing. The read policy
    admits the root, and the real verified reader refuses its empty name (``invalid child name``), so what leaves the root out
    is ``reader_spelling`` (T36 is the same property on the function)."""
    runtime = _runtime(_scene(tmp_path), read_roots=[])
    root = Path(tmp_path.anchor)
    roots: dict[str, Any] = {
        "protected_roots": file_access.protected_read_roots(runtime), "exempt_roots": file_access.workspace_exempt_roots(runtime),
        "permitted_roots": file_access.permitted_read_roots(runtime) or None,
    }
    file_access.resolve_read_path(str(root), **roots)  # premise: the policy admits the root (it raises FileAccessDenied otherwise)
    with pytest.raises(FileAccessDenied) as refused:
        file_access.read_verified_file(root, **roots)
    assert refused.value.reason == "invalid child name"
    monkeypatch.setattr(Path, "glob", lambda self, pattern, *args, **kwargs: iter([self]))
    listed = await ListFilesTool(runtime).invoke({"pattern": "**", "path": str(root)})
    assert listed.error is None and listed.output == {"files": []}, listed


@pytest.mark.parametrize("text_kind", ["a canonical text", "a text with a '..' part"])
def test_the_verified_reader_gives_its_location_gate_the_file_and_its_direct_parent_and_nothing_above(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, text_kind: str,
) -> None:
    """T37 (review round 6, B6-3; any platform, a real file): the real ``read_verified_file`` of a file two directories deep
    gives ``validate_read_location`` the file's text, then the direct parent of the candidate it returned, then the candidate
    (``PinnedDirectory.open`` and ``_leaf``), in that order, and no directory above the direct parent; for a text with a
    ``..`` part, the candidate is the text's normal form. T34's oracle and the probes of the review encode this sequence by
    hand; this test records it from the reader, so a change of which texts the reader gives its gate fails here, and
    ``reader_spelling``, T34's oracle and the probes must then be audited (BF-953 L18, L21)."""
    target = tmp_path.resolve() / "a" / "b" / "g.txt"
    target.parent.mkdir(parents=True)
    target.write_bytes(_CONTENT)
    path = target if text_kind == "a canonical text" else target.parent / ".." / "b" / "g.txt"
    seen: list[str] = []
    real_gate = file_access.validate_read_location

    def recording(raw: Any, **kwargs: Any) -> Path:
        seen.append(str(raw))
        return real_gate(raw, **kwargs)

    monkeypatch.setattr(file_access, "validate_read_location", recording)
    assert file_access.read_verified_file(path, protected_roots=[]).data == _CONTENT
    assert seen == [str(path), str(target.parent), str(target)], seen
````

## 8. Tracking (M3's commit)

**Head constraint:** neither head may carry a lifecycle keyword from `gen_ad_ledger.py` `_STATUS_PATTERNS` (`:126-132`: retired, abandoned, withdrawn, superseded, deferred, postponed, closed, shipped, staged, landed, open) in its first 120 characters.
**Date rule:** both heads carry 2026-11-04. If M3 is committed on another local date (`git log -1 --format=%cs`), use that date in both heads.
**Issue number:** the heads carry `#1752` (the BF-953 issue, `gh issue view 1752`).
**Only insert.** Both pairs add text and change no line of BF-948's entries: BF-948's M4 amends those lines by SEARCH later (its P4-6 and P4-7), and each of those SEARCH strings must still occur exactly once after M3 (§13 checks it).
**Staging:** explicit paths only; `PROGRESS.md` and `DECISIONS.md` may hold unrelated work.

**B3-1** `PROGRESS.md`

SEARCH:
````
# ProbOS Progress

````
REPLACE:
````
# ProbOS Progress

**BF-953 (2026-11-04), #1752 -- the read floor decides every spelling of one file the same way.** `resolve_read_path` decided a path by comparing the text of its resolved form with the roots, so on Windows a path spelled with the extended-length prefix or as a share path of a local drive was decided differently from its ordinary spelling, for the floor, the exempt roots and the permitted roots. Now `_longest_match` compares each path and root without its namespace prefix, and a path or root that still names a share or device is also compared by the identity the system gives the file (volume and file index, read once per call and only for those spellings, on Windows only). The function returns the resolved path as before; no config field; other platforms are unchanged. The contract is `prompts/bf-953-read-floor-spellings.md`, with its own tests over `ReadFileTool`, `ListFilesTool` and the write side.

````

**B3-2** `DECISIONS.md`

SEARCH:
````
### BF-948 -- list_files lists only what the read policy admits (2026-11-04, #1736)
````
REPLACE:
````
### BF-953 -- The read floor decides every spelling of one file the same way (2026-11-04, #1752)

- *Scope.* `security/file_access.py` (`_longest_match`, `_namespace_free`, `_file_identity`, `_OnDisk`; `resolve_read_path`'s docstring and its three calls), tests. Contract `prompts/bf-953-read-floor-spellings.md`.
- *SP1 (the decision).* Containment is decided on the namespace-free text of the path and the root; a path or root that still names a share or device is also decided by file identity, read once per call and only for those spellings, on Windows only. Rejected: the textual key alone (it cannot name a machine's own names); the system's final path name (it reports what it was given); refusing every share path (it refuses a legitimate network path and needs an operator escape); identity for every path (a stat per ancestor on every read).
- *SP2 (the return).* The resolved path, as before. It names the file the decision was made on. Rejected: returning the rewritten text (it can name another file).
- *SP3 (no escape).* No config field and no operator escape: nothing admitted for a reason other than its spelling is refused.
- *SP4 (other platforms).* The textual test is the whole decision wherever `os.name` is not `nt`.
- *Residual.* Recorded limits L1 to L8 of the contract.
- *Reversal.* Revert the BF-953 commits.

### BF-948 -- list_files lists only what the read policy admits (2026-11-04, #1736)
````

Then regenerate the ledger (`python -P scripts/gen_ad_ledger.py`) and stage `docs/development/open-ads-report.md` and `docs/development/ad-ledger-snapshot.json` as the tool writes them. **Not updated:** `docs/development/roadmap.md` (its Bug Tracker lists BFs filed and not fixed; BF-953 is fixed in this PR).

**M4's tracker pairs (in M4's commit).** They amend the committed M3 text in place. The heads and their dates are unchanged, so the head constraint still holds. Regenerate the ledger afterwards and stage what it writes.

**B5-1** `PROGRESS.md`

SEARCH:
````
Now `_longest_match` compares each path and root without its namespace prefix, and a path or root that still names a share or device is also compared by the identity the system gives the file (volume and file index, read once per call and only for those spellings, on Windows only). The function returns the resolved path as before; no config field; other platforms are unchanged.
````
REPLACE:
````
Now `_match_position` compares each path and root without its namespace prefix, for the floor, the exempt roots and the permitted roots. The floor alone is also decided by identity, for a path or root that still names a share or device (volume and file index, read once per call and only for those spellings, on Windows only): a floor root contains the path when it is one of the parts of the path's own chain or the chain reaches the root's volume through a link, and a floor that cannot be read refuses; an exempt or permitted root admits a share or device spelling only if its text names it, and an exemption is ranked by where it stands in the path's own chain, not by how its root is spelled. The read-policy root builders resolve the workspace root as a candidate is resolved. On Windows the final component of a floor file root and of a credential name is compared by the file it names (a stream suffix, trailing dots or spaces, and for a credential name another case, do not make another file), whether or not the file is on disk; an admitted read keeps the path as resolved. The function returns the resolved path as before; no config field; other platforms are unchanged.
````

**B5-2** `DECISIONS.md` (four edits, each SEARCH unique)

SEARCH:
````
- *Scope.* `security/file_access.py` (`_longest_match`, `_namespace_free`, `_file_identity`, `_OnDisk`; `resolve_read_path`'s docstring and its three calls), tests. Contract `prompts/bf-953-read-floor-spellings.md`.
````
REPLACE:
````
- *Scope.* `security/file_access.py` (`_match_position`, `_identity_position`, `_namespace_free`, `_file_identity`, `_OnDisk`, `_Unverifiable`, `_base_name`, `_base_file`, `_protected_leaf`, `plain_spelling`; `resolve_read_path`'s docstring and its three calls; the workspace root in `permitted_read_roots` and `workspace_exempt_roots`), tests. Contract `prompts/bf-953-read-floor-spellings.md` (with Amendment 1).
````

SEARCH:
````
a path or root that still names a share or device is also decided by file identity, read once per call and only for those spellings, on Windows only. Rejected:
````
REPLACE:
````
for the floor alone, a path or root that still names a share or device is also decided by file identity, read once per call and only for those spellings, on Windows only (SP5). Rejected:
````

SEARCH:
````
- *SP3 (no escape).* No config field and no operator escape: nothing admitted for a reason other than its spelling is refused.
````
REPLACE:
````
- *SP3 (no escape).* No config field and no operator escape: nothing admitted for a reason other than its spelling is refused. A share spelling of the agent workspace, admitted before only because the floor did not match it, is refused (SP5).
````

SEARCH:
````
- *SP4 (other platforms).* The textual test is the whole decision wherever `os.name` is not `nt`.
- *Residual.* Recorded limits L1 to L8 of the contract.
````
REPLACE:
````
- *SP4 (other platforms).* The textual test is the whole decision wherever `os.name` is not `nt`.
- *SP5 (identity is deny-only, Amendment 1).* The floor is decided by text, by the identity of the path's own chain, by the volumes the chain reaches through a link, and refuses when it cannot be read; an exempt or a permitted root by text alone; an exemption is ranked by where it stands in the path's own chain, not by how its root is spelled. Rejected: identity for the allow-lists too, with per-step transition checks (the system gives a share spelling no physical path); mapping a local share spelling to its drive spelling (aliases and device forms remain); refusing every share spelling (a legitimate remote read, and an escape).
- *SP6 (the roots the builders compose).* `permitted_read_roots` and `workspace_exempt_roots` resolve the workspace root as a candidate is resolved.
- *SP7 (the display form).* `plain_spelling` is the spelling `list_files` shows (BF-948's M5). Rejected: a reader change.
- *SP8 (the final component, update 2).* On Windows the floor's file roots and the credential names are compared by the file the final component names: the text from the first colon and trailing dots and spaces are dropped, and the credential names are compared in the write side's case-folded key; an admitted read keeps the path as resolved. Rejected: refusing every colon, trailing-dot or trailing-space name (a neighbour's stream is the caller's own file); a lookup on disk (an absent file has no identity); changing the write side's key (BF-911's). In the extended namespace a name with a trailing dot or space can be a different file; it is refused (L14).
- *Residual.* Recorded limits L1 to L15 of the contract.
````

**M5's tracker pairs (in M5's commit).** They amend the committed text in place. The heads and their dates are unchanged, so the head constraint still holds, and the ledger needs no regeneration: `gen_ad_ledger.py --check` says it is current (measured), and a regeneration would only rewrite the captured git head and time.

**B7-1** `PROGRESS.md`

SEARCH:
````
The read-policy root builders resolve the workspace root as a candidate is resolved. On Windows the final component of a floor file root and of a credential name is compared by the file it names (a stream suffix, trailing dots or spaces, and for a credential name another case, do not make another file), whether or not the file is on disk; an admitted read keeps the path as resolved.
````
REPLACE:
````
The read-policy root builders resolve the workspace root as a candidate is resolved, and keep it as composed when the system cannot resolve it, so a configured read policy still confines reads. On Windows the final component of a floor file root and of a credential name is compared by the file it names, the root's as well as the candidate's: a stream suffix, trailing dots or spaces (and for a credential name another case) on either side are refused as the file is, whether or not the file is on disk. That is a deny-side text rule: in the extended namespace a name that ends in a dot or a space can be another file, and it is refused too. An admitted read keeps the path as `Path.resolve()` spelled it. `reader_spelling` says whether a listing may name a match (BF-948).
````

**B7-2** `DECISIONS.md` (three edits, each SEARCH unique)

SEARCH:
````
- *Scope.* `security/file_access.py` (`_match_position`, `_identity_position`, `_namespace_free`, `_file_identity`, `_OnDisk`, `_Unverifiable`, `_base_name`, `_base_file`, `_protected_leaf`, `plain_spelling`; `resolve_read_path`'s docstring and its three calls; the workspace root in `permitted_read_roots` and `workspace_exempt_roots`), tests. Contract `prompts/bf-953-read-floor-spellings.md` (with Amendment 1).
````
REPLACE:
````
- *Scope.* `security/file_access.py` (`_match_position`, `_identity_position`, `_namespace_free`, `_file_identity`, `_OnDisk`, `_Unverifiable`, `_base_name`, `_base_file`, `_floor_roots`, `_protected_leaf`, `_workspace_root`, `plain_spelling`, `reader_spelling`; `resolve_read_path`'s docstring and its three calls; the workspace root in `permitted_read_roots` and `workspace_exempt_roots`), tests. Contract `prompts/bf-953-read-floor-spellings.md` (with Amendments 1 and 2).
````

SEARCH:
````
- *SP6 (the roots the builders compose).* `permitted_read_roots` and `workspace_exempt_roots` resolve the workspace root as a candidate is resolved.
- *SP7 (the display form).* `plain_spelling` is the spelling `list_files` shows (BF-948's M5). Rejected: a reader change.
````
REPLACE:
````
- *SP6 (the roots the builders compose).* `permitted_read_roots` and `workspace_exempt_roots` resolve the workspace root as a candidate is resolved, through one helper (`_workspace_root`, SP10).
- *SP7 (the display form).* `plain_spelling` is the spelling `list_files` shows (BF-948's M5), and only where `reader_spelling` gives one (SP11). Rejected: a reader change.
````

SEARCH:
````
- *Residual.* Recorded limits L1 to L15 of the contract.
````
REPLACE:
````
- *SP9 (a floor file root is compared by its file, Amendment 2).* `_floor_roots` adds the file each root's final component names after the root, so a root spelled as a stream, or with a trailing dot or space, refuses every spelling of its file, as a candidate's final component is reduced. A root that names itself adds nothing. Rejected: replacing the root by its file (it would stop refusing an extended-namespace directory spelled with a trailing dot or space); reducing in `protected_config_files` (the write side's list).
- *SP10 (the workspace root as composed, Amendment 2).* `_workspace_root` resolves the configured workspace root and, when the system cannot resolve it, keeps it as composed, as before BF-953, so a configured read policy still confines reads. A policy whose every root is unusable and whose workspace root cannot be composed is `[]`, as on the base (L17). Rejected: a root that matches nothing, in a list whose emptiness means "none configured".
- *SP11 (the spelling a listing may name, Amendment 2).* `reader_spelling` is `plain_spelling` when every component after the anchor names, as an ordinary path, what it names in the extended namespace (none ends in a dot or a space; no part is a reserved device name), and none otherwise; textual, no system call. Rejected: an identity rule (two `os.stat` per match, and a volume that reports file index 0 would empty every listing); the verified reader's own location check as the gate (it checks the final component only).
- *Residual.* Recorded limits L1 to L18 of the contract.
````

**M6's tracker pairs (in M6's commit).** They amend the committed text in place. The heads and their dates are unchanged, so the head constraint still holds, and the ledger needs no regeneration: `gen_ad_ledger.py --check` says it is current.

**B9-1** `PROGRESS.md` (the BF-953 and BF-948 entries)

SEARCH:
````
`reader_spelling` says whether a listing may name a match (BF-948). The function returns the resolved path as before; no config field; other platforms are unchanged.
````
REPLACE:
````
`reader_spelling` says whether a listing may name a match (BF-948): the verified reader's rules on the text must admit the spelling, on every platform (strict UTF-8; no colon after the drive and no character below 32; no reserved device name as the final name; no backslash, trailing dot or trailing space in it) and, on Windows, every component must name in the ordinary namespace what it names in the extended one; it calls no filesystem function and does not say that the file opens. `resolve_read_path` returns the resolved path as before; no config field; on other platforms its decisions are unchanged, and a listing leaves out only the names the verified reader's rules on the text refuse.
````

SEARCH:
````
in either case without a Windows namespace prefix (the spelling the armed reader opens; a share spelling of a local directory is listed by its absolute share spelling, which the reader opens too); a match that no ordinary spelling names (a component that ends in a dot or a space, a reserved device name) is left out like a refused one.
````
REPLACE:
````
in either case without a Windows namespace prefix (the armed reader rejects it; a share spelling of a local directory is listed by its absolute share spelling, which the verified reader opens, T14); a match for which BF-953's `reader_spelling` gives no spelling (the verified reader's rules on the text refuse it, or, on Windows, no ordinary spelling names it: a component that ends in a dot or a space, a reserved device name) is left out like a refused one, and a listed name does not say that it opens.
````

**B9-2** `DECISIONS.md` (BF-953: scope, SP11, SP12, residual; BF-948: scope, LF8, LF9)

SEARCH:
````
Contract `prompts/bf-953-read-floor-spellings.md` (with Amendments 1 and 2).
````
REPLACE:
````
Contract `prompts/bf-953-read-floor-spellings.md` (with Amendments 1 to 3).
````

SEARCH:
````
- *SP11 (the spelling a listing may name, Amendment 2).* `reader_spelling` is `plain_spelling` when every component after the anchor names, as an ordinary path, what it names in the extended namespace (none ends in a dot or a space; no part is a reserved device name), and none otherwise; textual, no system call. Rejected: an identity rule (two `os.stat` per match, and a volume that reports file index 0 would empty every listing); the verified reader's own location check as the gate (it checks the final component only).
````
REPLACE:
````
- *SP11 (the spelling a listing may name, Amendment 2).* `reader_spelling` is `plain_spelling` when the verified reader's rules on the text admit it (SP12) and, on Windows, every component after the anchor names, as an ordinary path, what it names in the extended namespace (none ends in a dot or a space; no part is a reserved device name), and none otherwise; textual, no filesystem call. Rejected: an identity rule (two `os.stat` per match, and a volume that reports file index 0 would empty every listing); the verified reader's own location check as the only gate (it checks the final component only; SP12 adopts it as the first step).
- *SP12 (the verified reader's rules on the text, Amendment 3).* `reader_spelling` calls `validate_read_location` as it is and applies the pinned directory's child-name rule to the final name (a backslash, a trailing dot or a trailing space), on every platform, before SP11's Windows rule: a name that is not strict UTF-8, a colon or a character below 32, a reserved device stem as the final name and a prefix `plain_spelling` leaves are not listed. A listing follows the verified reader's rules because a `list_files` call cannot know whether the next read is armed (`_workspace_read` is set for the two reader tools only), and a name the reader rejects and the listing offers is answered `read_file failed` with the reader's own text (BF-953 L22) and counted as a tool defect when read again; a name only the plain reader opens is not listed and is still opened by its path (L19). The function calls no filesystem function and says nothing about whether a name opens (L18, L20). Rejected: strict UTF-8 only (the gate's other refusals stay listed and refused); the gate alone (a backslash, a trailing dot or a trailing space stay listed on POSIX); asking the loop (AD-1240's surface); answering the reader's lexical refusal as a caller-input error instead (BF-948 L17, the orchestrator's decision: it changes the classification, not the listing).
````

SEARCH:
````
- *Residual.* Recorded limits L1 to L18 of the contract.
````
REPLACE:
````
- *Residual.* Recorded limits L1 to L20 of the contract.
````

SEARCH:
````
Contract `prompts/bf-948-list-files-read-policy.md` (with Amendments 1 to 3).
````
REPLACE:
````
Contract `prompts/bf-948-list-files-read-policy.md` (with Amendments 1 to 4).
````

SEARCH:
````
so a prefixed base the policy admits is listed in the spelling the armed reader opens, and an extended-prefix base inside `src/` lists project-relative names. A share spelling of a local directory is listed by its absolute share spelling, which the armed reader opens too (L18).
````
REPLACE:
````
so a prefixed base the policy admits is listed in the spelling the armed reader admits (the prefix it rejects removed), and an extended-prefix base inside `src/` lists project-relative names. A share spelling of a local directory is listed by its absolute share spelling, which the verified reader opens (T14, L18).
````

SEARCH:
````
A match for which `reader_spelling` gives no spelling (a component that ends in a dot or a space, a reserved device name) is left out, like a refused one, for every base.
````
REPLACE:
````
A match for which `reader_spelling` gives no spelling (BF-953 SP11 and SP12: the verified reader's rules on the text refuse it, or, on Windows, a component ends in a dot or a space or a part is a reserved device name) is left out, like a refused one, for every base; a listed name does not say that it opens (BF-953 L18).
````

**M7's tracker pairs (in M7's commit; both entries are amended in place, their heads unchanged).**

**B11-1** `PROGRESS.md` (the BF-953 entry)

SEARCH:
````
the verified reader's rules on the text must admit the spelling, on every platform (strict UTF-8; no colon after the drive and no character below 32; no reserved device name as the final name; no backslash, trailing dot or trailing space in it) and, on Windows, every component must name in the ordinary namespace what it names in the extended one; it calls no filesystem function and does not say that the file opens.
````
REPLACE:
````
the verified reader's rules on the text must admit the spelling, on every platform, applied as the reader applies them to the file and to the directory that holds it (strict UTF-8; no colon after the drive and no character below 32; no reserved device name as the final name or as the name of that directory; no backslash, trailing dot or trailing space in the final name) and, on Windows, every component must name in the ordinary namespace what it names in the extended one; it calls no filesystem function and does not say that the file opens (a reserved device name above the directory that holds the file is not looked at off Windows, because the reader opens the directories above it by name).
````

**B11-2** `DECISIONS.md` (BF-953: scope, SP12, residual)

SEARCH:
````
Contract `prompts/bf-953-read-floor-spellings.md` (with Amendments 1 to 3).
````
REPLACE:
````
Contract `prompts/bf-953-read-floor-spellings.md` (with Amendments 1 to 4).
````

SEARCH:
````
- *SP12 (the verified reader's rules on the text, Amendment 3).* `reader_spelling` calls `validate_read_location` as it is and applies the pinned directory's child-name rule to the final name (a backslash, a trailing dot or a trailing space), on every platform, before SP11's Windows rule: a name that is not strict UTF-8, a colon or a character below 32, a reserved device stem as the final name and a prefix `plain_spelling` leaves are not listed.
````
REPLACE:
````
- *SP12 (the verified reader's rules on the text, Amendments 3 and 4).* `reader_spelling` calls `validate_read_location` as it is, on the file and on the file's direct parent (the two texts `read_verified_file` gives it), and applies the pinned directory's child-name rule to the final name (a backslash, a trailing dot or a trailing space), on every platform, before SP11's Windows rule: a name that is not strict UTF-8, a colon or a character below 32, a reserved device name or stem as the final name or as the name of the directory that holds the file, and a prefix `plain_spelling` leaves are not listed; a reserved device name above that directory is listed off Windows, because the reader opens the directories above it by name (L21).
````

SEARCH:
````
and a name the reader refuses and the listing offers is answered `invalid path` and counted as a tool defect when read again;
````
REPLACE:
````
and a name the reader rejects and the listing offers is answered `read_file failed` with the reader's own text (BF-953 L22) and counted as a tool defect when read again;
````

SEARCH:
````
Rejected: strict UTF-8 only (the gate's other refusals stay listed and refused); the gate alone (a backslash, a trailing dot or a trailing space stay listed on POSIX); asking the loop (AD-1240's surface);
````
REPLACE:
````
Rejected: strict UTF-8 only (the gate's other refusals stay listed and refused); the gate on the file alone (a backslash, a trailing dot or a trailing space stay listed on POSIX, and so does a file in a directory named as a device); a public function the reader and the lister share (it edits the armed reader, which other callers use; T34 and the orchestrator's probe are the drift guard); asking the loop (AD-1240's surface);
````

SEARCH:
````
- *Residual.* Recorded limits L1 to L20 of the contract.
````
REPLACE:
````
- *Residual.* Recorded limits L1 to L21 of the contract.
````

**M8's tracker pairs (in M8's commit; both entries are amended in place, their heads unchanged).**

**B13-1** `PROGRESS.md` (the BF-953 entry)

SEARCH:
````
the verified reader's rules on the text must admit the spelling, on every platform, applied as the reader applies them to the file and to the directory that holds it (strict UTF-8; no colon after the drive and no character below 32; no reserved device name as the final name or as the name of that directory; no backslash, trailing dot or trailing space in the final name) and, on Windows, every component must name in the ordinary namespace what it names in the extended one; it calls no filesystem function and does not say that the file opens (a reserved device name above the directory that holds the file is not looked at off Windows, because the reader opens the directories above it by name).
````
REPLACE:
````
the verified reader's own functions must admit the text of the spelling, on every platform, as the reader applies them to the file and to the directory that holds it; a path with no final name or with a `..` part has none; and, on Windows, every component must name in the ordinary namespace what it names in the extended one; it calls no filesystem function and does not say that the file opens (the contract's D14, D15, L18 and L22).
````

**B13-2** `DECISIONS.md` (BF-953: scope, SP12, residual)

SEARCH:
````
Contract `prompts/bf-953-read-floor-spellings.md` (with Amendments 1 to 4).
````
REPLACE:
````
Contract `prompts/bf-953-read-floor-spellings.md` (with Amendments 1 to 5).
````

SEARCH: the SP12 entry, replaced whole
````
- *SP12 (the verified reader's rules on the text, Amendments 3 and 4).
````
````
it changes the classification, not the listing).
````
REPLACE:
````
- *SP12 (the verified reader's functions on the text, Amendments 3 to 5).* `reader_spelling` calls `validate_read_location` as it is, on the file and on the file's direct parent (the two texts `read_verified_file` gives it), and restates the pinned directory's child-name rule for the final name, on every platform, before SP11's Windows rule. A path with no final name or with a `..` part has no spelling: the reader decides on the candidate its gate returns, which resolves `..`, and a listing's paths have none. A listing follows the verified reader's rules because a `list_files` call cannot know whether the next read is armed (`_workspace_read` is set for the two reader tools only); what the armed reader answers for a refused text is recorded, measured, in the contract's L22, and a repeat of the read counts as a tool defect (BF-948 L17); a name only the plain reader opens is not listed and is still opened by its path (L19). The function calls no filesystem function and says nothing about whether a name opens (L18, L20). Rejected: strict UTF-8 only; the gate on the file alone; deciding from the candidate the gate returns instead of denying `..`; a public function the reader and the lister share (it edits the armed reader, which other callers use; T34, T37 and the probes are the drift guards); asking the loop (AD-1240's surface); answering the reader's lexical refusal as a caller-input error instead (BF-948 L17, the orchestrator's decision: it changes the classification, not the listing).
````

SEARCH:
````
- *Residual.* Recorded limits L1 to L21 of the contract.
````
REPLACE:
````
- *Residual.* Recorded limits L1 to L22 of the contract.
````

## 9. What this does NOT change

- `src/probos/cognitive/swe_harness/tools.py` and `tests/test_bf948_list_files_read_policy.py` (BF-948's M4 edited both by SEARCH, its M5 edited both again after BF-953's M4, and its M6 edits both after BF-953's M5); `ReadFileTool`, `ListFilesTool` and every other consumer.
- The write side: `protected_write_refusal`, `_write_key`, `_same_key`, `_canonical_name`, `_DEVICE_PREFIXES`, and BF-911's T19 parity (`_canonical_name`, `_SHORT_NAME`, `_HFS_IGNORABLE`).
- `protected_read_roots`, `protected_config_files` and `resolve_for_runtime`: the roots they build and how. `permitted_read_roots` and `workspace_exempt_roots` change in one place only (M4, D9; M5, D13): the workspace root is resolved, and kept as composed when it cannot be. `resolve_read_path`'s signature and its return value are unchanged; its reasons gain one (`path cannot be verified against the protected roots`).
- (M5) No signature, return shape, config field, `EventType`, persisted format or gate changes: `reader_spelling` is added to `file_access` and has one caller; `_floor_roots` and `_workspace_root` are private; the decisions that change are those of a floor file root or candidate whose final component carries a stream suffix, a trailing dot or a trailing space (D12, refusals only) and of a configured policy whose workspace root does not resolve (D13, back to the base's list).
- (M6) No signature, return shape, config field, `EventType`, persisted format or gate changes. `reader_spelling`'s body and docstring, `plain_spelling`'s docstring and `ListFilesTool`'s docstring and two comments change. `validate_read_location`, `PinnedDirectory`, `read_verified_file`, `resolve_read_path`, `ReadFileTool`, the fault classification and every other consumer are byte-identical to the head. The decisions that change are those of a listing: a name that the verified reader's rules on the text refuse is not listed (D15), on every platform.
- (M7) No signature, return shape, config field, `EventType`, persisted format or gate changes. `reader_spelling`'s body (one call) and docstring change, and `ListFilesTool`'s docstring (BF-948's M8). `validate_read_location`, `PinnedDirectory`, `read_verified_file`, `resolve_read_path`, `ReadFileTool`, the fault classification and every other consumer are byte-identical to the head. The decisions that change are those of a listing on a POSIX host: a file whose direct parent is a reserved device name or stem is not listed (D15); on Windows nothing changes (0 of 43,380 generated inputs differ).
- (M8) No signature, return shape, config field, `EventType`, persisted format or gate changes. `reader_spelling`'s body (two clauses) and docstring change, and `ListFilesTool`'s docstring (BF-948's M9). `validate_read_location`, `PinnedDirectory`, `read_verified_file`, `resolve_read_path`, `ReadFileTool`, the fault classification and every other consumer are byte-identical to the head. The decisions that change are those of a listing: a root has no spelling, and neither has a path with a `..` part (D15; the lister yields none); on Windows only the root changes (§13f K8: 3 of 716,165 texts).
- `read_verified_file` and `read_bounded_utf8`, `validate_read_location` and the pinned-directory code.
- Config, `EventType`, the tier table, goldens, and any other platform's decisions.

## 10. Mutation rows (campaign of record, run by the Architect on M2's head)

Prefix `SPM` (absent from `prompts/`, `DECISIONS.md` and `PROGRESS.md`: §Absence Verified A4). Line cells hold the source line without its leading indentation. **Campaign of record (2026-11-04).** Base tree: a scratch copy of `728e1fc2` with M1 and M2 applied from this contract's blocks (`git worktree add --detach`, removed afterwards). Files as the working tree held them: `src/probos/security/file_access.py` sha256 `381606bef4795b98adc3ab329666aaf616c91da4f72a8dd51d746fe65979287c` (CRLF working copy; `28ee43378c8bbce975d8f7d0b5eb09c939c468642d548246bba59729beeda675` with LF line ends) and `tests/test_bf953_read_floor_spellings.py` sha256 `cfd2deaa26a96df4f6a68934eeaebab3812412308b9a98a8090a92e009d343da`. Unmutated baseline: 103 passed, 2 skipped. Each row was run alone against the new file, one file at a time, `-n 0`, home-guarded: **all 16 killed, none survived**; the file was restored to the hash above afterwards. **A Builder whose two files match those hashes does not repeat the campaign.** If `file_access.py` differs, rerun every row; if only the test file differs, rerun the rows whose killer changed. The rows were run on Windows (where their branch is reached); on the Linux runner only SPM-1 to SPM-4 and SPM-12 are reachable.

| Id | File (relative to src/probos/) | Line (the exact source line, backticked) | Mutate to (backticked) | Killed by (T-number) |
|---|---|---|---|---|
| SPM-1 | `security/file_access.py` | `if text[:8].upper() == _EXTENDED_UNC.upper():` | `if False:` | T5 |
| SPM-2 | `security/file_access.py` | `return "\\\\" + text[8:]` | `return text[8:]` | T5, T6, T1 |
| SPM-3 | `security/file_access.py` | `if text[:4] in _NAMESPACE_PREFIXES and text[4:5].isascii() and text[4:5].isalpha() and text[5:6] == ":":` | `if text[:4] in _NAMESPACE_PREFIXES and text[4:5].isascii() and True and text[5:6] == ":":` | T5 |
| SPM-4 | `security/file_access.py` | `if text[6:7] in ("", "\\"):` | `if True:` | T5 |
| SPM-5 | `security/file_access.py` | `if not inside and os.name == "nt" and (str(resolved).startswith("\\\\") or str(root).startswith("\\\\")):` | `if False:` | T1, T2, T3, T4, T9, T10 |
| SPM-6 | `security/file_access.py` | the same line | `if not inside and os.name == "nt" and (str(resolved).startswith("\\\\") and str(root).startswith("\\\\")):` | T1, T2, T3, T4, T9, T10 |
| SPM-7 | `security/file_access.py` | `inside = key == root_key or key.is_relative_to(root_key)` | `inside = key == root_key` | T1, T2, T3, T9 |
| SPM-8 | `security/file_access.py` | `if not inside and (key.drive.startswith("\\\\") or root_key.drive.startswith("\\\\")):` | `if False:` | T1, T2, T3, T4, T10 |
| SPM-9 | `security/file_access.py` | the same line | `if not inside:` | T9 |
| SPM-10 | `security/file_access.py` | `inside = root_id is not None and on_disk.holds(root_id)` | `inside = root_id is not None` | T1, T2, T3, T10 |
| SPM-11 | `security/file_access.py` | `found = (_file_identity(part) for part in (self._path, *self._path.parents))` | `found = (_file_identity(part) for part in (self._path,))` | T1, T2, T3, T10 |
| SPM-12 | `security/file_access.py` | `return (info.st_dev, info.st_ino) if info.st_ino else None` | `return (info.st_dev, info.st_ino)` | T7 |
| SPM-13 | `security/file_access.py` | `protect = _longest_match(resolved, protected_roots, on_disk)` | `protect = _longest_match(resolved, (), on_disk)` | T1, T2, T3, T4 |
| SPM-14 | `security/file_access.py` | `if permitted_roots and _longest_match(resolved, permitted_roots, on_disk) is None:` | `if permitted_roots and _longest_match(resolved, permitted_roots, on_disk) is not None:` | T1, T2, T3, T9 |
| SPM-15 | `security/file_access.py` | `return identity in self._found` | `return True` | T1, T2, T3, T10 |
| SPM-16 | `security/file_access.py` | `if text[:8].upper() == _EXTENDED_UNC.upper():` | `if text[:8] == _EXTENDED_UNC:` | T5 |

SPM-1 and SPM-16 are killed by T5 alone: an extended-UNC spelling that is not rewritten is still a share path, which the identity branch decides. SPM-9 is the cost row: it changes no decision, and T9 kills it by counting identity lookups.

**M4's campaign of record (Amendment 1, 2026-11-04).** Rows SPM-5 to SPM-15 quote lines that Amendment 1 removes or rewrites and are superseded by DNY-1 to DNY-32 (update 2 changed the lines of DNY-14 to DNY-16, which now compare the base file and leave the allow-lists to text, and added DNY-22 to DNY-32). SPM-1 to SPM-4 and SPM-16 quote unchanged lines; their killers are unchanged and were not rerun.
- Prefix `DNY` is absent from `prompts/`, `DECISIONS.md` and `PROGRESS.md` (§Absence Verified, Amendment 1, A4).
- **Base tree:** a scratch worktree at `d1aba238d5b1658c772c59d3c6273b5e7899c68c` with B4-1 and B4-2 applied, and BF-948's M5 (P5-1, P5-2) for DNY-19. Files as the working tree held them (CRLF), sha256: `src/probos/security/file_access.py` `77c8efb6c9df5017088875e8aa7f6791c4ab90bd8844cf3c210338b3a55aee9c` (LF line ends: `831c1e2efef6348864eea7d026816baaeb51cc8cc9edabf15b0c0c811ddc1843`); `tests/test_bf953_read_floor_spellings.py` `a6de0442c8772d4692af7837297da249691e17cefa32bbbf2ca60f8576029145` (LF: `917b6ffff865e3bcccca872e9e9bb037b9d32de36efc128d68ffa9fcd40ad7bc`); `src/probos/cognitive/swe_harness/tools.py` `0d90fb5ed76c4a55b64a8dee871662c8b428dcbec2f232e79558ded7b85c9213` (LF: `06a37d7f9f51a737ab665de5020e228038eee39b5a2758225422ced2646a1852`); `tests/test_bf948_list_files_read_policy.py` `39dc71e438a9004e5329c022aae4acc9ee3b46d501d734538c85c29eaf7a19b3` (LF: `f49c98949c0ad9845915cb5226f0b5eb3a98bef4d45bc2bbbb7bd6eba8bb5386`).
- Unmutated baseline: `tests/test_bf953_read_floor_spellings.py` **157 passed, 3 skipped**; `tests/test_bf948_list_files_read_policy.py` **32 passed**. Each row was applied alone, the one named test file run alone (`-n 0`, home-guarded), then the file restored to the hash above: **all 32 killed, none survived.** DNY-25's guard line occurs twice in the file, so that row was run with its three-line context.
- **A Builder whose files match those hashes does not repeat the campaign.** If `file_access.py` differs, rerun every DNY row; if only a test file differs, rerun the rows whose killer is in the changed file. The rows were run on Windows with a second local volume; on the Linux runner only DNY-1 and DNY-2 (T7), DNY-22 to DNY-24 (T18) and, derived and not run, DNY-25 (T22) are reachable.

| Id | File (relative to src/probos/) | Line (the exact source line, backticked) | Mutate to (backticked) | Killed by |
|---|---|---|---|---|
| DNY-1 | `security/file_access.py` | `raise _Unverifiable from exc` | `return None` | T7, T12 |
| DNY-2 | `security/file_access.py` | `if not info.st_ino:` | `if False:` | T7, T12 |
| DNY-3 | `security/file_access.py` | `places.setdefault(identity, len(PureWindowsPath(_namespace_free(str(part))).parts))` | `places[identity] = len(PureWindowsPath(_namespace_free(str(part))).parts)` | T10 |
| DNY-4 | `security/file_access.py` | `self._crossed = frozenset(volumes) - {volumes[-1]} if volumes else frozenset()` | `self._crossed = frozenset(volumes)` | T1, T2, T3, T10, T11 |
| DNY-5 | `security/file_access.py` | `if place is None and on_disk.reaches(identity[0]):` | `if False:` | T10, T11 |
| DNY-6 | `security/file_access.py` | `elif floor and (key.drive.startswith("\\\\") or root_key.drive.startswith("\\\\")):` | `elif (key.drive.startswith("\\\\") or root_key.drive.startswith("\\\\")):` | T1, T2, T3, T10, T11 |
| DNY-7 | `security/file_access.py` | the same line | `elif floor:` | T9 |
| DNY-8 | `security/file_access.py` | `if exempt is None or exempt <= protect:` | `if exempt is None or exempt < protect:` | T13, T17 |
| DNY-9 | `security/file_access.py` | `raise FileAccessDenied(raw, _FLOOR_UNVERIFIED) from None` | `protect = None` | T12 |
| DNY-10 | `security/file_access.py` | `_FLOOR_UNVERIFIED = "path cannot be verified against the protected roots"` | `_FLOOR_UNVERIFIED = "path is protected"` | T12 |
| DNY-11 | `security/file_access.py` | `return composed.resolve()` | `return composed` | T14, T17 |
| DNY-12 | `security/file_access.py` | the same line | `return composed` | T14 |
| DNY-13 | `security/file_access.py` | `return Path(_namespace_free(str(path))) if os.name == "nt" else path` | `return path` | T15 |
| DNY-14 | `security/file_access.py` | `if permitted_roots and _match_position(resolved, permitted_roots) is None:` | `if permitted_roots and _match_position(resolved, permitted_roots, floor=True) is None:` | T1, T2, T3, T11 |
| DNY-15 | `security/file_access.py` | `exempt = _match_position(resolved, exempt_roots)` | `exempt = _match_position(resolved, exempt_roots, floor=True)` | T1, T3 |
| DNY-16 | `security/file_access.py` | `protect = _match_position(base_file, _floor_roots(protected_roots), on_disk, floor=True)` | `protect = _match_position(base_file, _floor_roots(protected_roots), on_disk)` | T1, T2, T3, T4, T11, T12, T13, T17, T19 |
| DNY-17 | `security/file_access.py` | `if identity is None:` (in `_identity_position`, the only occurrence) | `if False:` | T1, T2, T3, T4, T10, T11, T17 |
| DNY-18 | `security/file_access.py` | `volumes.append(identity[0])` | `pass` | T10, T11 |
| DNY-19 | `cognitive/swe_harness/tools.py` | `shown = reader_spelling(match)` (the start of the whole line, which continues with a comment) | `shown = match` | BF-948 T13, T14, T15 |
| DNY-20 | `security/file_access.py` | `at = _identity_position(root, on_disk, len(key.parts))` | `at = _identity_position(root, on_disk, 0)` | T10 |
| DNY-21 | `security/file_access.py` | `if at is not None and (best is None or at > best):` | `if at is not None and (best is None or at < best):` | T10, T17 |
| DNY-22 | `security/file_access.py` | `return name.split(":", 1)[0].rstrip(" .") or name` | `return name.split(":", 1)[0] or name` | T18, T19, T21 |
| DNY-23 | `security/file_access.py` | the same line | `return name.rstrip(" .") or name` | T1, T18, T19, T20, T21 |
| DNY-24 | `security/file_access.py` | the same line | `return name.split(":", 1)[0].rstrip(" .")` | T18 |
| DNY-25 | `security/file_access.py` | in `_base_file`, with its next two lines (the guard line alone occurs twice in the file): `    if os.name != "nt":`, `        return path`, `    base = _base_name(path.name)` | the guard line as `    if os.name == "nt":` | the 11 tests of DNY-26 on Windows (T1, T19, T20, T21); on POSIX T22 (derived, not run) |
| DNY-26 | `security/file_access.py` | `return path.with_name(base) if base != path.name else path` | `return path` | T1, T19, T20, T21 |
| DNY-27 | `security/file_access.py` | `return _canonical_name(path.name) in _PROTECTED_LEAF_KEYS if os.name == "nt" else path.name in PROTECTED_LEAF_NAMES` | `return path.name in PROTECTED_LEAF_NAMES` | T21 |
| DNY-28 | `security/file_access.py` | `base_file = _base_file(resolved)` | `base_file = resolved` | T1, T19, T20, T21 |
| DNY-29 | `security/file_access.py` | `on_disk = _OnDisk(base_file)` | `on_disk = _OnDisk(resolved)` | T19 |
| DNY-30 | `security/file_access.py` | `protect = _match_position(base_file, _floor_roots(protected_roots), on_disk, floor=True)` | `protect = _match_position(resolved, _floor_roots(protected_roots), on_disk, floor=True)` | T1, T19, T20, T21 |
| DNY-31 | `security/file_access.py` | `if _protected_leaf(base_file):` | `if _protected_leaf(resolved):` | T19, T20, T21 |
| DNY-32 | `cognitive/swe_harness/tools.py` | `if shown.is_relative_to(_PROJECT_ROOT) else str(shown)` | `if match.is_relative_to(_PROJECT_ROOT) else str(shown)` | BF-948 T14 |

DNY-7 is the cost row (a drive-letter spelling must read no identity: T9). DNY-17 is killed by a `TypeError` out of `None[0]`, which fails every test that asks about an absent root. Two mutants were considered and dropped as equivalent: using the root's raw count of parts where its namespace-free count is used (T16 shows the counts are equal for every spelling `_namespace_free` rewrites), and changing `whole` to a smaller count only where an exempt root's text names the same path (no spelling reaches it). DNY-19 and DNY-32 are the two display-form rows (BF-948 T13 and T14: DNY-32 moves the relative-to-`src/` test back before the display form).

**M5's campaign of record (Amendment 2, 2026-11-04).** Run by the Architect on M5's head (the scratch tree with B6-2 and B6-1 applied; each row applied to one line, the file run alone with `-n 0` under the home guard, the line restored after). The prefix `R3M-` is absent from `prompts/`, `DECISIONS.md` and `PROGRESS.md` on `34bd9153` (`git grep -n -e "R3M-" -e "R3N-" 34bd9153 -- prompts DECISIONS.md PROGRESS.md` prints nothing, exit 1; the same for `tests` and `src`). The base tree of every row is `34bd9153` plus B6-2 and B6-1, files as the working tree held them (CRLF, `core.autocrlf=true`), sha256: `src/probos/security/file_access.py` `1aca272e59d7268f0adb4717a7e91c0584285de00498acf694c653a20d996e5c`; `tests/test_bf953_read_floor_spellings.py` `07004fd03d6d5d768fb6f3dacc6b986befbb7ffa1fdff9cacaa60106fb2da394`. Rows R3M-1 to R3M-3 and R3M-7 to R3M-14 ran on a test file that differed from this one only in T25's runtime fixture, T5's docstring and one import; R3M-4 to R3M-6, the rows T25 kills, were rerun on this hash. Rerun a row only if a file differs.

| Row | File | Line | Mutant | Killed by (this file alone) |
|---|---|---|---|---|
| R3M-1 | `file_access.py` | `    return [*roots, *(base for root, base in zip(roots, named) if base != root)]` | `    return list(roots)` | 9 failed: T23 (4), T24 (4), T28 |
| R3M-2 | `file_access.py` | the same line | `    return named` | 4 failed: T24 (the root is not kept) |
| R3M-3 | `file_access.py` | `        protect = _match_position(base_file, _floor_roots(protected_roots), on_disk, floor=True)` | `        protect = _match_position(base_file, protected_roots, on_disk, floor=True)` | 5 failed: T23 (4), T28 |
| R3M-4 | `file_access.py` | `        logger.debug("BF-953: workspace root %r does not resolve; it is kept as composed", workspace, exc_info=True)` | `        return None` (the head's list) | 1 failed: T25 |
| R3M-5 | `file_access.py` | the same line | `        raise` | 1 failed: T25 |
| R3M-6 | `file_access.py` | `    return [] if workspace is None else [workspace]` | `    return []` | 28 failed: T25 and every test that needs the workspace exemption |
| R3M-7 | `file_access.py` | `    if any(name != name.rstrip(" .") for name in names):` | `    if False:` | 8 failed: T26's dot and space rows |
| R3M-8 | `file_access.py` | `    if any(part.is_reserved() for part in (ordinary, *ordinary.parents)):` | `    if ordinary.is_reserved():` | 2 failed: T26's reserved-ancestor rows |
| R3M-9 | `file_access.py` | `    names = ordinary.parts[1:] if ordinary.anchor else ordinary.parts` | `    names = ordinary.parts[-1:]` | 4 failed: T26's dot-directory rows |
| R3M-10 | `file_access.py` | `    shown = plain_spelling(path)` | `    shown = path` | 9 failed: T26's prefixed rows |
| R3M-11 | `file_access.py` | `                    at = len(root_key.parts)` | `                    at = len(key.parts)` | 14 failed, among them T27's four text cases; **T16 alone passes (6 passed)** |
| R3M-12 | `file_access.py` | `                    at = _identity_position(root, on_disk, len(key.parts))` | `                    at = len(root.parts)` | 23 failed, among them T27's identity test (alone: 1 failed) |
| R3M-13 | `file_access.py` | `    return resolved` | `    return base_file` | 4 failed: T19 (`:zz`, `:zz:$DATA`), T20, T28 (the path returned) |
| R3M-14 | `file_access.py` | `        return composed.resolve()` | `        return composed` | 2 failed: T14 (the short-path workspace), T17 (device) |

R3M-2 is the row that keeps D12's "add, not replace": a root list reduced to base files passes T23 and fails T24. R3M-11 is the row T16 could not kill. R3M-13 passed on the head's T19, which asserted admission only. BF-948's M6 rows are R3N-1 to R3N-3 (BF-948 §10). **DNY-19 after M6:** the line it mutates is now `shown = reader_spelling(match)  # BF-953: ...` and the mutant `shown = match` is killed by BF-948 T13, T14 and T15 (measured: 4 failed, 30 passed); DNY-32's line is unchanged and is killed by T14 (1 failed, 33 passed).

**M6's campaign of record (Amendment 3, 2026-11-05).** Run by the Architect on M6's head (the scratch tree with B8-2, B8-1 and P8-1 applied; each row applied to one place, the file run alone with `-n 0` under the home guard, the file restored after). The prefix `R4M-` is absent from `prompts/`, `PROGRESS.md`, `DECISIONS.md`, `src` and `tests` at `a0857b08` (`git grep -n -e "R4M-" a0857b08 -- prompts PROGRESS.md DECISIONS.md src tests` prints nothing, exit 1). The base tree of every row is `a0857b08` plus B8-2, B8-1 and P8-1, files as the working tree held them (CRLF, `core.autocrlf=true`), sha256: `src/probos/security/file_access.py` `eb3e4009e79a3378acbc3c52f7989b0f63c72d8fb5b50c21b6b21c32643ece74` (LF: `8e346e85d17f565a411c691031494cf3a17bbce0616e60fd108f8fbec15f7bdd`); `src/probos/cognitive/swe_harness/tools.py` `416cc7f4ff2d51999792f828526f5b94000cd218bb5aad67c946872816be2447` (LF: `1159be812ec975417092edcbd145fa3157beb5273deafe378587b9fc971fb2b9`); `tests/test_bf953_read_floor_spellings.py` `a47f9ed95063de3ee974adf2d3cfc1fc282e18f6193a6e95956bdcd039530fbf` (LF: `6ccfee8bda5ffdbd2768a607540d9d231c951f9e1c93c2225db5a9062c95ff3b`). Rerun a row only if a file differs. R3M-7 to R3M-10 mutate lines of `reader_spelling` whose killers changed with T26 and T29, so their counts are the ones in the second table; R3M-1 to R3M-6 and R3M-11 to R3M-14 mutate lines this amendment does not touch, with killers it does not change, and were not rerun.

| Row | File | Line | Mutant | Killed by (this file alone) |
|---|---|---|---|---|
| R4M-1 | `file_access.py` | the `try` block that calls `validate_read_location(str(shown))` | the block removed | 15 failed: T29 (7), T30 (6), T33 (2) |
| R4M-2 | `file_access.py` | `    except ValueError:  # the reader's own refusal ...` | `    except UnicodeEncodeError:  # ...` | 17 failed: T26 (5), T29 (6), T30 (5), T32 (1) (the gate's other refusals propagate) |
| R4M-3 | `file_access.py` | the same block | `str(shown).encode("utf-8")` under `except UnicodeEncodeError` (the reviewers' fix: strict UTF-8 only) | 9 failed: T29 (4: colon, newline, character below 32 in an ancestor, colon in an ancestor), T30 (5); **T33 passes**: the Windows names it can build are the surrogates |
| R4M-4 | `file_access.py` | the gate block and the final-name rule, before `if os.name != "nt":` | the same lines after the `return shown` | 9 failed: T30 (9); T29 passes on Windows, where the Windows branch is reached |
| R4M-5 | `file_access.py` | `    if "\\" in final or final != final.rstrip(" ."):` and its `return None` | removed | 3 failed: T30 (backslash, trailing dot, trailing space) |
| R4M-6 | `file_access.py` | `    if "\\" in final or final != final.rstrip(" ."):` | `    if "\\" in final:` | 2 failed: T30 (trailing dot, trailing space) |
| R4M-7 | `file_access.py` | the same line | `    if final != final.rstrip(" ."):` | 1 failed: T30 (backslash) |
| R4M-8 | `file_access.py` | `        validate_read_location(str(shown))` | `        validate_read_location(str(path))` (the gate before the prefix is removed) | 10 failed: T26 (6), the listing test of every spelling (3), T33 (1); BF-948's file alone: 3 failed, 31 passed (T13, T14, T15) |
| R4M-9 | `file_access.py` | the same line | `        validate_read_location(str(shown.anchor or "/") + shown.name)` (the final component under the root only) | 6 failed: T29 (3: the ancestor rows), T30 (1), T33 (2) |
| R4M-10 | `file_access.py` | `    final = shown.name` | the line, then `try: os.stat(shown.parent)` / `except OSError: pass` | 1 failed: T32 |
| R4M-11 | `file_access.py` | the final-name line | `... or " " in final or ...` (a name with a space is withheld) | 23 failed: the listing test of every spelling (20), T26 (1), T29 (1), T31 (1) |
| R4M-12 | `file_access.py` | the final-name line | `... or not final.isascii() or ...` (a name that is not ASCII is withheld) | 5 failed: T29 (2), T31 (1), T33 (2) |
| R4M-13 | `file_access.py` (the reader) | `            or name.rstrip(". ") != name` in `PinnedDirectory._leaf` | `            or name.rstrip(". ") != name or name.startswith(".")` (the reader's rule drifts) | 1 failed: T31 (`.hidden`) |

| Row (rerun on M6's head) | Mutant | Killed by |
|---|---|---|
| R3M-7 | `    if False:` for the dot and space rule | 6 failed: T26 (4), T29 (2) (before M6: 8, T26's) |
| R3M-8 | `    if ordinary.is_reserved():` | 3 failed: T26 (2), T29 (1) (before: 2) |
| R3M-9 | `    names = ordinary.parts[-1:]` | 6 failed: T26 (4), T29 (2) (before: 4) |
| R3M-10 | `    shown = path` | 10 failed: T26 (6), the listing test of every spelling (3), T33 (1) (before: 9) |

R4M-3 is the row that separates the chosen design from the reviewers' fix: T29 and T30 fail it, T33 does not. R4M-4 is the row T30 exists for: with the checks after the platform branch, a Windows host passes T29 and fails T30. R4M-13 is the row T31 exists for: it mutates the reader, and the lister's restatement is then wrong. BF-948's R3N rows quote two lines that P8-1's comments change; they are re-pointed in G1-3.

**M7's campaign of record (Amendment 4, 2026-11-05).** Run by the Architect on M7's head (the scratch tree with B10-2, B10-1 and P9-1 applied; each row applied to one place, the file run alone with `-n 0` under the home guard, the file restored after). The prefix `R5M-` is absent from `prompts/`, `PROGRESS.md`, `DECISIONS.md`, `src` and `tests` at `8c83093b` (`git grep -n -e "R5M-" 8c83093b -- prompts PROGRESS.md DECISIONS.md src tests` prints nothing, exit 1). The base tree of every row is `8c83093b` plus B10-2, B10-1 and P9-1, files as the working tree held them (CRLF, `core.autocrlf=true`), sha256: `src/probos/security/file_access.py` `9591d96d4c325677a1f21d9ddecfd3a4f58cf2bc7bc67d6feb4ff9911c2431ac` (LF: `c646bc026a6222838c6235c464fce3208a6d3c2aa4c03fde4df59f1a7f056171`); `src/probos/cognitive/swe_harness/tools.py` `206ee94a0d85df331dd8e85b5573e756fcf6b9fbf460e13c469305fc897c68dd` (LF: `d74970f8078c6af8210889c9b0def688cf027dc3efb884181ac09265d1d51f9d`); `tests/test_bf953_read_floor_spellings.py` `bb095d8071b343321dfa99a1466df4abc6e2d5c91ae3961e0b96c044fef9ae1c` (LF: `87fa5706f1286ffec7217cf6bfdcc3d8002e89fc0a25553a3026cb74d20c35b3`). Rerun a row only if a file differs. **This campaign reran every R4M, R3M-7 to R3M-10 and R3N row on the new hashes, because `file_access.py` changed; the counts below replace the M6 campaign's.**

| Row | File | Line | Mutant | Killed by (this file alone) | The orchestrator's probe (holes / misses: Windows; POSIX shape) |
|---|---|---|---|---|---|
| R5M-1 | `file_access.py` | `        validate_read_location(str(shown.parent))  # the directory read_verified_file pins ...` | the line removed (the head's behaviour) | 3 failed: T30 (2), T34 (1: the POSIX shape) | 0/0; 31,941/0 |
| R5M-2 | the same | the same | `validate_read_location(str(shown.parent.parent))` (the grandparent) | 4 failed: T30 (3), T34 (1) | 0/0; 18,900/18,837 |
| R5M-3 | the same | the same | `validate_read_location(str(path.parent))` (before the prefix is removed) | 10 failed: T26 (6), the listing test of every spelling (3), T33 (1) | 0/0; 0/0 (no prefixed text in its pools) |
| R5M-4 | the same | the same | the call under `if os.name == "nt":` | 3 failed: T30 (2), T34 (1) | 0/0; 31,941/0 |
| R5M-5 | the same | the same | the call, then the same call on `shown.parent.parent` (over-withheld) | 2 failed: T30 (1: a reserved name above the direct parent), T34 (1) | 0/0; 0/18,837 |
| R5M-6 | `file_access.py` | the final-name rule's `return None` | the rule, then `return None` for a direct parent that ends in a dot or a space (over-withheld) | 3 failed: T30 (2), T34 (1) | 0/0; 0/7,098 |
| R5M-7 | `file_access.py` | `        validate_read_location(str(shown))` | the line removed | 13 failed: T29 (4), T30 (5), T33 (2), T34 (2) | 5,856/0 (then the probe's own assertion stops it); not reached |
| R5M-8 | the same line of the parent call | the same | `validate_read_location(shown.parent.name)` (a relative text) | 48 failed: every test that gives a spelling | not run |
| R5M-9 | `file_access.py` | the final-name rule's `return None` | the rule, then `return None` for a final name that starts like a device name (over-withheld) | 3 failed: T26 (2), T29 (1) | 0/0; 0/0 (no such name in its pools) |
| R5M-T1 | the test file | `def _reader_admits(text: str, shape: str, *, parent_gate: bool = True)` | the default `False` (the oracle skips the parent's gate) | 2 failed: T34 (both shapes: the premise that the parent's gate refuses texts) | n/a |
| R5M-T2 | the test file | `("con", True), ("aux.py", True), ("dot.", True), ("space ", True),` | the first two directories removed | 2 failed: T34 (the same premise) | n/a |
| R5M-T3 | the test file | `        directory._leaf(parsed.name)` | `pass` | 2 failed: T34 (the child-name rule is the oracle's) | n/a |

| Row (rerun on M7's head) | Mutant | Killed by |
|---|---|---|
| R4M-1 | the gate's `try` block replaced by `pass` | 19 failed: T29 (7), T30 (8), T33 (2), T34 (2) (M6: 15) |
| R4M-2 | `except UnicodeEncodeError:` | 25 failed: T26 (6), T29 (8), T30 (7), T32 (1), T34 (2), T35 (1) (M6: 17) |
| R4M-3 | `str(shown).encode("utf-8")` only (the reviewers' fix of round 4) | 13 failed: T29 (4), T30 (7), T34 (2) (M6: 9) |
| R4M-4 | the gate block and the final-name rule after the platform return | 12 failed: T30 (11), T34 (1) (M6: 9) |
| R4M-5 | the final-name rule removed | 4 failed: T30 (3), T34 (1) (M6: 3) |
| R4M-6 | the rule is the backslash only | 3 failed: T30 (2), T34 (1) (M6: 2) |
| R4M-7 | the rule is the trailing dot and space only | 2 failed: T30 (1), T34 (1) (M6: 1) |
| R4M-8 | the file's gate given `str(path)` | 10 failed: T26 (6), the listing test of every spelling (3), T33 (1); BF-948's file alone: 3 failed, 31 passed (T13, T14, T15) |
| **R4M-9** | the file's gate given the anchor and the final name only | **246 passed: survives, and is equivalent** from M7: the parent's call and this call together cover every character of the file's text and the reserved test of the final component in both; the probe finds 0/0 on 292,464 texts per shape. In M6 it was killed by 6 tests |
| R4M-10 | `os.stat(shown.parent)` added | 1 failed: T32 |
| R4M-11 | a name with a space inside withheld | 23 failed: the listing test of every spelling (20), T26, T29, T31 |
| R4M-12 | a non-ASCII name withheld | 5 failed: T29 (2), T31, T33 (2) |
| R4M-13 | `PinnedDirectory._leaf` refuses a leading dot (the reader drifts) | 1 failed: T31 |
| R3M-7 | the dot and space rule off | 6 failed: T26 (4), T29 (2) |
| R3M-8 | the reserved rule tests the final part only | 3 failed: T26, T29, T35 (before: T26, T29) |
| R3M-9 | the dot and space rule tests the final component only | 6 failed: T26 (4), T29 (2) |
| R3M-10 | the prefix is not removed | 10 failed: T26 (6), the listing test of every spelling (3), T33 |
| R3N-1 | a match with no spelling is listed as it stands (`tools.py`) | BF-948's file alone: 2 failed (T15) |
| R3N-2 | one such name fails the listing | 2 failed (T15) |
| R3N-3 | the base is asked, not each match | 9 failed |

R5M-3, R5M-9 and R3M-8 show why T26, T29, T33 and T35 stay beside T34: the probe's pools have no prefixed text, no name that only starts like a device name, and the chain rule above the direct parent is a Windows rule its oracle excuses. R4M-9 is the only survivor and it is an equivalent mutant, not a gap. R5M-7 and R4M-5 are the rows the probe's holes show most plainly (5,856 and 19,776).

**M8's campaign of record (Amendment 5, 2026-11-05).** Run by the Architect on M8's head (a scratch tree at `bd67126a` holding B12-2, B12-1 and P10-1 as hand edits whose files equal the blocks' result: Amendment 5's §8; each row applied to one place, the file run alone with `-n 0` under the home guard, the file restored after and its hash re-verified). The prefix `R6M-` is absent from `prompts/`, `PROGRESS.md`, `DECISIONS.md`, `src` and `tests` at `bd67126a` (§13f, Absence Verified). Files as the working tree held them (CRLF), with the LF-normalised hash in brackets: `src/probos/security/file_access.py` sha256 `3f5afe6b8b935ffc611895e46863851116aaae0f4dc3965ec3761a1130bb9472` (`599e9245e94391bff2eee9603fda821799e767d428e23cb39b97308661f1b159`), `src/probos/cognitive/swe_harness/tools.py` `c6b4c7c82b66da5d892af6334f300cd3289718af4779a9f9463cd44248a1828c` (`95dc259a4c46757b95c7fb0d6e8a1902afd9c57b586d5c9a05ba336f7afc4303`), `tests/test_bf953_read_floor_spellings.py` `e18e1fef1117df4ed60aba59587e06cb55531b62ed471ea43036a5762c7dbfc3` (`407fe0c2f655ef7992cd3437413220893715ff918a5df0ffd7b96c88966ee3b1`). Unmutated baseline: 260 passed, 4 skipped (BF-953's file); 34 passed (BF-948's file). **This is the campaign of record for the candidate: a Builder whose three files match those hashes does not repeat it.** If `file_access.py` differs, rerun every row; if only the test file differs, rerun the rows whose killer changed; if `tools.py` differs by more than its docstring, rerun R3N-1 to R3N-3. The probe column is `probe_lexical_oracle3.py`'s count for the tree's function with the mutant in place, per shape: the holes (a text the function lists and the reader's text path refuses), and the unexcused misses (a text the reader's text path admits and the function withholds, that is neither D14's same-file rule on Windows nor a text that is not its own normal form); the harness is `files\r7x-probes\mutate.py` (the rows' old and new texts).

| Row | File | Mutant | Killed by (this file alone) | Probe: Windows; POSIX shape |
|---|---|---|---|---|
| R6M-0 | `file_access.py` | both new clauses removed (the head's function) | 9 failed: T30 (4), T34 (2), T36 (2), T38 (1) | Windows 3 holes (the roots), 0 unexcused misses; POSIX 1 hole (the root) and 2,774 `..` holes, 0 unexcused misses |
| R6M-1 | the same | the empty-name clause removed | 6 failed: T30 (1), T34 (2), T36 (2), T38 (1) | Windows 3 holes (the roots); POSIX 1 hole (the root); 0 unexcused misses |
| R6M-2 | the same | the empty-name clause after the platform return | 2 failed: T30 (1), T34 (1: the POSIX shape) | Windows 0 holes; POSIX 1 hole (the root); 0 unexcused misses |
| R6M-3 | the same | over-withheld: `if not shown.name or not shown.parent.name` (a file directly under a root) | 2 failed: T34 (2) | Windows 0 holes, 14 unexcused misses; POSIX 0 holes, 14 unexcused misses |
| R6M-4 | the same | the `..` clause removed | 4 failed: T30 (3), T34 (1: the POSIX shape) | Windows 0 holes; POSIX 2,774 `..` holes; 0 unexcused misses |
| R6M-5 | the same | the `..` clause tests the final name only | 4 failed: T30 (3), T34 (1) | Windows 0 holes; POSIX 2,774 `..` holes; 0 unexcused misses |
| R6M-6 | the same | the `..` clause after the platform return | 4 failed: T30 (3), T34 (1) | Windows 0 holes; POSIX 2,774 `..` holes; 0 unexcused misses |
| R6M-7 | the same | over-withheld: a part with two dots inside is refused | 4 failed: T26 (1), T31 (1), T34 (2) | Windows 0 holes, 8,134 unexcused misses; POSIX 0 holes, 26,024 unexcused misses |
| R6M-8 | the same | over-withheld: a part that starts with a dot is refused | 3 failed: T31 (1), T34 (2) | Windows 0 holes, 8,134 unexcused misses; POSIX 0 holes, 26,024 unexcused misses |
| R6M-9 | `file_access.py` (the reader) | `PinnedDirectory._leaf` gives the gate no text | 2 failed: T37 (2) | the function is not changed: 0 holes, 0 unexcused misses on both |
| R6M-10 | the same | `read_verified_file` gives the gate the grandparent too | 3 failed: T35 (1), T37 (2) | the same |
| R6M-11 | the same | `PinnedDirectory.open` gives the gate no text | 3 failed: T35 (1), T37 (2) | the same |
| R6M-T1 | the test file | T34's oracle does not normalise by default | 2 failed: T34 (2) | n/a |
| R6M-T2 | the test file | T34's corpus has no `..` directory | 2 failed: T34 (2: the premises on normalising) | n/a |
| R6M-T3 | the test file | T34's corpus has no root rows | 2 failed: T34 (2: the premise that the corpus holds a path with no final name) | n/a |
| R6M-T4 | the test file | T34's child verdicts are all "admitted" | 2 failed: T34 (2) | n/a |

R6M-0 is the red run of G9: the head's function against the new tests. R6M-9 to R6M-11 are the rows T37 exists for: they change the reader, and no other test of this file but T35 (for two of them) sees it. R6M-7 and R6M-8 are killed by T34 and by T31 (and R6M-7 by T26); T34's corpus holds `x..y` and `.hidden` as directories and as final names. R6M-5 is subsumed by the final-name rule on a `..` final name, so it fails the same rows as R6M-4 (the non-final `..` parts). R6M-T1 to R6M-T4 drift T34's own parts. Two rows of the first design are not in the table because they survived and were removed: an oracle call on the candidate's own gate (its refusals are implied by the parent's gate and the child verdict: the line was deleted), and a `..` final name in T34's corpus (the final-name rule already refuses it, and T29 and T30 carry those rows).

| Row (rerun on M8's head) | Mutant | Killed by |
|---|---|---|
| R5M-1 | the parent gate is not called | 3 failed: T30 (2), T34 (1) |
| R5M-2 | the parent gate is given the grandparent | 4 failed: T30 (3), T34 (1) |
| R5M-3 | the parent gate is given the parent before the prefix is removed | 10 failed: T3 (3), T26 (6), T33 (1) |
| R5M-4 | the parent gate on Windows only | 3 failed: T30 (2), T34 (1) |
| R5M-5 | over-withheld: the grandparent gated as well | 2 failed: T30 (1), T34 (1) |
| R5M-6 | over-withheld: a direct parent ending in a dot or a space | 3 failed: T30 (2), T34 (1) |
| R5M-7 | the file gate is not called | 13 failed: T29 (4), T30 (5), T33 (2), T34 (2) |
| R5M-8 | the parent gate is given the final name only | 48 failed: every test that gives a spelling |
| R5M-9 | over-withheld: a final name that starts like a device name | 3 failed: T26 (2), T29 (1) |
| R5M-T1 | the oracle skips the parent step by default (`*, parent_gate: bool = True,` to `False`: re-pointed to the new signature) | 2 failed: T34 (2) |
| R5M-T2 | the corpus holds no reserved directory | 2 failed: T34 (2) |
| R5M-T3 | the oracle does not apply the child-name verdict (`    return not refused_names[name]` to `    return True`: re-pointed, the oracle no longer calls `_leaf`) | 2 failed: T34 (2) |
| R4M-1 | the gate's `try` block replaced by `pass` | 19 failed: T29 (7), T30 (8), T33 (2), T34 (2) (M7: 19) |
| R4M-2 | `except UnicodeEncodeError:` | 26 failed: T26 (6), T29 (8), T30 (8), T32 (1), T34 (2), T35 (1) (M7: 25) |
| R4M-3 | `str(shown).encode("utf-8")` only | 13 failed: T29 (4), T30 (7), T34 (2) (M7: 13) |
| R4M-4 | the gate, the two M8 clauses and the final-name rule after the platform return (re-pointed: the two clauses sit between the gate and the final-name rule) | 18 failed: T30 (17), T34 (1) (M7: 12) |
| R4M-5 | the final-name rule removed | 4 failed: T30 (3), T34 (1) |
| R4M-6 | the rule is the backslash only | 3 failed: T30 (2), T34 (1) |
| R4M-7 | the rule is the trailing dot and space only | 2 failed: T30 (1), T34 (1) |
| R4M-8 | the file's gate given `str(path)` | 10 failed: T3 (3), T26 (6), T33 (1); BF-948's file alone: 3 failed, 31 passed (T13, T14, T15) |
| **R4M-9** | the file's gate given the anchor and the final name only | **260 passed: survives, and is equivalent** (as from M7: the parent's call and this call together cover every character of the file's text and the reserved test of the final component in both) |
| R4M-10 | `os.stat(shown.parent)` added | 1 failed: T32 |
| R4M-11 | a name with a space inside withheld | 23 failed: T3 (20), T26, T29, T31 |
| R4M-12 | a non-ASCII name withheld | 5 failed: T29 (2), T31, T33 (2) |
| R4M-13 | `PinnedDirectory._leaf` refuses a leading dot (the reader drifts) | 3 failed: T31 (1), T34 (2) (M7: 1) |
| R3M-7 | the dot and space rule off | 6 failed: T26 (4), T29 (2) |
| R3M-8 | the reserved rule tests the final part only | 3 failed: T26, T29, T35 |
| R3M-9 | the dot and space rule tests the final component only | 6 failed: T26 (4), T29 (2) |
| R3M-10 | the prefix is not removed | 10 failed: T3 (3), T26 (6), T33 |
| R3N-1 | a match with no spelling is listed as it stands (`tools.py`) | BF-948's file alone: 2 failed (T15) |
| R3N-2 | one such name fails the listing | 2 failed (T15) |
| R3N-3 | the base is asked, not each match | 9 failed |

R4M-9 stays the only survivor and it is an equivalent mutant, not a gap. The rows whose counts moved are R4M-2, R4M-4 and R4M-13 (T34 now kills the drift of the reader's child-name rule too, through its real pinned directory); R5M-T1, R5M-T3 and R4M-4 were re-pointed; every other row has the count it had on M7's head.

## 11. Recorded limits

- **L1.** Identity is `(volume, file index)` as `os.stat` reports it. Two files that report the same pair, such as a file and the same file on a bit-identical copy of its volume, are one identity to this function. Only share and device spellings are decided by identity, for the floor only, on Windows.
- **L2.** A floor root that is not on disk has no identity and contains nothing by identity: it is matched by text only. The prefix forms and the spellings of the final component (a trailing dot or space, a stream suffix, another case: the base file is compared, L14) are covered by the text comparison; a share spelling of the local drive naming a **file root** that does not exist yet is admitted while its ordinary spelling is refused (measured, T21 leaves it out). A missing candidate beneath an existing floor directory is not covered by this limit: its existing ancestors are read, so its share spelling is refused where the base admitted it (§16 item 6).
- **L3.** For a share or device spelling, a hard link of a file root (a config file) is the same file by identity and is decided like it. A drive-letter spelling of a hard link is decided by text, as before (the limit `protected_config_files` already records).
- **L4.** A share or device spelling costs one `os.stat` per floor root compared and one per part of its own chain, once per call (measured here: 14 for a 9-part path against 3 floor roots, one of them absent; the head made 15); an exempt or a permitted root costs none. Over a network share each is a round trip. A drive-letter path costs none (T9).
- **L5.** Each decision is by path and identity at the moment of the check (BF-758's limit). A link retargeted afterwards changes only what a name points to.
- **L6.** Other platforms: no identity layer. A hard link or a bind mount there is decided by path, as before; no spelling family exists there that `Path.resolve()` leaves apart.
- **L7.** A spelling whose drive does not start with two backslashes and that `Path.resolve()` leaves apart from the roots is not known; this contract names none, and T1 enumerates 20.
- **L8.** The write side's own coverage (BF-911) is not changed here; T4 pins that the two sides agree for the loaded config file in these 20 spellings.
- **L9.** A share or device spelling is admitted by an exempt or a permitted root only if its text, without a namespace prefix, names the root. Where the ordinary spelling is admitted by one of those roots the share spelling is refused: with the root's own reason for a permitted root (as on the base), with the floor's reason for an exempt root (admitted on the base and on the head). A root configured as a share path is matched by text against a share-spelled candidate only. A legitimate alias of a confined path that this refuses (the share spelling of a path the ordinary spelling reads, through a link the share's text does not name) is the safe direction: the ordinary spelling reads it.
- **L10.** The floor knows the parts of the candidate's own chain and the volumes it reaches. A share whose root is below a floor root, named by its own share name, has no part in its chain that is the floor root and is on the root's volume, so it is decided as the base decided it. Hard links: L3.
- **L11.** A floor root, or a part of a share or device spelling's own chain, that the system will not answer for (a failed or refused read other than "no such file", or a file index of zero) refuses the call. A legitimate remote path with a part whose attributes the caller may not read is refused with the bounded reason. A part the system reports as absent is skipped. Only the class of the cause is logged.
- **L12.** The volume rule works on the volume the system reports for each part. A share or device spelling whose chain reaches a floor root's volume through a link is refused, though the file may be elsewhere on that volume.
- **L13.** A path a caller spells with a namespace prefix, which the policy admits, is rejected by the armed reader's lexical check (`read_file failed: invalid path`), as it was for any admitted path outside the floor on the base; before BF-953 a permitted root refused it first. `list_files` no longer lists such a spelling (D10). See BF-948 L17.
- **L14.** (Second reviewer's R3 and R6.) On Windows the final component of a floor file root and of a credential file name is compared by the file it names: the text from the first colon, then trailing dots and spaces, are dropped (`_base_name`), and the credential names are compared in the write side's canonical form (case-folded). In the extended namespace a name that ends in a dot or a space can be a different file than its base; it is refused when its base is a floor file root or a credential name, the safe direction. Only the final component is rewritten, and only for the floor's file roots and the credential names: a directory component is compared as `resolve()` leaves it. On another platform the names are compared as they are (T22).
- **L15.** (Second reviewer's R3.) The repair decides the name of a stream; it does not list, remove or create streams. **Reach:** a named stream of a floor file root or of a credential name is readable only if it already exists on that file (a stream is created by a write, and the write side refuses the same names: T20). A stream of a neighbour is read as named.
- **L16.** (Review round 3, A1.) A floor root spelled in the extended namespace with a trailing dot or space (a configured directory or file whose own name ends so) also refuses the directory or file its base names: `_floor_roots` adds the base after the root and keeps the root, so a floor is never narrowed. The over-refusal is the neighbour of such a root, and only a configuration that names a floor in that spelling reaches it. A directory root a system resolves (an ordinary spelling) never has such a final component.
- **L17.** (Review round 3, A2.) A configured read policy composes empty, which every consumer reads as "no limit", when every configured root is unusable (a text with a NUL, a failed resolution) and the workspace root cannot be composed at all (a relative workspace root whose platform data directory needs a home directory the system cannot name, or a value that is not a path). On the base the same two failures give the same list. **Reach:** the workspace root's own composition has to fail as well as every configured root; each unusable root is logged once (`BF-758: configured read_roots entry ... ignoring it`). Not repaired here: a fail-closed form needs a list entry that matches nothing, in a list whose emptiness means "none configured" (`resolve_for_runtime`, `CodeSearchAgent`, the copilot adapter, repository instructions, `ListFilesTool` and `reads_confined` read it so): a change of that list's contract.
- **L18.** (Review round 3, A3 and B1; widened by rounds 4 and 5; reduced by round 6.) What a listing says, and what it does not promise. `reader_spelling` is a rule on the text (D15): it says that the verified reader's own functions admit the text of the file and, on Windows, that D14's rule holds. It does not say that the file opens. A listing does not decide: the read policy (the lister applies it to each match and the next read applies it again); the two steps of `read_verified_file` that read the disk, `resolve_read_path` of the candidate with the comparison of its result to the candidate (`source path aliases another file`), and the pinned directory's verification of each directory and of the file (§13f K5); the tool's own two steps, the run's scope check (`read.scope.validate`) and the routing of a path with a `.tool-results` component to the workspace-result reader (`ReadFileTool.invoke`, §13f K5); a path longer than the system's ordinary limit on a host without long-path support (not measured: `LongPathsEnabled` is 1 on the host that measured this contract); a directory (a match of the pattern, which T33's expected listing includes); and a file changed after the listing. A later change of the reader's location gate reaches the lister through the two calls (D15); a later change of the child-name rule reaches it through T31, T34 and T36; a later change of *which* texts the reader gives its gate is recorded by T37, which then fails, and `reader_spelling`, T34's oracle and the probes are then audited by hand (L21).
- **L19.** (Review round 4, F1, and the orchestrator's reading of the gate; reduced by round 6.) A name that only the plain reader opens is not listed: the listing follows the verified reader's rules because a `list_files` call cannot know whether the next read of a name is armed (D15). Which names the function gives no spelling is the rows of T29 and T30 and the corpus of T34 (the ids are in §13f K9), and what the armed reader answers for each class is L22. T33 measures the plain reader's side on Windows: it opens a name with an unpaired surrogate, which the verified reader's gate refuses and the listing leaves out. **Reach:** none of the 5,889 names this repository tracks (`git ls-tree -r --name-only bd67126a`) is given no spelling (§13f K6). **The price:** a name left out is not listed though the plain reader opens it by its path; in the armed lane the reader refuses it whatever the listing does. Whether the reader's lexical refusal is answered as a caller-input error (BF-948 L17) is the orchestrator's decision; it would make the refusal visible without hiding a name.
- **L20.** (Review round 4, F2; replaced by round 6.) `reader_spelling` calls no filesystem function (T32; the audit of §13f K7: 8 inputs, none counted). It builds strings and path objects for each match and calls the reader's location gate twice. Counted by §13f K7 (Windows, one process, `probe_cost3.py`, interleaved; the function before Amendment 4 / after Amendment 4 / after Amendment 5), for each of its three fixtures (their paths hold 3, 9 and 13 parts by `len(Path.parts)`; K7 prints their labels): gate calls 1 / 2 / 2 and `pathlib` constructor calls 11 / 18 / 18, 17 / 24 / 24 and 21 / 28 / 28. So Amendment 4 added one gate call and seven constructor calls a match, and Amendment 5 adds neither. The times K7 prints are one run: they vary between runs and with the depth of the path, and they are not a bound; in that run the policy check each match already gets (`resolve_read_path` on an existing file, which touches the filesystem) took 207.9 µs.
- **L21.** (Review round 5, A; reduced by round 6.) The reader gives its location gate three texts for a file (the call list in §13f K2, by execution on real files on this host, and T37 on any platform): the file as it was given; then the direct parent of the candidate the gate returned (`PinnedDirectory.open`, whose first call is the gate); then the candidate (`_leaf`). It gives the gate no directory above the direct parent: it opens those by name. So `reader_spelling` calls the gate on the file and on the file's direct parent and on nothing above. Two consequences. (1) Off Windows the rule D14 applies above the direct parent is not a rule of the reader's text path, and the listing does not apply it there (T29, T30, T35; derived from the code, since no POSIX host was available: T35's first POSIX run is `ubuntu-latest`). (2) On Windows D14's rule is wider than the reader's text path: a name under `con\sub\` is left out although the verified reader reads it (measured on this host, Windows 10.0.26300, with real directories made through the extended namespace: `con\sub\g.txt` is read and `reader_spelling` gives `None`). That is deliberate and deny-only: in the extended namespace such a component can name another object than its ordinary spelling does, and a listing's spelling is the ordinary one (D10, D14); it costs a name a listing could have offered and never offers one the reader refuses (T34's Windows shape).
- **L22.** (Review round 6, B6-1.) What the armed reader answers for a text it refuses. Measured on this host (Windows 10.0.26300, home-guarded) by the command and output of §13f K1, through `read_verified_file` on a text and through `PinnedDirectory.read_bytes` on a child name. The table lists what the reader raises; what `ReadFileTool` does with it is not recorded here (BF-948 L17 records the classification question). The table records that run; it is not a rule, and no sentence of this contract says that a class is answered by one message only.

| Class of text, as the probe built it | The armed reader answers |
|---|---|
| NUL in the text | `ValueError: invalid path` |
| the prefixes `\\?\` and `\\.\` | `ValueError: invalid path` |
| a drive-relative text (`C:g.txt`) | `ValueError: invalid path` |
| a colon after the drive | `ValueError: invalid path` |
| a control character in the final name, and in an ancestor | `ValueError: invalid path` |
| a reserved device name as the final name, and as the direct parent | `ValueError: invalid path` |
| a lone surrogate in the final name, and in an ancestor | `UnicodeEncodeError: 'utf-8' codec can't encode character '\ud800' in position N: surrogates not allowed` |
| a rooted text with no drive | `ValueError: device or drive-relative path` |
| a relative text | `ValueError: absolute read authority required` |
| the drive root, given to `read_verified_file` (no final name) | `FileAccessDenied: invalid child name` |
| a trailing dot, and a trailing space, in the final name, given to `read_verified_file` | `FileNotFoundError` (`os.path.abspath` drops them before `_leaf` sees the name, so the text names a neighbour) |
| a child name given to `read_bytes`: empty; `.`; `..`; with `/`; with `\`; with `:`; ending in a dot; ending in a space | `FileAccessDenied: invalid child name` |
| a child name given to `read_bytes`: a reserved device name; a control character | `ValueError: invalid path` |
| a child name given to `read_bytes`: a lone surrogate | the `UnicodeEncodeError` above |

Notes. (a) A colon is answered `invalid path` in a text given to `read_verified_file` (the gate's rule) and `invalid child name` as a child name given to `read_bytes` (`_leaf`'s rule runs first): which message answers a class depends on which function sees it first. (b) A trailing dot or space in the final name reaches no refusal through `read_verified_file` on Windows; the function withholds such a name on every platform (D14, D15). (c) The probe was not run on a POSIX host (none was available). The gate has one explicit branch on the platform: it refuses a rooted text with no drive when `os.name` is `nt` (§13f K2); it also builds a `Path` and calls `os.path.abspath`, which are the platform's.

## 12. For the Captain

You decide nothing for this build; Amendment 1 raises two items for the orchestrator, neither blocking: a BF for review finding 6, and whether the armed reader's lexical rejection of a prefix a caller types itself should be answered as a caller-input error (BF-948 L16, L17). It adds no config field, no escape and no tier change. Whether to check past use of these spellings on the live vessel is your call; this contract gives no steps for it. It lands in the BF-948 PR as its own commits, before BF-948's M4 (the Architect's order for that PR, §4 of BF-948's amended contract).

Amendment 2 raises two items for the orchestrator, neither blocking: whether round four reviews the delta (this amendment's §0 recommends it: no signature, return shape, config field, event, persisted format or gate changes) or the whole candidate again, and whether to accept L17 (a configured policy that composes empty when the workspace root cannot be composed at all, as on the base) or to make that list fail closed in its own BF.

Amendment 3 raises two items for the orchestrator, neither blocking: whether round 5 reviews the delta or, under the standing order's "adds behaviour the findings did not ask for" clause, the whole candidate (this amendment's §0.2 recommends the delta), and whether the armed reader's lexical refusal is answered as a caller-input error (BF-948 L17), which D15 neither needs nor excludes.

Amendment 4 raises two items for the orchestrator, neither blocking: that BF-948 L17 goes to its own BF now that the lister cannot offer a name the reader refuses (that amendment's §3 D; what the reader answers is L22), and that round 6 reviews the delta with two reviewers (its §10). T35 is the first test of this contract to cross the seam natively on POSIX; its first POSIX run is the CI run.

Amendment 5 raises three items for the orchestrator, none blocking: that T37 and R6M-9 to R6M-11 are droppable if the smaller delta is preferred (Amendment 5's §2.3 names the two clauses of L18 and L21 that mention T37); that `probe_lexical_oracle2.py`'s own `LEX2_EXPECT=clean` stops on the POSIX shape's `..` texts by design (§13f K8) and `probe_lexical_oracle3.py`'s `LEX3_EXPECT=clean` is the assertion for the repaired tree; and that BF-948 L17 still goes to its own BF. Round 7 reviews the delta with two reviewers and nothing wider (§16 items 33 to 38; Amendment 5's §0 gives the stopping rule).

## 13. Verified Against Codebase (2026-11-04, on `728e1fc2`)

```
git rev-parse HEAD  (D:\ProbOS-worktrees\bf948-ca0ca20b)
  728e1fc2d2f49fd04584adf2a41d1dfa68befcb5
git diff --stat 9649df656fd3fbe846435b6b67f79e0ae96e3642 728e1fc2
  prompts/bf-948-list-files-read-policy.md | 430 +++...   (one file; 422 insertions, 8 deletions)
blobs equal at both heads: src/probos/security/file_access.py 004ea3991b, tests/test_bf948_list_files_read_policy.py d2282b897c,
  PROGRESS.md 2e7d32cc02, DECISIONS.md 09e596951a, src/probos/cognitive/swe_harness/tools.py fadc8fb71c

grep -n "^def _depth\|^def _longest_match\|^def resolve_read_path\|candidate.resolve()" src/probos/security/file_access.py
  88:def _depth(root: Path) -> int:
  92:def _longest_match(resolved: Path, roots: Iterable[Path]) -> Path | None:
  105:def resolve_read_path(
  129:        resolved = candidate.resolve()
grep -n "_longest_match(" src/probos/security/file_access.py
  151:    protect = _longest_match(resolved, protected_roots)
  153:        exempt = _longest_match(resolved, exempt_roots)
  160:    if permitted_roots and _longest_match(resolved, permitted_roots) is None:
grep -n "^from pathlib\|^import os\|^import ntpath\|PureWindowsPath" src/probos/security/file_access.py
  45:import os
  54:from pathlib import Path, PureWindowsPath
grep -n "_DEVICE_PREFIXES\|def _write_key\|def _same_key\|samestat" src/probos/security/file_access.py
  252:_DEVICE_PREFIXES = ("//?/", "//./")
  266:def _write_key(path_text: str) -> tuple[str, ...]:
  284:def _same_key(candidate: tuple[str, ...], protected: tuple[str, ...]) -> bool:
  367:        if os.path.samestat(current, config_stat):
grep -n "resolved != candidate\|resolve_read_path(" src/probos/security/file_access.py
  869:    resolved = resolve_read_path(
  871:    if resolved != candidate:
  933:        resolved = resolve_read_path(
  937:        if resolved != candidate or not resolved.is_relative_to(authorized_root):
grep -n "^_OUTSIDE\|^_PROTECTED\|^def _scene\|^def _runtime\|^async def _list" tests/test_bf948_list_files_read_policy.py
  28:_OUTSIDE = "list_files refused: path is outside every readable root"
  29:_PROTECTED = "list_files refused: path is protected: the runtime's data directory or a config file"
  44:def _scene(tmp_path: Path) -> _Scene:
  61:def _runtime(scene: _Scene, *, read_roots: list[Path]) -> SimpleNamespace:
  72:async def _list(
grep -n "read_file refused\|list_files refused" src/probos/cognitive/swe_harness/tools.py
  (ReadFileTool answers  f"read_file refused: {exc}"; ListFilesTool answers  f"list_files refused: {exc}")
grep -n "requires-python" pyproject.toml
  requires-python = ">=3.12"
```

Consumer search (§1 item 4), run on the committed head: `rg -n "resolve_read_path|resolve_for_runtime|protected_read_roots|permitted_read_roots|protected_config_files|workspace_exempt_roots|_longest_match|_ReadFloor" src` gave 85 hits in `agents/code_search.py` (19), `agents/directory_list.py` (2), `agents/file_reader.py` (2), `agents/file_search.py` (2), `agent_work_runner.py` (5), `cognitive/copilot_adapter.py` (6), `repository_instructions.py` (6), `security/file_access.py` (22), `tools/effect_tiers.py` (1, a comment), `cognitive/swe_harness/tools.py` (20). The same names in `tests` hit 7 files: `test_ad1200_instruction_file_access.py` (2), `test_ad1200_repository_instructions.py` (3), `test_ad1316_real_effect_routes.py` (1), `test_bf758_file_read_confinement.py` (20), `test_bf908_floor_and_children.py` (31), `test_bf911_protected_config_write_refusal.py` (3), `test_bf948_list_files_read_policy.py` (1); `scripts` none.

Measured on this host (Windows, Python 3.12.13), as premises of the design, with a throw-away fixture: for a file opened by each of the ordinary, extended-prefix and `localhost` share spellings, `os.stat` gives one `(st_dev, st_ino)`, equal to the ordinary spelling's, for the forward-slash, extended, `localhost`, `127.0.0.1`, computer-name, extended-UNC and device spellings; `Path.resolve()` keeps `\\?\C:\…`, `\\localhost\C$\…` and `\\?\UNC\localhost\C$\…` and returns `C:\…` for the device and forward-slash spellings; for the share-spelled handle `GetFinalPathNameByHandleW` returns the share path (DOS, NONE), the redirector's device path (NT) and fails (GUID).

Built and run on a scratch copy of `728e1fc2` (`git worktree add --detach`, removed afterwards), by the Architect, to settle the gate counts. Nothing was written in `D:\ProbOS` or in the BF-948 worktree; every test file ran alone, `-n 0`, through the home-guard runner.

```
fence-aware applier, labels B1-1 (new file, 352 lines), B2-1 .. B2-11, B3-1, B3-2:   DRY RUN OK: 14 blocks (1 new file, 13 pairs) in 4 files
plain "next **B / ## / ### line" rule: B1-1 and B2-1 .. B2-11 parse; B3-1 and B3-2 do not (their fences hold such lines), as §7 says
G1  M1 applied:           tests/test_bf953_read_floor_spellings.py   42 passed, 2 skipped, 61 xfailed        (exit 0)
    --runxfail:           every xfail fails for its marked reason (AttributeError for the missing helpers; AssertionError naming the spelling)
G2  M2 applied:           tests/test_bf953_read_floor_spellings.py   103 passed, 2 skipped                   (exit 0)
    consumers on M2:      test_bf758_file_read_confinement 24 passed, 1 skipped | test_bf908_floor_and_children 39 passed, 1 skipped
                          test_bf911_protected_config_write_refusal 119 passed | test_bf948_list_files_read_policy 17 passed
                          test_ad1200_instruction_file_access 40 passed | test_ad1200_repository_instructions 98 passed
                          test_ad1316_real_effect_routes 67 passed, 2 skipped
    check_architecture_principles.py --check:  architecture fitness check passed (srp-size=92, layer-import=0, db-connect=30, unowned-task=13)
G3  M3 applied:           gen_ad_ledger.py wrote docs/development/open-ads-report.md and ad-ledger-snapshot.json (14 + 6 changed lines);
                          --check: AD/BF ledger is current; tests/test_ad1184_ad_ledger.py 33 passed
                          (the test fails until the ledger is regenerated: it passed on the base, failed on M1 to M3 before the regeneration, passed after it)
BF-948 M4 on the BF-953 head (M1 to M3 applied): apply_labelled.py prompts/bf-948-list-files-read-policy.md, labels P4-1 .. P4-7:   DRY RUN OK: 8 pairs in 5 files
```

## Absence Verified (2026-11-04, on `728e1fc2`)

```
A1 CLAIM: nothing outside file_access.py calls _longest_match
   RUN:   rg -n "_longest_match" src tests scripts
   FOUND: security/file_access.py:92 (def), :151, :153, :160 (the three calls)
   HOLDS: yes; the new third parameter is optional

A2 CLAIM: none of the new names exists anywhere on the head
   RUN:   git grep -n -E "_namespace_free|class _OnDisk|_file_identity|_NAMESPACE_PREFIXES|_EXTENDED_UNC" 728e1fc2 -- src tests scripts
   FOUND: (no hits; exit 1)
   HOLDS: yes. Near misses, by name only: `def _identity` in execution/workspace.py:127 (another module) and `_same_identity` in file_access.py:516 (compares two stat results for the pinned reader; no hashable key, no zero-index rule), so the new helper is named _file_identity and is separate (§15)

A3 CLAIM: no read-side code already reduces the namespace prefix of a path for containment
   RUN:   rg -n -F '\\?\' src/probos --glob '*.py'   (and the same pattern with two backslashes)
   FOUND: cognitive/swe_harness/tools.py:229-230 (a final path from a handle, for one verified source read), agents/code_search.py:414 (a docstring), security/file_access.py (the write side's _DEVICE_PREFIXES, :252)
   HOLDS: yes; none is a containment test

A4 CLAIM: the mutation prefix SPM is unused
   RUN:   rg -n -w "SPM-[0-9]+" prompts DECISIONS.md PROGRESS.md
   FOUND: (no hits; exit 1)
   HOLDS: yes

A5 CLAIM: BF-953 is held only by #1752, and BF-954 is free
   RUN:   gh issue list --state all --limit 4000 --json number,title,state (1,507 issues, filtered on BF-9[4-9][0-9]); git log --all --format=%s filtered the same way; Get-ChildItem prompts -Filter bf-95*; Select-String docs/development/roadmap.md,PROGRESS.md,DECISIONS.md -Pattern 'BF-95[3-9]'
   FOUND: issue titles carrying a BF-94x or BF-95x number: BF-940, 942, 943, 944, 945, 946, 947, 948, 949, 950, 952 (#1751, OPEN) and BF-953 (#1752, OPEN); commit subjects: BF-941, 946, 947, 948, 949, 951; prompts/bf-95*: none; trackers: none
   HOLDS: yes

A6 CLAIM: no existing test pins the read floor's decision for an extended-prefix or share spelling (so no test pins the defect)
   RUN:   rg -n "\\\\\\\\\?|UNC|localhost|127\.0\.0\.1" tests/test_bf758_file_read_confinement.py tests/test_bf908_floor_and_children.py tests/test_ad1200_instruction_file_access.py tests/test_ad1200_repository_instructions.py
   FOUND: (no hits). The only prefix and UNC pins are BF-911's pure write-key tables (tests/test_bf911_protected_config_write_refusal.py:190-193)
   HOLDS: yes
```

## 13a. Verified for Amendment 1 (2026-11-04, on `d1aba238`)

```
git grep -n "_depth(" d1aba238 -- src/probos/security/file_access.py
  :88: def _depth(root: Path) -> int:
  :164: if inside and (best is None or _depth(root) > _depth(best)):
  :227: if exempt is None or _depth(exempt) <= _depth(protect):
git grep -n -e "^def workspace_exempt_roots" -e "^def permitted_read_roots" -e "^def _file_identity" -e "^class _OnDisk" -e "^def _longest_match" -e "^def resolve_read_path" d1aba238 -- src/probos/security/file_access.py
  :116 _file_identity   :128 _OnDisk   :142 _longest_match   :171 resolve_read_path   :237 permitted_read_roots   :460 workspace_exempt_roots
git grep -n "_resolve_workspace_root(workspace)" d1aba238 -- src/probos/security/file_access.py
  :263: roots.append(_resolve_workspace_root(workspace))
  :467: return [_resolve_workspace_root(workspace)]
git grep -n -e "workspace_exempt_roots" -e "permitted_read_roots" d1aba238 -- src
  agent_work_runner.py:617, :714; agents/code_search.py:341-342; cognitive/copilot_adapter.py:111-112; cognitive/swe_harness/tools.py:316, :340-341, :566-567, :951-952; repository_instructions.py:63-64; security/file_access.py:480-481 (resolve_for_runtime)
```

Probes (scratch worktree at the head, home-guarded; `files/evidence-amend1-before.txt`, `-extra-before`, `-devices-head`, `-after`, `-extra-after`, `-devices-after`, `-samevol-after`; update 2: `evidence-amend2-new-head`, `-new-amended`, `-new-after`, `-t953-first`, `-t953-second`, `-t948-first`, `-dny-1` to `-dny-32`, `-g-*`): the before/after table of the amendment's §1. Tests (one file per command, `-n 0`): `tests/test_bf953_read_floor_spellings.py` **157 passed, 3 skipped** (160 tests; red on the head code: 57 failed, 100 passed, 3 skipped), `tests/test_bf948_list_files_read_policy.py` **32 passed** (red on the head code: 2 failed, 30 passed). The seven consumer files of G2 and the 14-file list of BF-948's G4, each alone: `ad1356_s1_input_errors` 14, `ad1356_replay_approval_tiers` 5, `ad1205_fault_observer` 91, `ad1205_fault_paths` 231, `ad1169_fault_reports` 29, `ad1257_defect_follows_failure` 100, `ad1279_fault_finds_its_trace` 29, `ad1164_continue_or_ask` 89, `ad1189_deferred_tool_schemas` 74, `ad1156_plan_execute_mode` 87, `ad1240_tool_result_delivery` 513 passed 2 skipped, `bf758_file_read_confinement` 24 passed 1 skipped, `ad544_native_tools` 20, `bf948_list_files_read_policy` 32: **1338 passed, 3 skipped** for the 14 (1336 before BF-948's M5 added two tests); `bf908_floor_and_children` 39 passed 1 skipped, `bf911_protected_config_write_refusal` 119, `ad1200_instruction_file_access` 40, `ad1200_repository_instructions` 98, `ad1316_real_effect_routes` 67 passed 2 skipped: all unchanged. `check_architecture_principles.py --check`: `architecture fitness check passed (srp-size=92, layer-import=0, db-connect=30, unowned-task=13)`.

**Not run / not reproduced.** The broad gate; the Linux runner (counts derived: BF-953 file 49 passed, 111 skipped, T22 running only there; BF-948 file unchanged); the reviewer's `AgentWorkRunner` chain with the fault store (BF-948's T13 is the production-rig replacement, red on the head at the listing's spelling); the reviewer's "subdirectory share" precedence variant and the second reviewer's "15 against 8" equal-depth case (§1 of the amendment); a genuinely remote share; review finding 6.

## Absence Verified (Amendment 1, 2026-11-04, on `d1aba238`)

```
A1  CLAIM: `_depth` has no caller outside `file_access.py`'s two decision sites, so removing it breaks nothing
    RUN:   git grep -n "_depth(" d1aba238 -- src tests scripts
    FOUND: file_access.py:88 (the definition), :164, :227; the other hits are `_max_depth`, `queue_depth` and `_check_attention_queue_depth`, different names
    HOLDS: yes
A2  CLAIM: nothing outside `file_access.py` and T10 calls `_longest_match`, `_OnDisk` or `.holds(`
    RUN:   git grep -n -e "_longest_match" -e "\.holds(" -e "_OnDisk" d1aba238 -- src scripts tests
    FOUND: file_access.py:128, :142, :153, :163, :201, :222-232; tests/test_bf953_read_floor_spellings.py:349-352 (T10, rewritten by B4-2)
    HOLDS: yes
A3  CLAIM: no test or source pins the strings the amendment changes (`path cannot be verified ...` is new; the other reasons are unchanged)
    RUN:   git grep -n "cannot be verified against" d1aba238 -- src tests
    FOUND: (none)
    HOLDS: yes
A4  CLAIM: the mutation prefix DNY is absent from prompts, DECISIONS.md, PROGRESS.md and their era files
    RUN:   Select-String -Path prompts\*.md,prompts\*\*.md,prompts\*\*\*.md,DECISIONS.md,PROGRESS.md,decisions-era-*.md,progress-era-*.md -Pattern '\bDNY-\d'
    FOUND: 0 hits (`SPM-\d` finds 18, for comparison)
    HOLDS: yes
A5  CLAIM: no other consumer needs the workspace root unresolved
    RUN:   the consumer list above, then the 14-file and 7-file test runs of §13a
    FOUND: every consumer passes the root lists on to `resolve_read_path`, `read_verified_file` or a `is_relative_to` test against resolved paths; `tools.py:316-322` keeps the lexical root beside the resolved one
    HOLDS: yes, by the runs (0 failed)
```

## 13b. Verified for Amendment 2 (2026-11-04, on `34bd9153`)

Run on a scratch worktree at `34bd9153` with M5 and M6 applied; each block is the command and what it printed (line numbers are that tree's).

```
rg -n "^def (_base_file|_floor_roots|plain_spelling|reader_spelling|_workspace_root|permitted_read_roots|workspace_exempt_roots|protected_config_files|protected_read_roots|resolve_read_path)" src/probos/security/file_access.py
  131:def _base_file(path: Path) -> Path:
  143:def _floor_roots(roots: Sequence[Path]) -> list[Path]:
  180:def plain_spelling(path: Path) -> Path:
  191:def reader_spelling(path: Path) -> Path | None:
  296:def resolve_read_path(
  377:def _workspace_root(runtime: Any) -> Path | None:
  400:def permitted_read_roots(runtime: Any) -> list[Path]:
  427:def protected_read_roots(runtime: Any) -> list[Path]:
  439:def protected_config_files(runtime: Any, *, fail_closed: bool = False) -> list[Path]:
  618:def workspace_exempt_roots(runtime: Any) -> list[Path]:

rg -n "permitted_read_roots\(|workspace_exempt_roots\(" src --glob "!security/file_access.py"
  agent_work_runner.py:617 reads_confined=bool(permitted_read_roots(self._runtime)), :714
  agents/code_search.py:341-342; repository_instructions.py:63-64; cognitive/copilot_adapter.py:111-112
  cognitive/swe_harness/tools.py:317, :341-342, :570-571, :958-959

rg -n "is_reserved" src/probos/security/file_access.py
  208:    if any(part.is_reserved() for part in (ordinary, *ordinary.parents)):      (reader_spelling)
  707:        or PureWindowsPath(raw).is_reserved()                                  (validate_read_location)

rg -n "reads_confined" src
  agent_work_runner.py:617; tools/effect_tiers.py:47-61 (READ_POLICY_TOOL_IDS are routine only while reads_confined)

reg query "HKLM\SYSTEM\CurrentControlSet\Control\FileSystem" /v LongPathsEnabled
  LongPathsEnabled    REG_DWORD    0x1
```

## Absence Verified (Amendment 2, 2026-11-04, on `34bd9153`)

```
CLAIM: nothing in src calls reader_spelling except ListFilesTool, and plain_spelling has no caller but reader_spelling after M6
RUN:   rg -n "reader_spelling\(|plain_spelling\(" src
FOUND: file_access.py:180 (def plain_spelling), :191 (def reader_spelling), :201 (the call in reader_spelling); tools.py:588 (reader_spelling(match))
HOLDS: yes (T15 of this contract calls plain_spelling directly)

CLAIM: the floor roots are compared in one place, so _floor_roots is applied once
RUN:   rg -n "protected_roots" src/probos/security/file_access.py
FOUND: :299 (resolve_read_path's parameter), :356 (the comparison, through _floor_roots), :630 (resolve_for_runtime passes the list), :1087 and :1093 (read_verified_file passes it), :1129 and :1157 (read_bounded_utf8 passes it)
HOLDS: yes

CLAIM: an empty permitted-roots list is read as "no limit" by every consumer, so L17's list is "no limit" everywhere
RUN:   rg -n "permitted_read_roots\(" src
FOUND: `or None` at tools.py:342, :571, :959, code_search.py:342, copilot_adapter.py:112, file_access.py:632; `tuple(...) or None` at repository_instructions.py:64; `bool(...)` at agent_work_runner.py:617
HOLDS: yes (seven call sites in five modules, and reads_confined)

CLAIM: the prefixes R3M- and R3N- are unused
RUN:   git grep -n -e "R3M-" -e "R3N-" 34bd9153 -- prompts DECISIONS.md PROGRESS.md tests src
FOUND: nothing (exit 1)
HOLDS: yes
```

What Amendment 2 ran: §7 of the amendment file (red and green counts, the seven consumer files, the 14-file G4 list, the 17 mutation rows, the architecture check, the ledger test). **Not run:** the Linux runner (counts derived), a remote share, Python 3.13, a host without long-path support, the broad gate, the live vessel.

## 13d. Verified for Amendment 3 (2026-11-05, on `a0857b08`)

```
git grep -n -e "def reader_spelling" -e "def validate_read_location" -e "def _leaf" -e 'raw.encode("utf-8", errors="strict")' -e 'or name.rstrip(". ") != name' -e "candidate = validate_read_location(path)" -e "return directory.read_bytes(candidate.name)" a0857b08 -- src/probos/security/file_access.py
  191: def reader_spelling(path: Path) -> Path | None:
  690: def validate_read_location(raw: str | Path, *, relative_base: Path | None = None) -> Path:
  699:     raw.encode("utf-8", errors="strict")
  910:     def _leaf(self, name: str) -> Path:
  915:             or name.rstrip(". ") != name
  1091:     candidate = validate_read_location(path)
  1099:         return directory.read_bytes(candidate.name)
git grep -n -e "def _read_context" -e "read = _read_context(context)" -e "text = target.read_text" -e "shown = reader_spelling(match)" a0857b08 -- src/probos/cognitive/swe_harness/tools.py
  292: def _read_context(context: dict[str, Any] | None) -> WorkspaceReadContext | None:
  462:             read = _read_context(context)
  486:             text = target.read_text(encoding="utf-8")
  588:                 shown = reader_spelling(match)  # BF-953: the spelling ``read_file`` opens, as the policy admitted it
  811:             read = _read_context(context)
  833:             text = target.read_text(encoding="utf-8")
git grep -n -e "_READER_TOOLS: Mapping" -e "reader_tool = _READER_TOOLS.get" a0857b08 -- src/probos/cognitive/swe_harness/result_offload.py
  76: _READER_TOOLS: Mapping[str, tuple[str, type]] = {
  305:         reader_tool = _READER_TOOLS.get(tool_id) if type(tool_id) is str else None
git grep -n -e 'invocation_context\["_workspace_read"\] = read_context' a0857b08 -- src/probos/cognitive/swe_harness/agentic_loop.py
  2642:                 invocation_context["_workspace_read"] = read_context
```

## Absence Verified (Amendment 3, 2026-11-05, on `a0857b08`)

```
CLAIM: nothing but ListFilesTool calls reader_spelling in src
RUN:   git grep -n -e "reader_spelling(" a0857b08 -- src
FOUND: file_access.py:191 (the definition), tools.py:588 (ListFilesTool)
HOLDS: yes

CLAIM: no tool call context other than a worked read_file or codebase_read_source carries _workspace_read
RUN:   git grep -n -e "_workspace_read" a0857b08 -- src
FOUND: agentic_loop.py:2642 (the one place it is set); tools.py:293 and :498 (the two places it is read); result_offload.py:76 holds exactly read_file and codebase_read_source
HOLDS: yes (list_files is not in _READER_TOOLS, so invocation_context gives it None: result_offload.py:305)

CLAIM: none of the names this repository tracks is in a class the new rules refuse
RUN:   git ls-tree -r --name-only a0857b08 | <a colon, a character below 32, a backslash, a reserved device stem (CON PRN AUX NUL COM1-9 LPT1-9) as the stem of the final name, or a path component that ends in a dot or a space>
FOUND: 5,889 names, 0 in a refused class
HOLDS: yes

CLAIM: R4M-, E1-, G1-, B8-, B9-, P8-, T29 to T33, D15, SP12 and L19 and L20 (BF-953) are unused at the head
RUN:   git grep -n -I -E -e "R4M-" -e "\*\*(E1|G1|B8|B9|P8)-[0-9]+\*\*" -e "\bT(29|3[0-3])\b" -e "\*\*D15" -e "\bSP12\b" -e "^- \*\*L(19|20)\." a0857b08 -- prompts/bf-953-read-floor-spellings.md prompts/bf-948-list-files-read-policy.md PROGRESS.md DECISIONS.md src tests/test_bf953_read_floor_spellings.py tests/test_bf948_list_files_read_policy.py
FOUND: nothing (exit 1) for each pattern run on its own at the head
HOLDS: yes
```

## 13e. Verified for Amendment 4 (2026-11-05, on `8c83093b`)

```
git grep -n -e "def reader_spelling" -e "def validate_read_location" -e "def _leaf" -e 'raw.encode("utf-8", errors="strict")' -e "path = validate_read_location(path)" -e "candidate = validate_read_location(path)" -e "pin_directory(candidate.parent)" -e "return directory.read_bytes(candidate.name)" -e "def pin_directory" -e "def read_verified_file" 8c83093b -- src/probos/security/file_access.py
  191: def reader_spelling(path: Path) -> Path | None:
  706: def validate_read_location(raw: str | Path, *, relative_base: Path | None = None) -> Path:
  715:     raw.encode("utf-8", errors="strict")
  926:     def _leaf(self, name: str) -> Path:
  1050:         path = validate_read_location(path)
  1086: def pin_directory(
  1102: def read_verified_file(
  1107:     candidate = validate_read_location(path)
  1114:     with pin_directory(candidate.parent) as directory:
  1115:         return directory.read_bytes(candidate.name)
git grep -n -e "shown = reader_spelling(match)" -e "read.scope.validate(str(target), read.directive)" -e "private_candidate = is_workspace_result_path(target)" 8c83093b -- src/probos/cognitive/swe_harness/tools.py
  336:     read.scope.validate(str(target), read.directive)
  472:                 read.scope.validate(str(target), read.directive)
  475:             private_candidate = is_workspace_result_path(target) or is_workspace_result_path(Path(str(path)))
  594:                 shown = reader_spelling(match)  # BF-953: the spelling the verified reader's rules on the text admit
  825:                 read.scope.validate(str(target), read.directive)
  826:             private_candidate = is_workspace_result_path(target) or is_workspace_result_path(Path(str(path)))
git grep -n -e "def is_workspace_result_path" -e "RESULT_DIRECTORY =" 8c83093b -- src/probos/execution/workspace_results.py
  27: RESULT_DIRECTORY = ".tool-results"
  428: def is_workspace_result_path(path: Path) -> bool:
git grep -n -e "read_verified_file(" 8c83093b -- src
  src/probos/cognitive/copilot_adapter.py:108:        snapshot = read_verified_file(
  src/probos/cognitive/swe_harness/tools.py:339:        snapshot = read_verified_file(
  src/probos/cognitive/swe_harness/tools.py:961:            snapshot = read_verified_file(
  src/probos/security/file_access.py:1102:def read_verified_file(
```

## Absence Verified (Amendment 4, 2026-11-05, on `8c83093b`)

```
CLAIM: no function the armed reader runs, other than the three rules, takes the file's or a directory's text and refuses it, and no directory above the direct parent is given to the gate
RUN:   probe_gate_trace2.py (sys.setprofile over every call into file_access.py during the real read_verified_file on <root>\sub\g.txt, <root>\con\sub\g.txt and <root>\con\g.txt; files\evidence-r5-gate-trace.txt)
FOUND: the calls taking a text are validate_read_location (file; then the direct parent inside open; then the file again inside _leaf), resolve_read_path (the policy), pin_directory, open, read_bytes, _leaf and _open_windows_instruction_path (a handle per ancestor, no gate); every other function that ran takes a stat result, a handle or a decided name; no gate call names <root>\con for <root>\con\sub\g.txt
HOLDS: yes (this host, Windows; the POSIX branches differ only in how a descriptor is opened and verified: file_access.py 1066 to 1073 in open, 949 to 953 in read_bytes, 905 to 909 in verify, and one more refusal of a rooted path with no drive at 727 in the gate)

CLAIM: nothing but ListFilesTool calls reader_spelling in src
RUN:   git grep -n -e "reader_spelling(" 8c83093b -- src
FOUND: file_access.py:191 (the definition), tools.py:594 (ListFilesTool)
HOLDS: yes

CLAIM: none of the names this repository tracks is given no spelling by the function, and none has a reserved direct parent
RUN:   probe_reach.py (git ls-tree -r --name-only HEAD, each name under /w, os.name set to posix for the call) ; the direct parent tested with PureWindowsPath(...).parent.is_reserved()
FOUND: 5,889 names, 0 given no spelling, 0 with a reserved direct parent
HOLDS: yes

CLAIM: R5M-, E2-, G2-, B10-, B11-, P9-, T34 and T35 (the BF-953 and BF-948 contracts and test files), L21, and the headings 7.7 (BF-953) and 7.8 (both contracts) are unused at the head
RUN:   git grep -n -I -E -e "R5M-" -e "\*\*(E2|G2|B10|B11|P9)-[0-9]+\*\*" 8c83093b -- prompts/bf-953-read-floor-spellings.md prompts/bf-948-list-files-read-policy.md PROGRESS.md DECISIONS.md src tests ; the same for -e "\bT3[45]\b" over the two contracts and the two test files, -e "^- \*\*L21\." over the two contracts, -e "\bL21\b" over the two contracts, PROGRESS.md, src and the BF-953 test file, -e "^### 7\.8 M" over the two contracts and -e "^### 7\.7 M" over the BF-953 contract
FOUND: nothing (exit 1) for each
HOLDS: yes (T34 and T35 occur in other test files for other items, and "L21" in DECISIONS.md:633 for another item)
```

## 13f. Verified for Amendment 5 (2026-11-05, on `bd67126a`)

**K1. What the armed reader answers, per class (L22's table).** The command is the probe below, run with the temporary directory in a scratch location; each text names nothing that exists, so a refusal is the reader's own, before any file is touched. Part A is `read_verified_file` on a text; Part B is `PinnedDirectory.read_bytes` on a child name.

```
import re
import tempfile
from pathlib import Path

from probos.security import file_access as fa

root = Path(tempfile.mkdtemp(prefix="taxonomy-")).resolve()
(root / "dir").mkdir()


def show(text: str) -> str:
    text = text.replace(str(root), "<tmp>")
    text = re.sub(r"position \d+", "position N", text)
    return text.encode("ascii", "backslashreplace").decode("ascii")


rows_a = [
    ("NUL in the text", str(root / "a\x00b.txt")),
    ("namespace prefix \\\\?\\", "\\\\?\\" + str(root / "dir" / "g.txt")),
    ("device prefix \\\\.\\", "\\\\.\\" + str(root / "dir" / "g.txt")),
    ("drive-relative C:g.txt", "C:g.txt"),
    ("colon after the drive", str(root / "dir" / "run-12:30.txt")),
    ("control char in the final name", str(root / "dir" / "a\x01b.txt")),
    ("control char in an ancestor", str(root / "d\x01r" / "g.txt")),
    ("reserved device name as the final name", str(root / "dir" / "aux.py")),
    ("reserved device name as the direct parent", str(root / "con" / "g.txt")),
    ("lone surrogate in the final name", str(root / "dir" / "a\ud800b.txt")),
    ("lone surrogate in an ancestor", str(root / "d\ud800" / "g.txt")),
    ("rooted path with no drive", "\\Windows\\g.txt"),
    ("relative text", "dir\\g.txt"),
    ("trailing dot in the final name", str(root / "dir" / "g.")),
    ("trailing space in the final name", str(root / "dir" / "g ")),
    ("an empty final name (the drive root)", root.anchor),
    ("a name that is absent (reference)", str(root / "dir" / "absent.txt")),
]
print("PART A: read_verified_file(text)")
for label, text in rows_a:
    try:
        fa.read_verified_file(Path(text), protected_roots=[], exempt_roots=[], permitted_roots=None)
        outcome = "READ OK"
    except BaseException as exc:  # the class matters as much as the message
        outcome = f"{type(exc).__name__}: [WinError {exc.winerror}] {exc.strerror}" if isinstance(exc, OSError) else f"{type(exc).__name__}: {exc}"
    print(f"  {label:<44} -> {show(outcome)[:140]}")

names_b = ["", ".", "..", "a/b", "a\\b", "a:b", "g.", "g ", "con", "aux.py", "a\x01b", "a\ud800b", "absent.txt"]
print("PART B: PinnedDirectory(<tmp>/dir).read_bytes(name)")
with fa.pin_directory(root / "dir") as directory:
    for name in names_b:
        try:
            directory.read_bytes(name)
            outcome = "READ OK"
        except BaseException as exc:
            reason = getattr(exc, "reason", None)
            if isinstance(exc, OSError):
                outcome = f"{type(exc).__name__}: [WinError {exc.winerror}] {exc.strerror}"
            else:
                outcome = f"{type(exc).__name__}: {reason if isinstance(exc, fa.FileAccessDenied) else exc}"
        print(f"  {name!r:<14} -> {show(outcome)[:120]}")
print("DONE")
```

Output (Windows 10.0.26300; the same on a second run):

```
PART A: read_verified_file(text)
  NUL in the text                              -> ValueError: invalid path
  namespace prefix \\?\                        -> ValueError: invalid path
  device prefix \\.\                           -> ValueError: invalid path
  drive-relative C:g.txt                       -> ValueError: invalid path
  colon after the drive                        -> ValueError: invalid path
  control char in the final name               -> ValueError: invalid path
  control char in an ancestor                  -> ValueError: invalid path
  reserved device name as the final name       -> ValueError: invalid path
  reserved device name as the direct parent    -> ValueError: invalid path
  lone surrogate in the final name             -> UnicodeEncodeError: 'utf-8' codec can't encode character '\ud800' in position N: surrogates not allowed
  lone surrogate in an ancestor                -> UnicodeEncodeError: 'utf-8' codec can't encode character '\ud800' in position N: surrogates not allowed
  rooted path with no drive                    -> ValueError: device or drive-relative path
  relative text                                -> ValueError: absolute read authority required
  trailing dot in the final name               -> FileNotFoundError: [WinError 2] The system cannot find the file specified
  trailing space in the final name             -> FileNotFoundError: [WinError 2] The system cannot find the file specified
  an empty final name (the drive root)         -> FileAccessDenied: invalid child name
  a name that is absent (reference)            -> FileNotFoundError: [WinError 2] The system cannot find the file specified
PART B: PinnedDirectory(<tmp>/dir).read_bytes(name)
  ''             -> FileAccessDenied: invalid child name
  '.'            -> FileAccessDenied: invalid child name
  '..'           -> FileAccessDenied: invalid child name
  'a/b'          -> FileAccessDenied: invalid child name
  'a\\b'         -> FileAccessDenied: invalid child name
  'a:b'          -> FileAccessDenied: invalid child name
  'g.'           -> FileAccessDenied: invalid child name
  'g '           -> FileAccessDenied: invalid child name
  'con'          -> ValueError: invalid path
  'aux.py'       -> ValueError: invalid path
  'a\x01b'       -> ValueError: invalid path
  'a\ud800b'     -> UnicodeEncodeError: 'utf-8' codec can't encode character '\ud800' in position N: surrogates not allowed
  'absent.txt'   -> FileNotFoundError: [WinError 2] The system cannot find the file specified
DONE
```

**K2. The texts the reader gives its location gate, and the gate's rules.** `probe_gate_trace2.py` (`sys.setprofile` over every call into `file_access.py` during the real `read_verified_file` of three real files made through the extended namespace: `<root>\sub\g.txt`, `<root>\con\sub\g.txt`, `<root>\con\g.txt`), run on the repaired tree (the reader is byte-identical to the head), trimmed to the calls that take a text:

```
=== read_verified_file(<root>\sub\g.txt) -> read
      validate_read_location  raw='<root>\\sub\\g.txt'
      resolve_read_path  raw='<root>\\sub\\g.txt'
      pin_directory  path='<root>\\sub'
        open  path='<root>\\sub'
          validate_read_location  raw='<root>\\sub'
          _open_windows_instruction_path  (one call per directory of the chain, no gate call; the direct parent last)
      read_bytes  name='g.txt'
        _leaf  name='g.txt'
          validate_read_location  raw='<root>\\sub\\g.txt'
        _open_windows_instruction_path  path='<root>\\sub\\g.txt'
=== read_verified_file(<root>\con\sub\g.txt) -> read      (the gate is given the file and <root>\con\sub, never <root>\con)
=== read_verified_file(<root>\con\g.txt) -> ValueError: invalid path
      validate_read_location  raw='<root>\\con\\g.txt'
      resolve_read_path  raw='<root>\\con\\g.txt'
      pin_directory  path='<root>\\con'
        open  path='<root>\\con'
          validate_read_location  raw='<root>\\con'          (raises; no _open_windows_instruction_path call: nothing was opened)
```

The gate's own statements are `validate_read_location` at `file_access.py:710` to `:737` of the head: an empty text or a NUL; `raw.encode("utf-8", errors="strict")` (719); the prefixes `\\?\` and `\\.\`; a drive with no separator after it; a `:` in the tail; a character below 32; `PureWindowsPath(raw).is_reserved()`; on `nt` a rooted text with no drive (731, the gate's one explicit branch on the platform); a non-absolute text; then `Path(os.path.abspath(candidate))`. T37 records the sequence of texts from the real reader on any platform. **Not measured:** a POSIX host; a path longer than the ordinary limit on a host without long-path support.

**K3. The reader's child-name rule and the function's restatement.** `PinnedDirectory._leaf` at `file_access.py:930` to `:938` of the head:

```
type(name) is not str or not name or name in (".", "..")
or "/" in name or "\\" in name or ":" in name
or name.rstrip(". ") != name
    -> raise FileAccessDenied("", "invalid child name")
return validate_read_location(self._paths[-1] / name)
```

and the function's statements (`Select-String -Path src\probos\security\file_access.py -Pattern 'if not shown.name|in shown.parts|final = shown.name|final.rstrip'` on the repaired tree): `if not shown.name:` (the empty name); `if ".." in shown.parts:` (the candidate rule, round 6's F3); `final = shown.name`; `if "\\" in final or final != final.rstrip(" ."):` (a backslash; a trailing dot or space, which also covers `.` and `..`). Not restated, and why: the final name of a path object is never `.` and never holds a separator (`PurePosixPath('/a/.').name` is `'a'`, `PurePosixPath('/a//b').name` is `'b'`, `PurePosixPath('/a/b/..').name` is `'..'`, `PurePosixPath('/').name` is `''`, `PurePosixPath('/a/b\\c').name` is `'b\\c'` (a POSIX name keeps a backslash, which the restated condition refuses), and the same for `PureWindowsPath`, measured by one `python -c` over those texts); a colon is refused by the gate on every platform (T29's and T30's rows; K1 shows `invalid path` for it in a text); `type(name) is not str` cannot hold for a path object's `.name`.

**K4. D14's Windows rule.** The three statements of `reader_spelling` after the platform return (`Select-String -Path src\probos\security\file_access.py -Pattern 'ordinary = PureWindowsPath|rstrip\(" \."\) for name|is_reserved\(\) for part'`): every component after the anchor that ends in a dot or a space, and any part that `PureWindowsPath.is_reserved()` accepts, gives `None` on Windows. D14, LF9 and `PROGRESS.md` say those two things and nothing else.

**K5. What a listing does not decide.** `git grep -n -E "read\.scope\.validate|is_workspace_result_path\(" bd67126a -- src/probos/cognitive/swe_harness/tools.py`: `tools.py:313, 327, 336, 472, 475, 830, 831` (`ReadFileTool.invoke`: the run's scope check at 472 and the routing of a `.tool-results` path at 475; `CodebaseReadSourceTool`'s at 830 and 831). `read_verified_file` (`file_access.py:1106` to `:1119`): `resolve_read_path` of the candidate, `resolved != candidate` → `source path aliases another file` (1117), then `pin_directory` (1118) and `read_bytes` (1119), which verify the directories and the file.

**K6. Reach.** `probe_reach.py` (`git ls-tree -r --name-only` on the head, each name under `/w`, `os.name` set to `posix`): `tracked names: 5889; given no spelling by reader_spelling (POSIX shape): 0; direct parent a reserved device name or stem: 0`.

**K7. Cost** (`probe_cost3.py`; µs per call; the gate calls and the `pathlib` constructor calls are for one call; the fixture labels are the probe's own names: counted by `len(Path.parts)` (`probe_fixture_parts.py`, one run) the paths labelled `7 parts`, `12 parts` and `3 parts` hold 9, 13 and 3 parts):

```
fixture    state                 us per call  gate calls  pathlib constructors
7 parts    pre-M7 (8c83093b)           24.71           1                    17
7 parts    M7 (bd67126a)               34.51           2                    24
7 parts    current tree                35.01           2                    24
12 parts   pre-M7 (8c83093b)           43.43           1                    21
12 parts   M7 (bd67126a)               58.25           2                    28
12 parts   current tree                60.79           2                    28
3 parts    pre-M7 (8c83093b)           18.12           1                    11
3 parts    M7 (bd67126a)               27.25           2                    18
3 parts    current tree                27.24           2                    18
for scale: plain_spelling 0.86 us; resolve_read_path on an existing file with no roots (the policy check each match already gets) 207.9 us
audit over 8 inputs: gave a spelling for 1; filesystem calls counted: none
```

**K8. The probes' counts and the differential against the head.** The oracle probes' counts: `probe_lexical_oracle.py` with `LEX_EXPECT=clean` on the repaired tree: PREMISES HELD (0 holes, 0 misses on 292,464 texts per shape); `probe_lexical_oracle3.py` with `LEX3_EXPECT=clean`: PREMISES HELD (Windows: 716,165 texts, the oracle admits 180,769, 0 holes, every miss the same-file rule's, 155,748; POSIX: 716,164 texts, admits 123,205, 0 holes, every miss a text that is not its own normal form, 27,316); `probe_lexical_oracle2.py` stops on its own `LEX2_EXPECT=clean` assertion with 27,316 POSIX misses, each a text with a `..` part (by design). The differential is `probe_diff6.py` (the head's function copied verbatim from `bd67126a`, the tree's function, and the same corpus; P-A: the new result is `None` or the head's; P-B: it is `None` exactly when the head's is `None` or the path has no final name or has a `..` part). Output:

```
[windows] differ 3; newly denied 3; newly denied: no final name 3; oracle admits, head withholds: a '..' part 36202; oracle admits, head withholds: same-file rule 119546; oracle admits, tree withholds: a '..' part 36202; oracle admits, tree withholds: same-file rule 119546; texts 716165
[windows] P-A / P-B violations: 0
[posix] differ 16561; newly denied 16561; newly denied: a '..' part 16560; newly denied: no final name 1; oracle admits, head withholds: a '..' part 13530; oracle admits, tree withholds: a '..' part 27316; texts 716164
[posix] P-A / P-B violations: 0
DIFFERENTIAL CLEAN
```

So on Windows only the three roots change; on POSIX the changed texts are the root and texts with a `..` part, and every one of the 27,316 texts the oracle admits and the tree withholds has a `..` part.

**K9. The case ids of T29 and T30, and the shares of T34's corpus** (`pytest tests/test_bf953_read_floor_spellings.py --collect-only`, 264 tests, and `probe_t34_numbers.py`):

```
T29 (24 rows): an ordinary name | a space inside a name | a non-ASCII name | an astral name | a name that only starts like a device name |
  a lone high surrogate | a lone low surrogate inside a name | a lone surrogate in an ancestor | a colon in the final name | a colon in an ancestor |
  a newline in the final name | a character below 32 in an ancestor | a reserved device stem as the final name | a reserved device name in another case |
  a trailing dot in the final name | a trailing space in the final name | a reserved device name as the direct parent | a reserved device stem as the direct parent |
  a reserved device name above the direct parent | a trailing dot on an ancestor | a trailing space on an ancestor | a '..' as the final name |
  a '..' that leaves a reserved device name as the direct parent | a '..' that leaves an admitted name
T30 (21 rows): an ordinary name | a reserved device name as the direct parent | a reserved device stem as the direct parent | a reserved device name above the direct parent |
  a trailing dot on an ancestor | a trailing space on an ancestor | a colon in the final name | a timestamp in the final name | a newline in the final name |
  a reserved device stem as the final name | a backslash in the final name | a trailing dot in the final name | a trailing space in the final name |
  a name decoded with surrogateescape | a relative spelling | a filesystem root | a root with two leading separators | a '..' as the final name |
  a '..' that leaves a reserved device name as the direct parent | a '..' that leaves a reserved device stem as the direct parent | a '..' that leaves an admitted name
  T31 (10 rows, 9 on Windows): note.txt | a b.txt | café | .hidden | x..y | note. | "note " | "note. " | ... | a\b (the backslash row off Windows only)
  T34 corpus per shape: texts 9032 (all distinct); the oracle admits 1704 (POSIX) and 2290 (Windows); refused only by the parent's gate 640; refused only by normalising 56;
  admitted and not their own normal form 556 (POSIX) and 741 (Windows); listed by the function 1148 (POSIX) and 205 (Windows); the root is refused by the oracle
```

**K10. The gates the contracts define** (`git grep -n -o -E "^- \*\*G[0-9]+( \(M[0-9]+\))?[,.]?[^*]*\*\*" bd67126a -- prompts/bf-953-read-floor-spellings.md prompts/bf-948-list-files-read-policy.md`): BF-953 `128 G1 (red)`, `129 G2 (green)`, `130 G3`, `132 G5 (M4)`, `134 G6 (M5)`, `136 G7 (M6)`, `138 G8 (M7)`; BF-948 `165 G1`, `166 G2`, `167 G3`, `171 G4, red first`, `175 G4, green`, `181 G5 (M5)`, `186 G6 (M6)`, `191 G7 (M7)`, `193 G8 (M8)`. BF-953 has no G4.

**K13. The lister's paths** (`git grep -n -F -e 'Path(pattern).anchor or ".." in Path(pattern).parts' -e 'base = resolve_read_path(' bd67126a -- src/probos/cognitive/swe_harness/tools.py` prints `tools.py:574:        if type(pattern) is not str or Path(pattern).anchor or ".." in Path(pattern).parts:` and `tools.py:584:                base = resolve_read_path(`, that is, the guard that refuses a pattern with a `..` part and the resolution of the base; and, in one `python -c` over `src` (`base.glob('**/*')`, 1,196 matches): 0 matches with a `..` part, and `base.glob('**')` yields the base itself: `True`).

## Absence Verified (Amendment 5, 2026-11-05, on `bd67126a`)

```
CLAIM: nothing but ListFilesTool calls reader_spelling in src
RUN:   git grep -n -e "reader_spelling(" bd67126a -- src
FOUND: file_access.py:191 (the definition), tools.py:599 (ListFilesTool)
HOLDS: yes

CLAIM: no test of the BF-953 file reads or writes a private name of the pinned directory
RUN:   git grep -n -E "\._(paths|leaf|descriptors)" -- tests/test_bf953_read_floor_spellings.py   (on the repaired tree)
FOUND: on the head, test_bf953_read_floor_spellings.py:1283 (directory._paths = [...]) and :1288 (directory._leaf(parsed.name)), plus two docstrings that name PinnedDirectory._leaf (:1278, :1305); on the repaired tree: no output (exit 1)
HOLDS: yes

CLAIM: R6M-, E3-, G3-, B12-, B13-, P10-, T36 to T38, L22, the headings 7.8 and 7.9, 13f (BF-953) and 13g (BF-948), G9, the M8 and M9 rows and the Amendment 5 header (BF-953) and Amendment 6 header (BF-948) are unused at the head
RUN:   git grep -n -I -E -e "R6M-" -e "\*\*(E3|G3|B12|B13|P10)-[0-9]+\*\*" bd67126a -- prompts/bf-953-read-floor-spellings.md prompts/bf-948-list-files-read-policy.md PROGRESS.md DECISIONS.md src tests ; the same for -e "\bT3[678]\b" over the two contracts and the two test files, -e "^- \*\*L22\." over the two contracts, -e "^### 7\.8 M" over BF-953's and -e "^### 7\.9 M" over BF-948's, -e "^## 13[fg]\." over both, -e "\*\*G9" over both, -e "^\| M8 \|" over BF-953's, -e "^\| M9 \|" over BF-948's, -e "Revised by \(Amendment [56]\)" over each
FOUND: nothing (exit 1) for each, except that BF-948 has a `## 13f` heading and an Amendment 5 header already (so its new heading is `13g` and its new header Amendment 6)
HOLDS: yes

CLAIM: the 1 and 3 holes the orchestrator's probe found for a root are the only Windows holes; no Windows input other than the root changes
RUN:   probe_lexical_oracle3.py on the head function and on the repaired tree; the differential of §13f K8
FOUND: see K8
HOLDS: yes (K8)
```

## 14. Deterministic gate checks, resolved up front

- **`check_architecture_principles.py --check`:** after Amendment 1, two private classes in `file_access.py` (`_OnDisk` with three methods, and the exception `_Unverifiable`), private helpers `_namespace_free`, `_file_identity`, `_identity_position`, `_match_position`, `_base_name`, `_base_file` and `_protected_leaf`, and one public helper, `plain_spelling` (the check passed with the same counts on the scratch tree: `srp-size=92, layer-import=0, db-connect=30, unowned-task=13`); no new module, no import (`os`, `PureWindowsPath` are already imported at `:45`, `:54`); only public names cross a module. The new test imports private names from the BF-948 test module and from `file_access`, as BF-911's tests do from `file_access` (`tests/test_bf911_protected_config_write_refusal.py:259`). G2 runs the check.
- **`check_dormant_classes.py`:** `_OnDisk` is constructed in `_longest_match` and `resolve_read_path`.
- **Config:** none. **EventType:** none. **Goldens:** none touched.
- **`gen_ad_ledger.py --check`:** passes once M3 regenerates; the heads carry no status keyword in their first 120 characters.
- **Collection:** one new test file; M1's strict xfails keep G1 green on the base.
- **Exceptions (three-tier):** (Amendment 1) `_file_identity` returns `None` only for "no such file" and raises `_Unverifiable` for any other failure; the one boundary, `resolve_read_path`, logs the class of the cause and refuses with a bounded reason (propagate to the policy's refusal: a floor that cannot be verified is not a floor that decided); `_match_position` keeps its `OSError`/`ValueError` skip around the textual comparison only. Nothing is swallowed that the base propagated.
- **After Amendment 2:** one more public helper, `reader_spelling`, and two private ones, `_floor_roots` and `_workspace_root`, in `file_access.py`; no new class, module or import (`PureWindowsPath`, `Sequence` and `os` are already imported); the check passed with `srp-size=92, layer-import=0, db-connect=30, unowned-task=13` (the same counts) on the scratch tree. `_workspace_root` catches `Exception` around the composition (as the two builders did, tier "log-and-degrade": the debug line is the base's) and `OSError`, `RuntimeError` and `ValueError` around `resolve()` (the three `resolve_read_path` already catches; the line says the root is kept).

## 15. Prior Art and Blind Spots

- **Internal:** BF-758 (floor, policy, resolve before containment); BF-908 (the config files in the floor; `_ReadFloor`); BF-911 (the write side's key and its `os.stat` identity layer, whose idea this reuses for the read side); BF-948 review round 1 (finding 1, where this was found). Considered and not reused: `_same_identity` (`file_access.py:516`) compares two `os.stat_result`s, including the file type, for the pinned reader's chain checks; the read floor needs a hashable key and the zero-index rule, and merging the two would touch the pinned reader, so `_file_identity` stays separate.
- **External:** skipped. A Windows-only path-identity matter with no outside design question.
- **Blind spots found:**
  1. The orchestrator's first probe rows for `ListFilesTool` were void (it imported the floor function by name, so a monkeypatch of the module name never reached it): T3 uses BF-948's rig, which passes the floor through the runtime, and asserts first that the ordinary spelling of the same directory is refused.
  2. The exempt scenario passed on the base only because no floor root matched the spelling: T1 asks the exemption on a spelling the floor now matches.
  3. A drive-letter-only text rewrite would have left the host-name spellings undecided (`_write_key` leaves them apart too).
  4. A rewrite of the returned path would lose the prefix a long local path needs (D2).

## 16. Diff Reviewer: properties to verify

This is a shared-contract change: review the whole candidate, every consumer in §1, not only the new lines.

1. For every spelling in `_FAMILIES`, `resolve_read_path` returns the decision the ordinary spelling gets for the floor (directory root and file root), and the same refusal reason where the ordinary spelling is refused, whether or not the file exists, with these qualifications: (a) where the ordinary spelling is admitted by an exempt or a permitted root, a share spelling (`_SHARE_FAMILIES`) is refused with that root's reason (L9); (b) a share spelling of a path that is not on disk is decided by the existing ancestors of its chain, so beneath an existing floor directory it is refused where the base admitted it; (c) a share spelling of a missing **file** root is admitted while the ordinary spelling is refused (L2).
2. An admitted call returns `Path(raw).resolve()` exactly as the base did, and that path names the file the decision was about.
3. Every decision on a drive-letter path against drive-letter roots is the base's, and no `os.stat` is added for it, with three stated exceptions: (a) on Windows the final component is decided by the file it names, the candidate's and a floor file root's, so a stream suffix, a trailing dot or space (and for a credential name another case) is refused as the file is where the base admitted it (D11, D12: a root named `ordinary-file-root`, a request for `loaded.yaml:settings`: the base admits, the head refuses; and the default stream of a root loaded as a stream is refused); (b) a workspace root configured as an 8.3 short path or on a mapped drive exempts the workspace it names, where the base's unresolved root exempted nothing (D9, the one intended admission); (c) a workspace root the system cannot resolve is kept as composed (D13), which is the base's list. On a platform other than Windows nothing in `_match_position` differs from the base in its result.
4. At the floor, nothing that the base refused is admitted: the identity step and the final-component step only add refusals there. An exempt or a permitted root admits a spelling only if the ordinary spelling of the same file is admitted by that root (its namespace-free text names it), so the extended-prefix spelling of a path under a permitted root is admitted where the base refused it, and no share or device spelling is admitted by one. A path no floor root is, sits under or reaches by volume stays as it was.
5. The exemption lifts the floor for a spelling that a floor root matches only where the exempt root's text, without a namespace prefix, contains the path and stands deeper in the path's own chain than the floor match (a count of the path's parts, never of the root as spelled); a file under the floor but outside the exempt root is refused, and so is a share or device spelling of an exempt file (L9).
6. A root that is not on disk contains nothing by identity (the textual decision stands for it; L2). A floor root, or a part of a share or device spelling's own chain, that the system cannot answer for (a failed read other than "no such file", or a zero file index) refuses the call with `path cannot be verified against the protected roots`; no exception text reaches the reply, and the log carries the class of the cause only. A path that is not on disk is decided by the existing ancestors of its chain.
7. `_namespace_free` is pure and is the same on every platform; `_write_key` and its parity with `builder_paths` (BF-911 T19) are unchanged.
8. M1 to M3: `tools.py`, the BF-948 test file, every consumer, config and `EventType` are unchanged; the two tracker edits only insert; BF-948's P4-6 and P4-7 SEARCH strings still occur once each. M4: `file_access.py` and its test file change, the two tracker entries are amended in place with their heads unchanged, and no consumer, config field or `EventType` changes; BF-948's M5 (Amendment 2) is the only change to `tools.py` and the BF-948 test file.
9. Every new or rewritten docstring, comment, error string and test docstring is true of the head in the code's branch order; no head text describes what can be read, from where or by whom.
10. Each test whose xfail mark M2 removes failed on the base for the reason its mark names; T8 passes on the base.
11. (M4) A drive-letter spelling against drive-letter roots reads no identity (T9) and costs the base's calls; an exempt or a permitted root is never compared by identity (DNY-6, DNY-14, DNY-15).
12. (M4) The floor refuses a share or device spelling whose own chain names a floor root, and one whose chain reaches a floor root's volume through a link (T10, T11); a link on the root's own volume is followed by `Path.resolve()` and needs no rule (measured: `evidence-amend1-samevol-after`).
13. (M4) An exemption stands at a count of the path's own parts: the same count for every spelling of its root (T13, T17). T16 shows only that a text count is the same number however the prefix is spelled, and kills no mutant of `_match_position`; T27 pins the position it returns for a text match and for an identity match (R3M-11, R3M-12).
14. (M4) Both root builders return the long resolved workspace root for a short-path configuration (T14); `WorkspaceManager` and `_resolve_workspace_root` are unchanged.
15. (M4) Every new or rewritten docstring, comment, error string and test docstring is true of the head in the code's branch order; no head text describes what can be read, from where or by whom.
16. (M4, update 2) On Windows the floor's file roots and the credential names are compared by the file the final component names (the text from the first colon, then trailing dots and spaces; for a credential name the write side's case-folded key), whether or not the file is on disk: a stream, trailing-dot, trailing-space or case spelling of one is refused with the file's own reason (T19 to T21; DNY-22 to DNY-31). The path an admitted read returns is the path as resolved, so a neighbour's stream is read as named. The share spelling of an absent file root is the one exception (L2). On another platform the names are compared as they are (T22).
17. (M4, update 2) A loaded config file root outranks the workspace that encloses it however the workspace root is spelled, and the verified readers refuse it too (T17).

**M5 (Amendment 2): review scope and properties.** The orchestrator decides whether round four reviews the whole candidate or the delta; this contract's recommendation is the delta `34bd9153..HEAD` with items 18 to 22, the three reproductions of §1 items 9 to 11 re-run, and every consumer of §1 whose result the delta can change (items 18 and 19 name them).

18. (M5) A floor file root is compared by the file its own final component names, as the candidate is: for a root spelled `loaded.yaml:settings`, `loaded.yaml.` or `loaded.yaml ` (the last two in the extended namespace) the root's own spelling, the ordinary spelling of the file, its default stream and every other stream of it are refused with the floor's reason, and a neighbour is admitted (T23, T28). For an ordinary root list `_floor_roots` equals the list, so every decision against it is the head's, and on another platform nothing is added (T24). A position count is the root's own count of parts (T27). A directory root spelled in the extended namespace with a trailing dot or space also refuses the directory its base names (L16).
19. (M5) `permitted_read_roots` and `workspace_exempt_roots` return the workspace root as `Path.resolve()` spells it, and as composed when `resolve()` raises `OSError`, `RuntimeError` or `ValueError`; a configured policy whose roots are unusable and whose workspace root does not resolve still refuses every path outside its roots, through the policy, `read_file` and `list_files` (T25), as the base did. A policy whose every root is unusable and whose workspace root cannot be composed at all is `[]` (L17, as on the base). The consumers of `permitted_read_roots` and `workspace_exempt_roots` are those of §1 item 4 and `agent_work_runner.py`'s `reads_confined`.
20. (M5, amended by M6 to M8) `reader_spelling` calls no filesystem function (T32). It gives `None` where the verified reader's own functions refuse the text of the file or of its direct parent, where the path has no final name or a `..` part, and, on Windows, where D14's rule applies (D15, L22); otherwise it gives `plain_spelling`'s result. It does not say that a name opens (L18), and it adds string and path-object work for each match (L20).
21. (M5) No signature, return shape, config field, `EventType`, persisted format or gate changes (§9); the seven consumer files and the 14-file G4 list keep their counts (G6).
22. (M5) Every new or rewritten docstring, comment, error string and test docstring is true of the head in the code's branch order: none says that a name with a stream suffix, a trailing dot or a trailing space "is the same file" or "does not make another file" (`_namespace_free`, the test module, `PROGRESS.md`, §16 item 3), and none says a bare drive is returned unchanged; no head text describes what can be read, from where or by whom.

**M6 (Amendment 3): properties.**

23. (M6, amended by M7 and M8) The function applies the verified reader's own functions to the text on every platform: `validate_read_location` is called as it is, and the final-name rule is the pinned directory's (T31, T36). Which texts get no spelling is the rows of T29 and T30 and the corpus of T34 (§13f K9). What D14's rule withholds above the direct parent is not looked at off Windows (L21; T29, T30, T35).
24. (M6) A directory holding names that the verified reader's gate refuses is listed without them from an ordinary and an extended-prefix base, every file listed is opened by the verified reader with its own bytes, and the unarmed `read_file` opens a name left out (T33; the names probe: a 216-file fixture, 0 listed names the armed reader refuses and 0 names it opens that are not listed, from both bases and both patterns).
25. (M6) No `reader_spelling` caller, signature, config field, `EventType`, persisted format or gate changes. `git diff a0857b08 -- src` names `file_access.py` and `tools.py` only; in `file_access.py` the diff is inside `plain_spelling`'s docstring and `reader_spelling`; `validate_read_location`, `PinnedDirectory` and `read_verified_file` are byte-identical to the head.
26. (M6) Every new or rewritten docstring, comment, error string and test docstring is true of the head in the code's branch order, and none says that a listed name opens, that a listing reads nothing, or that its cost is unchanged; the claims audit of Amendment 3's §3 lists each sentence found and where it landed.
27. (M6) Round 5 reviews the delta `a0857b08..HEAD` (M6, and M7's docstring and comments). The properties to verify, each with its probe or test, are Amendment 3's §11; the reviewer confirms each, traces `reader_spelling`'s one caller and the consumers of `list_files`' reply, and states what it did not check. The sha256 of the three code files is §10's; R4M-1 to R4M-13, R3M-7 to R3M-10 and R3N-1 to R3N-3 are killed on those hashes; the differential probe finds the new result `None` or the head's for every input, and the names probe finds 0 holes in both directions. A change to `validate_read_location`, `PinnedDirectory`, `ReadFileTool` or the fault classification is outside M6 and has its own review (BF-948 L17).

**M7 (Amendment 4): properties.**

28. (M7) The function calls the gate on the file's text and on its direct parent's text, as `read_verified_file` and `PinnedDirectory.open` give them (T37 records the texts the reader gives its gate), and applies the pinned directory's child-name rule to the final name (T31, T36). The orchestrator's probe (`probe_lexical_oracle.py`) finds 0 holes and 0 misses over 292,464 texts per shape on M7's head (the head before it: 31,941 POSIX holes) and on M8's; T34 checks the same over its corpus; R5M-1, R5M-2, R5M-4, R5M-5, R5M-6 and R5M-7 are killed by T30 and T34 and are the probe's holes or misses (§10).
29. (M7) What the reader gives its gate: the call list of `read_verified_file` on real files (`probe_gate_trace2.py`, §13f K2) shows the file, the direct parent and the file again from `_leaf`, and no gate call on a directory above the direct parent; T37 records the same from the real reader on any platform. The reviewer re-runs the probe or reads `read_verified_file`, `PinnedDirectory.open` and `_leaf`, and states what the POSIX branches add and what it did not check.
30. (M7) The change is deny-only against the head, and on Windows no input changes: `probe_diff5.py` finds 0 differences over 43,380 Windows-shaped inputs, and on POSIX 124 newly denied of 7,536, each with a direct parent the gate refuses, 0 violations of P-A and P-B.
31. (M7) What D14's rule withholds above the direct parent is listed off Windows and left out on Windows, and L21 says both and why; T35 reads a file below `con/sub` with the verified reader from a real directory and lists it off Windows only. T35 has not run on a POSIX host: the reviewer reads its expectations against the POSIX branches of the reader and says what it did not check.
32. (M7) Every new or rewritten docstring, comment, error string, test docstring, contract sentence and tracker entry that says what a listing's names do, or what a refused name is answered, is true of the head: Amendment 4's §4 listed each site, and Amendment 5's §3 re-ran the audit and deleted what it found false (B6-1) or unmeasured. R4M-9 is recorded as equivalent, not as a gap. Round 6 reviewed the delta `8c83093b..HEAD` (BF-953 M7, BF-948 M8). A change to `validate_read_location`, `PinnedDirectory`, `ReadFileTool` or the fault classification is outside M7 and has its own review (BF-948 L17).

**M8 (Amendment 5): properties.**

33. (M8) A path with no final name has no spelling, on both platforms: T36 reads the reader's rule back from a real pinned directory (the empty child name is refused), T30's root rows and T34's corpus cover the POSIX shape, and T38 lists a real drive root through the real tool (Windows) and gets nothing; R6M-1 to R6M-3 are killed. The reviewer re-runs `probe_root_listing.py` (after: `{'files': []}`).
34. (M8) A path with a `..` part has no spelling: T29's and T30's rows, T34's corpus (`..` as a directory) and T37 (the candidate of a text with a `..` part is its normal form) cover it; R6M-4 to R6M-8 are killed. The reviewer re-runs `probe_noncanonical.py` and oracle3 (`LEX3_EXPECT=clean`: 0 holes, and every miss is the same-file rule's or a text that is not its own normal form), and states that oracle2's own `LEX2_EXPECT=clean` stops on the POSIX shape's `..` texts by design (Amendment 5's §2.2).
35. (M8) The change is deny-only against the head: a differential over T34's corpus finds the new result `None` or the head's for every input, and `None` exactly where the head's is `None` or the path has no final name or has a `..` part (§13f K8).
36. (M8) T34's oracle is the reader's functions through the public API only (`validate_read_location`, a real pinned directory's `read_bytes`): no private name is read or written (§13f K12). T37 records the three texts the reader gives its gate and fails when they change (R6M-9 to R6M-11).
37. (M8) No sentence that enumerates classes remains outside a command's output: L22's table and the case ids of T29 and T30 are the only lists. The reviewer re-runs the audit's searches and the ledger's commands (Amendment 5's §3) on the head and states which it did not run; D15, SP12, §1 item 16, §12 and §16 point to L22 and say nothing exclusive about what the reader answers; L20's numbers are re-measured (`probe_cost3.py`); BF-948's §17 item 6 and this contract's §17 item 4 list the gates the contracts define (§13f K10).
38. (M8) No signature, return shape, config field, `EventType` or persisted format changes; `git diff bd67126a -- src` names `file_access.py` and `tools.py` only; in `file_access.py` the diff is inside `reader_spelling`; `validate_read_location`, `PinnedDirectory`, `read_verified_file` and `resolve_read_path` are byte-identical. The three files' sha256 are §10's, and the campaign's rows are killed on those hashes. A change to `validate_read_location`, `PinnedDirectory`, `ReadFileTool` or the fault classification is outside M8 and has its own review (BF-948 L17). Round 7 reviews the delta `bd67126a..HEAD` (BF-953 M8, BF-948 M9) and nothing wider (the stopping rule of Amendment 5's §0).

## 17. Acceptance criteria

1. Every spelling in `_FAMILIES` gets the ordinary spelling's decision from `resolve_read_path` for the floor, and a refusal where only an exempt or a permitted root admits the ordinary spelling and the spelling is a share (T1), through `ReadFileTool` (T2), through `ListFilesTool` (T3), and for the loaded config file the write side agrees (T4).
2. The path returned is the resolved path and names the file (T1, T9). A drive-letter path costs no identity lookup (T9). A share path no root covers stays admitted (T10).
3. The canonicaliser is pure and the same everywhere (T5, T6); the identity helper follows the zero-index rule (T7); POSIX names stay distinct (T8).
4. Every §10 mutant is killed, SPM-1 to SPM-4 and SPM-16, DNY-1 to DNY-32, R3M-1 to R3M-14, R4M-1 to R4M-13, R5M-1 to R5M-9, R5M-T1 to R5M-T3, R6M-0 to R6M-11 and R6M-T1 to R6M-T4 (R4M-9 is an equivalent mutant from M7, §10). G1 to G3, G5 to G9 and the §14 checks pass, and the broad gate's receipt is green for the batch.
5. (M4) A share spelling through a link to another volume is refused by a permitted root and by a floor root on that volume (T11); a floor that cannot be read refuses a share spelling (T12); an exemption is ranked by where it stands in the path, and a floor file root outranks the workspace that encloses it (T13, T17); a short-path workspace root is the root its long path is (T14); the display form of a listing has no namespace prefix (T15, BF-948 T13, T14); a stream, trailing-dot, trailing-space or case spelling of a floor file root or a credential name is decided as the file is, on disk or not (T19 to T21).
6. (M5) A floor file root spelled with a stream suffix, a trailing dot or a trailing space is refused in its own spelling, in the ordinary spelling of its file and in every stream of it (T23, T24, T28); a workspace root the system cannot resolve stays in both root builders as composed, so a configured policy still confines (T25); (M6 to M8) `reader_spelling` returns a spelling only where the verified reader's own functions admit the text of the file and of its direct parent, on every platform; a path with no final name or with a `..` part has none; and, on Windows, only if every component names the file in the ordinary namespace (T26, T29 to T31, T33 to T38), which BF-948's T15 reads back through the verified reader; it does not say that a name opens (L18); T27 pins the positions T16 only counts.
7. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
