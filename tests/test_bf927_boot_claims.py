"""BF-927 (#1657): what the ship says about its security and verification services matches
whether production code calls them.

Each claim (a boot-log line in ``startup/finalize.py``, a config model's reference summary, a
roadmap status, a docstring) carries ``NOT_INVOKED`` exactly when the services it names have no
production caller. An entry method's callers are found by tracing each instance over
``src/probos`` with the AST from its construction or a parameter annotated with its class, so a
``.check(`` or ``.scan(`` on an untraced receiver does not count; a module-level function
(``vote_on_intent``) is matched by its name (approximation (d)). The pin
fails in both directions: a service that gains a caller while its claim still says it is not
invoked, and a claim that drops the phrase (or says "wired") over a service nothing calls.
``RedTeamLead``, which does run, is the invoked control on the real tree.

What the resolver cannot see, by construction: a method name built at run time
(``getattr(obj, name)()`` with a computed ``name``) or looked up through the instance's own
methods (``holder.__getattribute__("check")()``); a holder reached through the ``__self__`` of a
non-entry bound method handed on (``sink(holder.reset)``, ``sink(holder.__call__)``: a holder
value is not a callable, so ``__call__`` is not dropped from it); an instance or a bound entry
method kept in a
container, a tuple target, ``setattr`` or a ``return``; an instance bound by ``:=``, ``for`` or
``with ... as``, or reached through an expression (``(a or holder).check()``, a conditional); an
instance returned from a function; a local captured by a nested function; a builtin replaced at
run time; calls inside the service's own module, except the declared ``via`` delegation; callers
in ``ui/``, ``scripts/``, tests or a plugin loaded at run time.

A call is ``holder.check(...)``, ``holder.check.__call__(...)`` or ``getattr(holder, "check")(...)``
with a literal name. Wherever the resolver reads a callable (a call's own, the lookup inside a
``getattr(...)``, an argument or value tested as an entry method or as the module function),
``x.__call__`` is read as ``x``, every layer of it, so ``x.__call__(...)`` classifies exactly like
``x(...)`` (A5). A
hand-off it cannot type is an escape: a holder passed as an argument (``**holder`` included), or
an entry method passed or assigned uncalled (``sink(holder.check)``, ``hook = getattr(holder,
"check")``). ``getattr`` and the other ``_NON_INVOKING`` names count only as the builtin: a bare
name, called directly or through its own ``__call__``, that its module binds nowhere (no ``def``,
assignment, parameter or import
of it, and no star import; a binding in any function distrusts it in the whole module; a type
parameter is not seen, approximation (e)). Any other spelling (``lookup.getattr(...)``,
``builtins.getattr``, a shadowing ``def getattr``) is an ordinary callable, so a holder passed to
it, or a holder attribute it names with a literal (``lookup.getattr(runtime, "gate")``), is an
escape, never a call. Each of these holds through ``__call__`` alike: ``getattr.__call__(runtime,
"gate")`` reads the holder as the builtin does, ``getattr.__call__(holder, "check")()`` is a call,
and ``lookup.getattr.__call__(runtime, "gate")`` is an escape. For a service with no
resolved caller an escape fails the test rather than counting as "not invoked"; for an invoked
service it changes nothing, because it could only add callers.

Known approximations (BF-926/927 review rounds 1 to 3; follow-up R10). Directions are stated
against a "not invoked" claim: a silent one can miss a caller, which keeps such a claim green; a
loud one adds a false caller or escape, which fails it (a false caller could also keep
``RedTeamLead``'s invoked claim green after its real caller went). The "cannot see" forms above go
either way: most can hide a caller; a traced holder or entry passed directly to ``setattr`` or a
container constructor (``dict(gate=holder)``) is an escape; a builtin replaced at run time can add
a false caller or invoke an entry behind an exempt name.
(a) Silent: a typed parameter is keyed by its callable's short name (the class for ``__init__``)
and the parameter name, so a keyword hand-off to another callable with the same two names is
exempt as if typed.
(b) Loud: a holder attribute is matched by its name, not its owner, so once ``runtime.gate`` holds
the service any ``other.gate.check()`` counts as a call.
(c) Loud: a positional argument is an escape even into a parameter annotated with the class (spell
a typed hand-off as a keyword).
(d) A module-level function is matched by its short name: loud, any ``x.vote_on_intent()`` counts
as a call; silent, a call through an import alias (``from ... import vote_on_intent as vote``) is
not followed.
(e) Loud: a Python 3.12 type parameter (``def f[getattr]()``) is not collected as a binding, so a
builtin of that name stays trusted in its module and can count a false caller.
"""

from __future__ import annotations

import ast
import functools
import importlib
import inspect
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from probos.config import GroundTruthConfig, SystemConfig

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC_ROOT = _REPO_ROOT / "src" / "probos"
_FINALIZE = _SRC_ROOT / "startup" / "finalize.py"
_ERA5 = "docs/development/roadmap-era-5-completed.md"

NOT_INVOKED = "built, not invoked"
_ACTIVE_WORDS = ("wired", "initialized", "active", "enforc")
_LOG_METHODS = frozenset({"debug", "info", "warning", "error", "exception", "critical"})
_NON_INVOKING = frozenset({"getattr", "hasattr", "isinstance", "id", "type", "repr", "bool", "len", "str"})
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z_0-9]*")


@dataclass(frozen=True)
class Service:
    module: str
    name: str
    entries: tuple[str, ...]  # methods whose call invokes it; () for a module-level function
    via: tuple[str, ...] = ()  # services that invoke it from inside its own module


@dataclass(frozen=True)
class Site:
    path: str
    line: int
    scope: str


@dataclass
class Resolution:
    state: str  # "invoked", "not invoked" or "escapes"
    calls: list[Site] = field(default_factory=list)
    escapes: list[Site] = field(default_factory=list)


@dataclass(frozen=True)
class _Module:
    name: str
    path: str
    tree: ast.Module
    bound: frozenset[str]  # the names the module binds, in any scope (A3; type parameters are not collected, (e))


SERVICES: tuple[Service, ...] = (
    Service("probos.security.red_team_lead", "RedTeamLead", ("start", "run_campaign_now")),
    Service("probos.security.input_validator", "InputValidator", ("check",)),
    Service("probos.security.threat_detector", "ThreatDetector", ("scan",)),
    Service("probos.security.trust_integrity", "TrustIntegrityMonitor", ("analyze",)),
    Service("probos.governance.risk_tiers", "ActionRiskRegistry", ("check_authorization",)),
    Service("probos.mesh.disclosure", "DisclosureRouter", ("check_recipients", "filter_permitted")),
    Service("probos.consensus.quorum", "vote_on_intent", ()),
    Service("probos.security.autonomy_boundaries", "BoundaryViolationDetector", ("scan",)),
    Service("probos.security.classification", "ClassificationGate", ("check_disclosure",)),
    Service("probos.cognitive.validation_framework", "ReconciliationEscalator", ("reconcile",)),
    Service("probos.cognitive.ground_truth", "GroundTruthRejectionGate", ("evaluate",)),
    Service("probos.cognitive.ground_truth", "GroundTruthVerifier", ("verify",), via=("GroundTruthRejectionGate",)),
)
# Measured, not wished: a change here must come with the caller that justifies it.
EXPECTED_STATE = {service.name: "not invoked" for service in SERVICES} | {"RedTeamLead": "invoked"}


@dataclass(frozen=True)
class Claim:
    key: str
    services: tuple[str, ...]
    boot_prefixes: tuple[str, ...] = ()
    documents: tuple[str, ...] = ()  # "module:qualname"; a class is judged by its reference summary
    roadmap: tuple[tuple[str, str], ...] = ()  # (file, the start of the entry's line)


CLAIMS: tuple[Claim, ...] = (
    Claim("AD-455-red-team", ("RedTeamLead",), ("AD-455: RedTeamLead",)),
    Claim(
        "AD-455-screening", ("InputValidator", "ThreatDetector", "TrustIntegrityMonitor"), ("AD-455: InputValidator",),
        ("probos.config:SecurityConfig",), ((_ERA5, "**AD-455: Security Team"),),
    ),
    Claim("AD-676", ("ActionRiskRegistry",), ("AD-676:",), ("probos.config:RiskTierConfig",), ((_ERA5, "**AD-676: Action Risk Tiers**"),)),
    Claim("AD-679", ("DisclosureRouter",), ("AD-679:",), (), ((_ERA5, "**AD-679: Selective Disclosure Routing**"),)),
    Claim("AD-753", ("vote_on_intent",), (), ("probos.consensus.quorum:vote_on_intent",), (("docs/development/roadmap.md", "| AD-753 |"),)),
    Claim(
        "AD-511", ("BoundaryViolationDetector",), ("AD-511:",), ("probos.config:AutonomyBoundariesConfig",),
        ((_ERA5, "**AD-511: Agent Autonomy Boundaries"),),
    ),
    Claim(
        "AD-530", ("ClassificationGate",), ("AD-530:",), ("probos.config:ClassificationGateConfig",),
        ((_ERA5, "**AD-530: Information Classification Enforcement**"),),
    ),
    Claim(
        "AD-451", ("ReconciliationEscalator",), ("AD-451:",), ("probos.config:ValidationFrameworkConfig",),
        ((_ERA5, "**AD-451: Validation Framework Hardening**"),),
    ),
    Claim("AD-528b", ("GroundTruthRejectionGate",), ("AD-528b:",)),
    Claim(
        "AD-528", ("GroundTruthVerifier",), ("AD-528:",), ("probos.config:GroundTruthConfig",),
        ((_ERA5, "**AD-528: Ground-Truth Task Verification**"),),
    ),
)
BOOT_CLAIMS = tuple(claim for claim in CLAIMS if claim.boot_prefixes)
DOC_CLAIMS = tuple(claim for claim in CLAIMS if claim.documents or claim.roadmap)


# --- the resolver -------------------------------------------------------------------------------


def _parse_package(root: Path, package: str) -> tuple[_Module, ...]:
    modules = []
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root)
        parts = [package, *relative.with_suffix("").parts]
        if parts[-1] == "__init__":
            parts.pop()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        modules.append(_Module(".".join(parts), relative.as_posix(), tree, _bound_names(tree)))
    return tuple(modules)


def _index(modules: tuple[_Module, ...]) -> tuple[list, list, list]:
    """Assignments, calls and functions of every module, each with its enclosing scope."""
    assigns: list = []
    calls: list = []
    functions: list = []
    for module in modules:
        stack: list[tuple[ast.AST, str]] = [(module.tree, "")]
        while stack:
            node, scope = stack.pop()
            for child in ast.iter_child_nodes(node):
                inner = scope
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    if not isinstance(child, ast.ClassDef):
                        functions.append((module, scope, child))
                    inner = f"{scope}.{child.name}" if scope else child.name
                elif isinstance(child, (ast.Assign, ast.AnnAssign)):
                    assigns.append((module, scope, child))
                elif isinstance(child, ast.Call):
                    calls.append((module, scope, child))
                stack.append((child, inner))
    return assigns, calls, functions


def _callee(expr: ast.AST | None) -> str:
    if isinstance(expr, ast.Name):
        return expr.id
    if isinstance(expr, ast.Attribute):
        return expr.attr
    return ""


def _plain(func: ast.AST | None) -> ast.AST | None:
    """The callable an expression names: ``x.__call__`` is ``x``, so every trailing ``.__call__`` is dropped (A5)."""
    while isinstance(func, ast.Attribute) and func.attr == "__call__":
        func = func.value
    return func


def _bound_names(tree: ast.Module) -> frozenset[str]:
    """The names the module binds, in any scope (a star import adds ``"*"``): a builtin of that name is not trusted there.

    A 3.12 type parameter (``def f[getattr]()``) is not collected: approximation (e).
    """
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.ExceptHandler, ast.MatchAs, ast.MatchStar)):
            names.add(node.name or "")
        elif isinstance(node, ast.arg):
            names.add(node.arg)
        elif isinstance(node, ast.Name) and not isinstance(node.ctx, ast.Load):
            names.add(node.id)
        elif isinstance(node, ast.alias):
            names.add(node.asname or node.name.partition(".")[0])
        elif isinstance(node, ast.MatchMapping) and node.rest:
            names.add(node.rest)
    return frozenset(names)


def _builtin(func: ast.AST, bound: frozenset[str]) -> str:
    """The builtin a call's ``func`` names, or ``""``: only a bare name its module never binds is trusted."""
    name = _callee(func)
    return name if isinstance(func, ast.Name) and name not in bound and "*" not in bound else ""


def _resolve_function(service: Service, index: tuple[list, list, list]) -> tuple[list[Site], list[Site]]:
    assigns, calls, _ = index
    sites: list[Site] = []
    escapes: list[Site] = []
    for module, scope, node in calls:
        if module.name == service.module:
            continue
        if _callee(_plain(node.func)) == service.name:
            sites.append(Site(module.path, node.lineno, scope))
        handed = [*node.args, *(keyword.value for keyword in node.keywords)]
        if any(isinstance(_plain(arg), (ast.Name, ast.Attribute)) and _callee(_plain(arg)) == service.name for arg in handed):
            escapes.append(Site(module.path, node.lineno, scope))  # the function handed on as a value
    for module, scope, node in assigns:
        value = node.value
        if module.name != service.module and isinstance(_plain(value), (ast.Name, ast.Attribute)) and _callee(_plain(value)) == service.name:
            escapes.append(Site(module.path, node.lineno, scope))  # the function aliased
    return sites, escapes


def _resolve(service: Service, index: tuple[list, list, list]) -> tuple[list[Site], list[Site]]:
    """Calls of the service's entry methods on a resolved receiver, and untyped hand-offs."""
    if not service.entries:
        return _resolve_function(service, index)
    assigns, calls, functions = index
    bound = {module.name: module.bound for module, _, _ in calls}  # a lookup is a call, so its module is here
    attr_holders: set[str] = set()
    name_holders: set[tuple[str, str, str]] = set()
    typed: set[tuple[str, str]] = set()  # (callable, parameter) annotated with the service class

    for module, scope, node in functions:
        inner = f"{scope}.{node.name}" if scope else node.name
        owner = scope.rsplit(".", 1)[-1] if node.name == "__init__" and scope else node.name
        for arg in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs):
            if arg.annotation is not None and service.name in _IDENTIFIER.findall(ast.unparse(arg.annotation)):
                typed.add((owner, arg.arg))
                if module.name != service.module:
                    name_holders.add((module.name, inner, arg.arg))

    def is_read(module: str, scope: str, expr: ast.AST) -> bool:
        if isinstance(expr, ast.Name):
            return (module, scope, expr.id) in name_holders
        if isinstance(expr, ast.Attribute):
            return expr.attr in attr_holders
        if isinstance(expr, ast.Call) and _builtin(_plain(expr.func), bound[module]) == "getattr" and len(expr.args) >= 2:
            key = expr.args[1]
            return isinstance(key, ast.Constant) and key.value in attr_holders
        return False

    def is_entry(module: str, scope: str, expr: ast.AST) -> bool:
        """An entry method on a resolved receiver, called or not: ``holder.check`` or the builtin ``getattr(holder, "check")``."""
        expr = _plain(expr)  # ``sink(holder.check.__call__)`` hands on ``holder.check`` (A5)
        if isinstance(expr, ast.Attribute):
            return expr.attr in service.entries and is_read(module, scope, expr.value)
        if isinstance(expr, ast.Call) and _builtin(_plain(expr.func), bound[module]) == "getattr" and len(expr.args) >= 2:
            key = expr.args[1]
            return isinstance(key, ast.Constant) and key.value in service.entries and is_read(module, scope, expr.args[0])
        return False

    changed = True
    while changed:
        changed = False
        for module, scope, node in assigns:
            value = node.value
            if module.name == service.module or value is None:
                continue
            if not (_callee(_plain(getattr(value, "func", None))) == service.name or is_read(module.name, scope, value)):
                continue
            for target in node.targets if isinstance(node, ast.Assign) else [node.target]:
                if isinstance(target, ast.Name) and (module.name, scope, target.id) not in name_holders:
                    name_holders.add((module.name, scope, target.id))
                    changed = True
                elif isinstance(target, ast.Attribute) and target.attr not in attr_holders:
                    attr_holders.add(target.attr)
                    changed = True

    sites: list[Site] = []
    escapes: list[Site] = []
    for module, scope, node in calls:
        if module.name == service.module:
            continue
        func = _plain(node.func)  # every check below reads ``x.__call__(...)`` as ``x(...)`` (A5)
        if is_entry(module.name, scope, func):
            sites.append(Site(module.path, node.lineno, scope))  # a resolved call
        callee = _callee(func)
        key = node.args[1] if callee == "getattr" and len(node.args) >= 2 else None
        if isinstance(key, ast.Constant) and key.value in attr_holders and _builtin(func, bound[module.name]) != "getattr":
            escapes.append(Site(module.path, node.lineno, scope))  # a getattr that may not be the builtin
        if _builtin(func, bound[module.name]) in _NON_INVOKING:
            continue
        handed = [*node.args, *(keyword.value for keyword in node.keywords if (callee, keyword.arg) not in typed)]
        if any(is_read(module.name, scope, arg) for arg in handed):
            escapes.append(Site(module.path, node.lineno, scope))  # an untyped hand-off
        if any(is_entry(module.name, scope, arg) for arg in (*node.args, *(keyword.value for keyword in node.keywords))):
            escapes.append(Site(module.path, node.lineno, scope))  # an entry method handed on
    for module, scope, node in assigns:
        if module.name != service.module and node.value is not None and is_entry(module.name, scope, node.value):
            escapes.append(Site(module.path, node.lineno, scope))  # an entry method aliased
    return sites, escapes


def _blocked(services: tuple[Service, ...], invoked: set[str]) -> tuple[str, ...]:
    return tuple(f"{service.name}.{entry}" for service in services if service.name not in invoked for entry in service.entries)


def _inside(scope: str, blocked: tuple[str, ...]) -> bool:
    return any(scope == entry or scope.startswith(entry + ".") for entry in blocked)


def _classify(modules: tuple[_Module, ...], services: tuple[Service, ...]) -> dict[str, Resolution]:
    index = _index(modules)
    raw = {service.name: _resolve(service, index) for service in services}
    invoked: set[str] = set()
    changed = True
    while changed:
        changed = False
        blocked = _blocked(services, invoked)
        for service in services:
            sites, _ = raw[service.name]
            reached = any(not _inside(site.scope, blocked) for site in sites) or any(name in invoked for name in service.via)
            if service.name not in invoked and reached:
                invoked.add(service.name)
                changed = True
    blocked = _blocked(services, invoked)
    result: dict[str, Resolution] = {}
    for service in services:
        sites, escapes = raw[service.name]
        open_escapes = [site for site in escapes if not _inside(site.scope, blocked)]
        if service.name in invoked:
            state = "invoked"
        elif open_escapes:
            state = "escapes"
        else:
            state = "not invoked"
        result[service.name] = Resolution(state, sites, open_escapes)
    return result


@functools.lru_cache(maxsize=1)
def _production_states() -> dict[str, Resolution]:
    """Parsed and resolved once per process; every test only reads the result."""
    return _classify(_parse_package(_SRC_ROOT, "probos"), SERVICES)


def _quiet(claim: Claim) -> bool:
    """True when every service of the claim is not invoked; a mixed claim must be split."""
    states = {_production_states()[name].state for name in claim.services}
    assert "escapes" not in states, f"{claim.key}: classify the escape(s) before wording the claim"
    assert len(states) == 1, f"{claim.key}: its services are in different states {states}; split the claim"
    return states == {"not invoked"}


def _finalize_log_texts(prefixes: tuple[str, ...]) -> list[str]:
    tree = ast.parse(_FINALIZE.read_text(encoding="utf-8"))
    texts = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.args):
            continue
        logger_call = node.func.attr in _LOG_METHODS and isinstance(node.func.value, ast.Name) and node.func.value.id == "logger"
        first = node.args[0]
        if logger_call and isinstance(first, ast.Constant) and isinstance(first.value, str) and first.value.startswith(prefixes):
            texts.append(first.value)
    return texts


# --- the tests ----------------------------------------------------------------------------------


@pytest.mark.parametrize("service", SERVICES, ids=lambda service: service.name)
def test_each_service_state_is_resolved(service: Service) -> None:
    resolution = _production_states()[service.name]

    assert resolution.state == EXPECTED_STATE[service.name], (resolution.calls, resolution.escapes)


_FIXTURE = {
    "svc.py": "class Gate:\n    def check(self):\n        return True\n",
    "boot.py": "from pkg.svc import Gate\n\n\ndef boot(runtime):\n    gate = Gate()\n    runtime.gate = gate\n",
    "decoy.py": "def other(thing):\n    return thing.check()\n",
}
_FIXTURE_CASES = {
    "a decoy only": ({}, "not invoked"),
    "a resolved caller": ({"user.py": "def use(runtime):\n    held = getattr(runtime, 'gate', None)\n    return held.check()\n"}, "invoked"),
    "a typed hand-off": (
        {
            "holder.py": (
                "from pkg.svc import Gate\n\n\nclass Holder:\n    def __init__(self, gate: Gate):\n"
                "        self._held = gate\n\n    def run(self):\n        return self._held.check()\n"
            ),
            "wire.py": "from pkg.holder import Holder\n\n\ndef wire(runtime):\n    return Holder(gate=runtime.gate).run()\n",
        },
        "invoked",
    ),
    "an untyped hand-off": ({"hand.py": "def hand(runtime, sink):\n    sink(runtime.gate)\n"}, "escapes"),
    "a literal getattr call": ({"lit.py": "def use(runtime):\n    return getattr(runtime.gate, 'check')()\n"}, "invoked"),
    "an entry handed on": ({"cb.py": "def wire(runtime, bus):\n    bus.subscribe(runtime.gate.check)\n"}, "escapes"),
    "an entry aliased": ({"alias.py": "def wire(runtime):\n    hook = runtime.gate.check\n    return hook\n"}, "escapes"),
    "an entry called through __call__": ({"dunder.py": "def use(runtime):\n    return runtime.gate.check.__call__()\n"}, "invoked"),
    "a qualified getattr": ({"qual.py": "def use(runtime, lookup):\n    return lookup.getattr(runtime.gate, 'check')()\n"}, "escapes"),
    "a shadowed getattr": (
        {"shadow.py": "def getattr(value, name):\n    return lambda: None\n\n\ndef use(runtime):\n    return getattr(runtime.gate, 'check')()\n"},
        "escapes",
    ),
    "a getattr parameter reading a holder": (
        {"param.py": "def use(runtime, getattr):\n    held = getattr(runtime, 'gate')\n    return held.check()\n"},
        "escapes",
    ),
    "a qualified hasattr": ({"probe.py": "def use(runtime, obj):\n    return obj.hasattr(runtime.gate, 'check')\n"}, "escapes"),
    "a getattr called through its own __call__": ({"gcall.py": "def use(runtime):\n    return getattr.__call__(runtime.gate, 'check')()\n"}, "invoked"),
    "a holder read through the builtin getattr's __call__": (
        {"bcall.py": "def use(runtime):\n    held = getattr.__call__(runtime, 'gate')\n    return held.check()\n"},
        "invoked",
    ),
    "a holder read through a qualified getattr's __call__": (
        {"qcall.py": "def use(runtime, lookup):\n    held = lookup.getattr.__call__(runtime, 'gate')\n    return held.check()\n"},
        "escapes",
    ),
    "an unrelated typed __call__": (
        {
            "typed.py": "from pkg.svc import Gate\n\n\nclass Unrelated:\n    def __call__(self, *, gate: Gate):\n        pass\n",
            "kw.py": "def use(runtime, lookup):\n    return lookup.hasattr.__call__(gate=runtime.gate)\n",
        },
        "escapes",
    ),
    "an entry handed on through __call__": ({"cbcall.py": "def wire(runtime, bus):\n    bus.subscribe(runtime.gate.check.__call__)\n"}, "escapes"),
}


@pytest.mark.parametrize("case", sorted(_FIXTURE_CASES))
def test_the_resolver_tells_a_caller_from_a_decoy_and_an_escape(case: str, tmp_path: Path) -> None:
    extra, expected = _FIXTURE_CASES[case]
    package = tmp_path / "pkg"
    package.mkdir()
    for name, text in {**_FIXTURE, **extra}.items():
        (package / name).write_text(text, encoding="utf-8")

    resolution = _classify(_parse_package(package, "pkg"), (Service("pkg.svc", "Gate", ("check",)),))["Gate"]

    assert resolution.state == expected


@pytest.mark.parametrize("claim", BOOT_CLAIMS, ids=lambda claim: claim.key)
def test_each_boot_line_says_what_its_services_do(claim: Claim) -> None:
    quiet = _quiet(claim)
    texts = _finalize_log_texts(claim.boot_prefixes)

    assert texts, f"no finalize.py log call starts with {claim.boot_prefixes}"
    for text in texts:
        assert (NOT_INVOKED in text) is quiet, text
        if quiet:
            assert not any(word in text.lower() for word in _ACTIVE_WORDS), text


@pytest.mark.parametrize("claim", DOC_CLAIMS, ids=lambda claim: claim.key)
def test_each_description_says_what_its_services_do(claim: Claim) -> None:
    quiet = _quiet(claim)
    for target in claim.documents:
        module_name, _, qualname = target.partition(":")
        documented = getattr(importlib.import_module(module_name), qualname)
        doc = inspect.getdoc(documented) or ""
        text = doc.split("\n\n")[0] if inspect.isclass(documented) else doc  # the reference shows a model's summary
        assert (NOT_INVOKED in text) is quiet, f"{target}: {text!r}"
    for relative, head in claim.roadmap:
        lines = [line for line in (_REPO_ROOT / relative).read_text(encoding="utf-8").splitlines() if line.startswith(head)]
        assert len(lines) == 1, f"{relative}: {len(lines)} entries start {head!r}"
        assert (NOT_INVOKED in lines[0][:400]) is quiet, lines[0][:400]


@pytest.mark.asyncio
async def test_the_booted_vessel_prints_the_reworded_lines(tmp_path: Path) -> None:
    """The production path: a real boot prints each line, and its wording matches the callers."""
    from probos.runtime import ProbOSRuntime

    records: list[str] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record.getMessage())

    finalize_logger = logging.getLogger("probos.startup.finalize")
    handler, previous_level = _Capture(level=logging.INFO), finalize_logger.level
    finalize_logger.addHandler(handler)
    finalize_logger.setLevel(logging.INFO)
    # active_rejection_enabled is set only so the AD-528b line prints; no tracked config sets it
    # (system.yaml:1335 is false), and the gate it builds is never called, which is the claim.
    rt = ProbOSRuntime(config=SystemConfig(ground_truth=GroundTruthConfig(active_rejection_enabled=True)), data_dir=tmp_path)
    try:
        await rt.start()
    finally:
        await rt.stop()
        finalize_logger.removeHandler(handler)
        finalize_logger.setLevel(previous_level)

    for claim in BOOT_CLAIMS:
        printed = [message for message in records if message.startswith(claim.boot_prefixes)]
        assert printed, f"the boot printed no line starting {claim.boot_prefixes}"
        for message in printed:
            assert (NOT_INVOKED in message) is _quiet(claim), message
