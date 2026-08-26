# AD-1250: joint allowance/ration search — a policy decision, not a fix

**Issue:** #1294 (already filed, OPEN) · **Repo:** OSS `d:\ProbOS`, branch `main`
**Number:** AD-1250 — already allocated, do not mint a new one.
**Provenance:** adversarial review of the BF-762 diff (#1220).
**This is a decision prompt with a measurement phase in front of it.** Do not write the search first.

---

## What exists at HEAD (2026-08-22)

`render_tool_output_sourced` searches two dimensions **in a fixed, deliberate order** — the per-leaf
**allowance** (BF-761) first, then the container **ration** (BF-762), reusing the allowance the first
search settled on:

```
src/probos/cognitive/swe_harness/tool_call.py:493-529   def search_allowance(keeps, floor_render, best)
                                             :531       best, allowance = search_allowance(...)   # ONCE
                                             :579-627   for _ in range(_RATION_PROBES):           # reuses `allowance`
```

The order is **stated in the module, not discovered**, with the alternative measured and rejected:

```
tool_call.py:551-560
  "the allowance is searched FIRST, and the ration search then reuses it. Re-running the allowance
   search after each widening was implemented and then removed -- measured across seven payload
   shapes at three caps, twenty of the twenty-one combinations rendered identically and review found
   a twenty-second, a mixed JSON payload, where a faithful re-run rendered 5,805 characters against
   5,805 and added no rows."
```

**The joint search is a different thing from that re-run.** A re-run re-optimises the allowance at a
ration already accepted. A joint search lets a widening that *would otherwise overflow* succeed by
trading leaf detail for breadth. That is a policy change — *"more rows, each shorter"* versus *"fewer
rows, each fuller"* — not a bug fix. BF-762 does not carry it, and correctly says so.

### The claim under consideration

> A joint search that tightens allowance before classifying a wider ration as overflow retained
> **32 rows instead of 13** in one cap-3,000 mixed payload.

**Architect has not reproduced this.** It comes from the review of #1220 and is recorded as measured
there. See phase 1 — reproducing it is the first deliverable, before any decision is taken.

### Blast radius is narrower than it looks — state this to the Captain

The renderer is **inert on the shipped configuration**:

```
tool_call.py:434-435          if max_chars <= 0 or len(plain) <= max_chars:  return plain, len(plain)
git show HEAD:config/system.yaml   ->  tool_result_max_chars: 0
config/system.yaml (Captain's local, skip-worktree)  ->  tool_result_max_chars: 6000
```

So the entire two-dimensional search runs only for an operator who sets a non-zero cap — today, the
Captain's vessel. That is not a reason to skip the decision; it is the reason it is a *policy* call
about one vessel's defaults rather than an urgent correctness fix.

### And it is one policy for every payload

There is exactly **one** consumer, and it is the boundary every agentic tool result crosses:

```
tool_call.py:678   def from_tool_result(cls, ..., max_chars: int = 0)
             :726      out, source_chars = render_tool_output_sourced(raw, max_chars=max_chars)
```

So a 120-row search result set and a deep diagnostic payload are governed by the same choice. The
issue's first question — "a search result set and a diagnostic payload plausibly answer differently"
— is structural, not hypothetical.

---

## Phase 1 — measure, and report. Do not change `tool_call.py` in this phase.

Deliverable: a throwaway script (delete before commit) plus a written table. Nothing else.

1. **Reproduce the headline.** Build the cap-3,000 mixed payload the review used and confirm ordered
   = 13 rows, joint = 32. **If it does not reproduce, stop and report that** — a policy decision built
   on an unreproduced number is the failure this repo keeps paying for. Say what you got.
2. **Characterise, do not anecdote.** Run both searches across the shape × cap matrix BF-762 already
   used (seven shapes × three caps, `:555-558`) plus the flat integer array named at `:566-569`
   (`{"rows": list(range(100000))}` at a 50,000 cap). For each cell report: rows retained, bytes
   retained, % of budget spent, and **renders performed**.
3. **Report the losses, not only the wins.** A joint search that trades leaf detail for breadth
   *must* lose somewhere. Name the shapes where the ordered search retains more useful content, and
   quantify. A measurement that finds only improvements has not looked hard enough.
4. **Test monotonicity at adjacent caps, not on a ladder.** BF-762 had to quantise its ration ladder
   to powers of two because a cap-dependent ladder broke "a bigger cap never returns less":
   `tool_call.py:596-600` records 5,954 chars → 126 rows and 5,955 → 120. **A joint search has two
   ladders that can both move with the cap, so this binds harder, not less.** Sweep every integer cap
   across at least one 3,000-wide window per shape and report the worst dip. A sparse ladder proves
   nothing — that is the recorded lesson from BF-762 itself.
5. **State the render bound as an arithmetic expression**, before any code is written. Today's is
   fixed and asserted:

   ```
   tool_call.py:218   _ALLOWANCE_PROBES = 8
                :225   _RATION_PROBES    = 5
                :416-419 / :576-578   "16 depth-zero renders in the worst adversarial case"
   tests/test_bf762_container_ration_is_searched.py:221, :233, :247
        assert count <= 3 + tool_call._ALLOWANCE_PROBES + tool_call._RATION_PROBES
   ```

   A joint search over two dimensions multiplies probes. AD-1151 R3 measured a serialise-per-elision
   loop at **33 s for 2,000 entries synchronously inside an async method** — that is the precedent for
   why this bound is not negotiable. **Any joint search must state its bound before it is written**,
   and the bound must remain a fixed expression in the two constants, not a data-dependent one.

---

## Phase 2 — the decision. HANDED TO THE CAPTAIN.

**Do not choose this yourself, and do not build past it.** Present phase 1's table with a
recommendation and stop.

The question, precisely:

> **For a bounded tool result the model must reason over, is breadth (more records, each shorter) or
> per-record detail (fewer records, each fuller) worth more — and is one answer right for every tool?**

Three outcomes are all legitimate:

- **Take the joint search** as the single policy, if phase 1 shows a broad win and a bound that holds.
- **Decline it**, and record the measurement in the module beside BF-762's existing rejected-alternative
  note, so the next reviewer finds the answer instead of re-deriving it. This is a real outcome, not
  a failure — BF-762 already improved this shape class from 13.6% to 92% of budget on the measured
  120-row array. This issue is about the remaining headroom, not a loss.
- **Split the policy per tool** — and if the Captain wants this, it is a **separate AD**, not this one.
  See "do not build".

Architect's recommendation, offered not assumed: **decline unless phase 1 shows the win generalises
past the one mixed payload AND the render bound stays a fixed expression.** The measured advantage is
one shape at one cap; the constraint it strains (cap monotonicity across two coupled ladders) is the
one BF-762 needed a deliberate quantisation to satisfy with a single ladder. Breadth-over-detail is
also the wrong trade for the payload class BF-759 was fixed for — a single-leaf document where
"more rows" is meaningless and leaf detail is the entire answer.

---

## Phase 3 — build, only if the Captain says yes

### Required tests

Extend `tests/test_bf762_container_ration_is_searched.py` rather than starting a new file: it already
owns this contract, and splitting it invites the two halves to drift.

1. **The render bound holds**, asserted as an expression in the constants — not a magic number.
   `:221, :233, :247` are the existing assertions; they must be **updated to the new expression with
   the reasoning recorded inline, never deleted**. A test that pins the old bound as contract will
   otherwise make the correct new bound look like a regression.
2. **Cap monotonicity across adjacent caps**, per shape, asserted with the tolerance BF-762 uses
   (`later >= earlier * 0.99`) and the measured worst case named in the docstring. State the property
   you actually have — a fixed-probe search is monotone only up to its resolution.
3. **The headline improvement**, pinned to the reproduced payload, with the ordered-search result
   asserted as the counterfactual so the test proves the joint search is load-bearing.
4. **The losses are pinned too.** Every shape phase 1 found a regression on gets a test asserting the
   *measured* new value, so a later "improvement" that quietly worsens it goes red.
5. **`_RATION_PROBES = 0` still degrades cleanly** — `:318` monkeypatches it and that path must survive.
6. **Mutation matrix per guard.** BF-761 and BF-762 each found vacuous tests only through this;
   BF-761's own fix silently made one of its regression fixtures inert. Re-run the whole matrix after
   every source change, not only the first.

---

## Do not build

- **Do not build the search before phase 1 reports and the Captain answers.** The phases are the
  deliverable order.
- **Do not make the render bound data-dependent.** A bound that varies with payload shape is not a
  bound; it is the AD-1151 R3 defect with extra steps.
- **Do not re-introduce the per-widening allowance re-run.** It was implemented, measured across
  22 combinations, and removed (`:551-560`). It is a *different* thing from the joint search and
  including it would silently re-add four renders per widening for no content.
- **Do not remove the power-of-two quantisation** at `:588-600`. It is what makes the ration ladder
  cap-independent, and a joint search needs it more, not less.
- **Do not add a per-tool policy, a config knob, or a `render_hint` parameter** in this AD. If the
  Captain wants per-tool policy that is its own AD with its own blast-radius analysis — every tool
  registration and the `ToolResult` contract are in scope for that, and none of them are here.
- **Do not touch `_shrink`** (`:261`), the opaque-leaf carve-out, or the elision markers. BF-759 and
  BF-761 own those and their reasoning is recorded in place.
- **Do not change `_LIST_KEEP` / `_DICT_KEEP`** (`:207-208`) or the rung tuple at `:447`. BF-728's
  rations are correct when the budget is genuinely tight and the searches only ever widen from them.
- **Do not change the shipped `tool_result_max_chars: 0`.** Arming the renderer by default is a
  separate decision with its own cost.
- **Do not touch AD-1148's downstream character bound** or `truncate_tool_output`. That is the
  backstop this function's docstring promises and it stays.

---

## Acceptance criteria

**Phase 1:** a written table covering every shape × cap cell with rows, bytes, % of budget and render
count for both searches; an explicit statement of whether the 32-vs-13 headline reproduced; a named
list of shapes where the joint search loses; a worst-dip figure from an adjacent-cap sweep; and the
proposed render bound as an expression in `_ALLOWANCE_PROBES` and `_RATION_PROBES`. No source change.

**Phase 2:** a recommendation and a stop. The Captain decides.

**Phase 3 (only on a yes):**
- The render bound is fixed, expressed in the two constants, and asserted.
- Cap monotonicity holds to a stated, measured tolerance on every shape tested.
- Both the wins and the losses are pinned by tests.
- The module comment at `:551-560` is extended to record what was decided and why — including if the
  answer was no. A rejected alternative with its measurement is worth more than silence.
- Mutation matrix run per guard and after every subsequent fix.
- Focused gate: `pytest tests/test_bf762_*.py tests/test_bf761_*.py tests/test_bf728_*.py tests/test_ad543_tool_call_protocol.py -q -n 0`
- Then one consolidated gate: `pytest tests/ -q -n 16 --dist=loadfile`
- **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**
- Run the `Diff Reviewer` subagent on the staged diff with a different model than wrote the code.

---

## Verified Against Codebase (2026-08-22)

```
src/probos/cognitive/swe_harness/tool_call.py
  207-208  _LIST_KEEP = 8 ; _DICT_KEEP = 40
  218      _ALLOWANCE_PROBES = 8
  225      _RATION_PROBES    = 5
  383      def render_tool_output(value, *, max_chars: int = 0) -> str
  393      def render_tool_output_sourced(value, *, max_chars: int = 0) -> tuple[str, int]
  416-419  "16 depth-zero renders in the worst adversarial case"
  434-435  if max_chars <= 0 or len(plain) <= max_chars:  return plain, len(plain)   # inert at 0
  447      rungs = ((_LIST_KEEP, _DICT_KEEP), (4, 8), (2, 3))
  493-529  def search_allowance(...)          # called ONCE at :531
  551-560  the order is deliberate; the per-widening re-run was built and removed
  566-569  the ration-multiplier ceiling was built and removed; one measured loss recorded
  579-627  the ration search
  588-600  power-of-two quantisation; raw ratio measured 5,954->126 rows, 5,955->120
  678      def from_tool_result(...)          # the ONLY consumer
  726      out, source_chars = render_tool_output_sourced(raw, max_chars=max_chars)

grep -n "render_tool_output" src/probos/**    ->  only tool_call.py (def + the one consumer)

git show HEAD:config/system.yaml   ->  tool_result_max_chars: 0        (renderer inert as shipped)
config/system.yaml:2412            ->  tool_result_max_chars: 6000     (Captain's local, skip-worktree)
SystemConfig().agentic_loop.tool_result_max_chars  ->  0

tests/test_bf762_container_ration_is_searched.py
  221, 233, 247   assert count <= 3 + _ALLOWANCE_PROBES + _RATION_PROBES      # the bound, pinned
  268             for _ in range(tool_call._RATION_PROBES)
  318             monkeypatch.setattr(tool_call, "_RATION_PROBES", 0)
```
