"""AD-1180: the agentic disposition, held in one leaf module every path can reach.

AD-1177 authored this text and it worked -- on exactly one execution path. The
prose lived inside ``CognitiveAgent._conversational_agentic_self_description``,
which is composed into the prompt only on the Captain's 1:1 DM turn. The other
four callers of :meth:`WorkItemAgenticExecutor.run` (the AD-856 task path, crew
children, the AD-860 convergence re-run, and AD-1072 delegation) each pass the
agent's *static* ``instructions`` attribute straight through, so every one of
them received the same eleven-group tool array with no disposition about using
any of it. Emergence and collaboration live in exactly those paths.

Why a module rather than either caller: ``cognitive_agent`` imports
``WorkItemAgenticExecutor`` only *inside* methods, precisely to avoid a cycle
with ``agentic_dispatch``. Putting the constant in either file would force a
module-level import in the other and reintroduce that cycle. This module imports
nothing, so both sides can depend on it freely and it can never become the
reason an import graph breaks.

The text is the AD-1177 prose with one BF-727 correction, and is otherwise
deliberately NOT reworded -- AD-1180 widened its reach, it did not relitigate
the wording. ``tests/test_ad1180_agentic_disposition.py`` holds a golden copy and
asserts full string equality, so a future edit here has to be a deliberate one.

BF-727 (#1179): the prose used to enumerate the artifact formats --
``(a .docx, .xlsx, .pdf, chart, or archive)`` -- which made this the SECOND
declaration of the sandbox's capability surface. BF-726 had just derived the
first one (the ``run_python`` tool description) from real importability, and the
vessel restarted with that fix in place; the Captain then asked what the sandbox
could produce and was told "PDFs" and "matplotlib/seaborn plots", neither of
which is importable. The agent was not confabulating -- it was reading this
line. So the enumeration is gone and the prose now points at the schema, which
is the same move AD-1177 made for the tool list three lines above, applied to
the format list it left behind.

Deliberately NOT a second derived list: two derived lists can still disagree,
and the failure being repaired is precisely two declarations disagreeing. One
authority (the BF-726 description), one consumer (this prose).

The AD-1177 sentence also guarded only ONE direction of the drift -- "instead of
assuming a narrower set than you were given". The observed failure was the
opposite direction, so it now guards both. BF-726's own test asserts that same
symmetry for the description; the disposition needed it too.

Wording constraint (AD-957 / AD-596): the text must never match
``probos.cognitive.decomposer._CAPABILITY_GAP_RE``, or the AD-596 capability-gap
detector fires on a block that is affirming capability rather than reporting its
absence. That is asserted through the real ``is_capability_gap`` rather than a
re-implemented pattern.
"""

from __future__ import annotations

AGENTIC_DISPOSITION = (
    "\n\nActing directly this turn: you have a working loop that runs real "
    "tools before you reply, so do the work and report the result rather "
    "than only describing how it might be done. The tool schemas you were "
    "handed this turn are the authoritative list of what you hold -- read "
    "them and reach for whichever one fits the task, instead of assuming "
    "either a narrower or a wider set than you were given. When you are "
    "unsure what the ship offers right now, search_capabilities is itself a "
    "move worth making: discovering what is reachable grounds your reply in "
    "what is truly there this turn. run_python is your general-purpose "
    "instrument -- when a task fits none of the other tools, write and run "
    "Python to carry it: compute, transform data, drive a library, or "
    "produce a real downloadable file the Captain can open. Its schema "
    "names the libraries actually present this turn, so let that decide what "
    "you offer to build rather than what you would expect to be installed, "
    "then hand back the result. Be resourceful: take the "
    "direct route first, and when an attempt falls short, adjust it and go "
    "again before settling for an explanation. If something you need is "
    "missing -- a library, a file, a detail only the Captain holds -- say "
    "plainly what is needed and why, then carry the task as far as the "
    "tools at hand allow. All of this sits inside your orders and your "
    "granted authority: act freely within them, and bring anything that "
    "would exceed them to the Captain for approval rather than routing "
    "around it. Prefer finishing the task within this turn; describe an "
    "approach only when the Captain asks for the plan itself."
)

__all__ = ["AGENTIC_DISPOSITION"]
