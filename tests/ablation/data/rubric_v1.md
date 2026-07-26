# Crew artifact scoring rubric

<!--
Deliberately unversioned in its own text. The version string and the content
hash live in the harness, not here: naming the version inside the rubric would
put the study's name into the judge prompt and unblind the judge. The loader
enforces this and refuses a rubric containing any unblinding term.
-->

You are scoring a single artifact produced by a crew of collaborating agents
working on one goal. Score only what is in front of you. You are not told, and
must not guess, how the artifact was produced, what system produced it, or how
it compares to any other artifact.

Score each of the four dimensions independently on a continuous `0.0`–`1.0`
scale, where `0.0` is a total failure of that dimension and `1.0` is exemplary.
Use the full range: an artifact that is merely adequate on a dimension should
score near the middle, not near the top.

---

## `coordination_quality`

Do the parts of the artifact fit together, or are they stapled?

- `0.0` — the sections contradict each other, repeat each other verbatim, or
  read as unrelated documents concatenated under one heading.
- `0.5` — the sections are consistent and non-redundant but independent; none
  of them visibly depends on another.
- `1.0` — there is explicit evidence that one part consumed the output of
  another: a later section names, reuses, refines, or builds on a definition,
  schema, figure, or decision established in an earlier one, and the artifact
  is coherent as a single piece of work.

Do not reward a merely tidy structure. Reward observable dependency between the
parts.

## `reasoning_depth`

Does the artifact reason from the material, or restate the request?

- `0.0` — restates or paraphrases the goal, lists generalities, or asserts
  conclusions with no supporting chain.
- `0.5` — draws correct but shallow inferences; the reasoning is present but
  stops at the first step.
- `1.0` — works through the specific material, handles the non-obvious cases,
  names trade-offs, and shows why the chosen answer follows rather than only
  that it was chosen.

## `knowledge_retention`

Does the artifact use facts it was not handed in the goal text?

- `0.0` — every fact in the artifact is either in the goal text or invented.
- `0.5` — some grounded detail beyond the goal text, but thin or incidental.
- `1.0` — the artifact carries forward concrete, checkable specifics —
  identifiers, prior decisions, constraints, names, values — that are not in the
  goal text and are used to reach the answer rather than merely mentioned.

Penalise fabricated specifics. A confident, precise, wrong detail scores lower
than an honest omission.

## `artifact_correctness`

Does it actually answer the goal?

- `0.0` — answers a different question, or is unusable as a deliverable.
- `0.5` — answers the goal partially, or answers it but omits a stated
  requirement.
- `1.0` — satisfies every stated requirement of the goal and would be accepted
  by the person who asked for it without rework.

---

## Output format

Respond with JSON only — no preamble, no commentary, no code fence:

```
{"coordination_quality": 0.0, "reasoning_depth": 0.0,
 "knowledge_retention": 0.0, "artifact_correctness": 0.0,
 "justifications": {"coordination_quality": "...", "reasoning_depth": "...",
 "knowledge_retention": "...", "artifact_correctness": "..."}}
```

Every one of the four scores is required and every one must be a number between
`0.0` and `1.0` inclusive. Keep each justification to one sentence.
