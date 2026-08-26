# BF-811: the Dispatcher delegate — a tripwire, honestly labelled

**Issue:** #1275 · **Repo:** OSS, branch `main`, base `b4acdbfe`

## Scope, narrowed hard

The issue proposes a `typing.Protocol` for the delegate. **That was built and proven not to deliver
the property**, and this prompt exists mainly to record why, so it is not proposed a third time.

There is **no live bypass.** Production has exactly one `Dispatcher` construction and it passes the
real authorizing bus method:

```
startup/finalize.py:4718-4722
    dispatcher = Dispatcher(
        ...
        dispatch_async_fn=_intent_bus.dispatch_async,
```

AST enumeration during review found **27 `Dispatcher(...)` sites — 1 in `src/`, 26 in tests.** This
issue is about the constructor's public contract remaining bypassable, not about a hole anyone is
falling through today.

## Why the Protocol does not close it

Reproduced by execution: a delegate with the **exact** Protocol signature that simply ignored
authorization was constructed and run under a deny-all hook. `Dispatcher` returned `accepted=1`. The
intent reached the handler.

- The Protocol has **no runtime enforcement**, and this repository has **no type-check step in CI**.
  Nothing rejects a non-conforming delegate.
- Requiring a `raise_on_denial` parameter proves only that the delegate **can be asked** — not that
  it asks anyone. A callable signature cannot prove that authorization happened.

Shipping it would have added a Protocol, a guard and three tests, left the bypass exactly as open,
and read to a future maintainer as though it had been closed. That is worse than the honest
`Callable[..., Any]` it replaced. Patch preserved at `.git/W1_REJECTED.patch`.

## Required change — two small, honest things

### 1. Fail closed on a `None` return

`Dispatcher` currently treats a `None` return from `dispatch_async` as **admitted**, so the ~26
existing test doubles keep working while the real contract is pinned at the production seam.

Enumeration during the BF-815 review found no production wrapper, subclass, partial or monkeypatch
that can produce `None` — so this is not a live hole. It found **36 test-side replacements: 9
returning explicit `None`, 25 default `AsyncMock`s, and 2 implicit-`None` functions.** A default
`AsyncMock` returns a truthy mocked `.admitted`, so the gate silently accepts it (measured:
`bool(not mock.admitted)` is `False`).

Require a real `DispatchAdmission` (`types.py:105`). Fail closed on `None`. **Update all 36 doubles
to return real receipts** — otherwise a large green suite keeps hiding the contract mismatch, which
is the actual finding here.

Preserve `DispatchAdmission`'s stated semantics when writing the doubles: `admitted` means *the
delivery substrate accepted responsibility* — a JetStream ACK, a core-NATS publish, a cognitive-queue
enqueue, a scheduled handler task. It deliberately does **not** mean an agent processed the work.

### 2. Generalise the construction tripwire, and call it a tripwire

BF-789 shipped `test_the_wiring_really_passes_the_authorizing_bus_method`, which checks the one known
site. Generalise it to fail on **any new production `Dispatcher(...)` construction** whose delegate
expression does not end in `.dispatch_async`.

**State in the test's docstring, in plain words, that this is a regression tripwire and not a
security control.** It accepts any expression ending in `.dispatch_async` and alias constructions
evade it entirely. Its whole value is that a second production construction cannot be added
*silently*. A guard that reads as a gate is the failure mode this issue was opened about; do not
reproduce it in the guard meant to fix it.

Leave BF-789's `test_the_delegating_arm_contains_no_authorization_call` in place. It actively forbids
authorizing in the obvious spot, and that is **correct**: `IntentBus.dispatch_async` already evaluates
AD-698, so checking again would evaluate a stateful hook (rate limiter, quota) **twice per intent**,
silently halving its allowance with nothing reporting it.

## Do not build

- **Do not add the Protocol.** Proven inert. If a future AD wants it, it must first add a type-check
  step to CI — without that, it is a comment with syntax.
- **Do not authorize inside the delegating arm** (`activation/dispatcher.py:144-154`). Double-charges
  a stateful hook; BF-789's guard forbids it deliberately.
- **Do not centralize authorization in `Dispatcher` with a reusable receipt here.** That is the
  issue's option 1 and it is the right long-term shape — it dissolves the double-charge constraint
  instead of policing it, and it composes with the transport-side origin problem in #1253 (BF-789)
  and #1254 (BF-790). It is also a large refactor whose only benefit today is defending against a
  second `Dispatcher` construction that does not exist. **If it is built, it is its own AD**, and it
  should be motivated by the transport-origin work, not by this issue.
- **Do not require a concrete adapter type** (the issue's option 2). It couples `activation/` to a
  concrete `IntentBus`, inverting the dependency direction the layer rules require.
- **Do not touch `IntentBus.dispatch_async`** or the AD-698 hook.

## Tests

1. A delegate returning `None` is refused — `accepted` is 0 and the refusal is visible. Fails before
   the fix.
2. A default `AsyncMock` delegate is refused rather than silently accepted. This is the one that
   proves the 36 doubles were hiding the contract, and it should fail loudly across the suite until
   they are updated.
3. The generalised tripwire fires on a synthetic second production construction with a bare callable.
4. The tripwire does **not** fire on the existing legitimate site.
5. Production dispatch is unchanged end to end — same `accepted` counts for the same inputs.

Mutation-check items 1 and 3.

## Tracking

- Close **#1275** as built-narrowed, and say explicitly in the close comment: *the Protocol was
  rejected, the `None` contract and the tripwire were built, and centralized authorization remains
  open as a design item under the transport-origin work.*
- Cross-reference **#1279 (BF-815)** — the receipt this reuses.
- Note on **#1253 (BF-789)** and **#1254 (BF-790)** that centralized authorization is the shape that
  would dissolve their constraint too, so whoever takes those should cost it once for all three.

## Report back

- The number of test doubles actually updated — expect ~36, and report the real figure.
- **Anything in this prompt that turned out to be untrue.**

Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
