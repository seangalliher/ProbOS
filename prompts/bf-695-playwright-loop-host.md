# BF-695 — the browser tool cannot start under the Windows selector loop

**Status:** Ready for Builder.
**Severity:** AD-706's BrowserTool has **never functioned inside `probos serve` on
Windows**. Every browser feature — AD-706 actions, AD-1052a watch streaming,
AD-1052b bridge, AD-1052c input forwarding, AD-1158 session binding, AD-1160
`key_type`, AD-1161 Captain sessions — is unreachable on that platform.

---

## 1. Root cause

`src/probos/__main__.py:2456`:

```python
# Windows ProactorEventLoop doesn't support add_reader required by pyzmq.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
```

`SelectorEventLoop` on Windows does not implement subprocess transports —
`loop.subprocess_exec` raises `NotImplementedError`. `BrowserSession.start()`
(`session.py`) calls `async_playwright().start()`, whose transport does
`asyncio.create_subprocess_exec` to launch the Playwright **driver** process.

Observed live:

```
File "playwright/_impl/_transport.py", line 120, in connect
  self._proc = await asyncio.create_subprocess_exec(
File "asyncio/base_events.py", line 528, in _make_subprocess_transport
  raise NotImplementedError
NotImplementedError
```

This is a known, thrice-encountered constraint in this repo — see
`decisions-era-2-emergence.md` (ShellCommandAgent), BF-660 (git resolver),
BF-012 (Discord teardown). Each was solved by replacing async subprocess with
sync `subprocess.Popen` in an executor. **Playwright cannot use that escape
hatch**: its async API needs the event loop itself, not just a one-shot spawn.

## 2. Why NOT to fix it by changing the policy

Tempting and wrong. Switching the global policy to Proactor would change the loop
for NATS, aiosqlite, ChromaDB, uvicorn and every agent. This repo already
documents Proactor-specific failures — `prompts/archive/bf-250-251-proactive-test-windows-iocp-hang.md`
is literally "Proactive Loop Test Hangs on Windows ProactorEventLoop", and BF-250
traced a hang to `_overlapped.GetQueuedCompletionStatus`. Trading one platform
bug for a different one across the whole runtime is not an improvement.

`pyzmq` is still a declared dependency (`pyproject.toml`) and
`federation/transport.py` still imports it, so the original AD-108 reason has not
lapsed either.

**Isolate the incompatibility to the component that has it.** That is what the
three prior fixes did, and it is what this one must do.

## 3. The fix — a dedicated Proactor loop host

Add a **Playwright host**: a single background thread running its own
`ProactorEventLoop`, owning every Playwright object. Public `BrowserTool` /
`BrowserSession` coroutines marshal onto it and await the result from the caller's
loop.

Sketch (the Builder owns the final shape):

```python
class _PlaywrightHost:
    """Owns a Proactor loop on a private thread; all Playwright work runs here."""
    def start(self) -> None: ...          # idempotent, lazy
    async def run(self, factory: Callable[[], Coroutine[Any, Any, T]]) -> T: ...
    async def aclose(self) -> None: ...
```

- `run()` submits via `asyncio.run_coroutine_threadsafe(factory(), self._loop)`
  and awaits `asyncio.wrap_future(fut)` so the **caller's** loop is never blocked.
- Take a **factory**, not a coroutine object, so the coroutine is created on the
  host loop's thread. Creating it caller-side and shipping it across is the kind
  of subtlety that works until it doesn't.
- **Activate only when needed.** If the running loop already supports subprocess
  (any non-Windows platform, or Windows-on-Proactor), do **not** start a thread —
  call straight through. One predicate, evaluated once, with the no-op path
  byte-identical to today. State the predicate explicitly rather than testing
  `sys.platform` alone.

### 3.1 The boundary must be COMPLETE — marshal at `BrowserSession.page`

**ARCHITECT DECISION (amended after Builder review).** An earlier draft of this
spec said "marshal at the dispatch point in `BrowserTool.invoke`". That is
**wrong** and is superseded. The Builder proved why, empirically:

- `invoke`'s step-6 dispatch has **four** branches, and two of them do more than
  Playwright. `action_verify` and `action_compute_use_click` also call
  `store.write()` and `llm_client.complete()`.
- `FilesystemAttachmentStore` holds an `asyncio.Lock`; `LLMClient` holds an
  `asyncio.Lock`, three `asyncio.Semaphore`s and `httpx.AsyncClient` pools — all
  bound to the **main** loop on first contended use. Cross-loop use raises
  `RuntimeError: ... is bound to a different event loop` (verified on this
  interpreter).
- Both call sites are already inside `except Exception:` honest-degrade blocks,
  so that `RuntimeError` would be **swallowed into a permanent `ok: None` /
  `skipped_reason`** — silent, Windows-only, forever. The exact failure shape
  this BF exists to remove.
- The AD-1052a MJPEG streamer never passes through `invoke` at all, so dispatch-
  point marshalling would not cover it regardless.

**Therefore: `BrowserSession.page` returns a marshalling proxy when the host is
active.** `host.run(...)` additionally wraps `start()` / `connect()` / `stop()`
explicitly, since those create and destroy the objects themselves.

This covers every Playwright touch — actions, compute_use, credentials, and the
streamer — with **zero call-site edits**, and leaves `llm_client` and
`AttachmentStore` on the caller's loop where they belong.

The decisive property is failure **direction**. Call-site marshalling fails
*open*: a future handler that adds `await page.something_new()` is a silent
Windows-only break. A proxy fails *closed*: there is no site to forget.

### 3.1a Proxy requirements — transitivity is the risk

A proxy is only safe if it is **transitive**. Anything returned from a host-bound
object that is itself host-bound must also be wrapped, or the same cross-loop bug
reappears one level deeper. Handle at minimum:

- **async methods** (`page.click`, `page.screenshot`, `page.title`,
  `page.evaluate`, `page.fill`, …) → marshal onto the host loop.
- **sub-objects reached by sync attribute** — `page.mouse`, `page.keyboard` →
  return a proxy, never the raw object.
- **async context managers** — `async with page.expect_download()` whose result
  is then `await`ed (`await dl_info.value`) → both the context manager and the
  yielded object need proxying.
- **sync properties returning plain data** — `page.url`, `page.viewport_size` →
  pass through unwrapped.

**Fail closed on the unknown.** If the proxy meets an attribute whose kind it
does not recognise, it must **raise or wrap — never silently return the raw
host-bound object**. A permissive default reintroduces exactly the bug class
being fixed, and it will surface only on Windows, only at runtime.

### 3.1b The predicate

Use the Builder's capability check, not `sys.platform`:

```python
type(loop)._make_subprocess_transport is BaseEventLoop._make_subprocess_transport
```

Verified `False` for `ProactorEventLoop` (capable), `True` for the Windows
selector loop (incapable — the base raises `NotImplementedError`).

**Note for tests:** `asyncio_mode = "auto"` with no conftest policy override means
the suite already runs on `ProactorEventLoop`, so the predicate reports "capable"
and every existing test takes the passthrough path unchanged. The host path
therefore needs tests that **force** it explicitly — it will not be exercised by
accident.

### 3.2 Lifecycle

- Thread is a daemon, started lazily on first need, stopped in `BrowserTool.stop()`.
- `aclose()` must stop the loop and join the thread with a timeout, then log if
  the thread outlived it. Do not leave a non-daemon thread able to block exit.
- Handle `asyncio.CancelledError` across the marshal boundary: a cancelled caller
  should cancel the host-side future, not orphan it.
- Exceptions must propagate to the caller with their original type and traceback.

## 4. Acceptance criteria

- `tests/test_bf695_playwright_host.py`.
- A test proving the **predicate**: on a loop that supports subprocess, no host
  thread is created and the call path is direct.
- A test proving marshalling works: a coroutine submitted through the host runs on
  a *different* loop than the caller's, and its result returns to the caller.
- Exception propagation across the boundary preserves type and message.
- Cancellation across the boundary cancels the host-side work.
- `aclose()` joins the thread; a second `aclose()` is a no-op.
- A test asserting **every** Playwright-touching public entry point routes through
  the host — enumerate them explicitly so a future entry point that forgets is a
  visible omission rather than a silent Windows-only break.
- Existing browser suites stay green unchanged — the fake-page tests must not
  need modification, which is the strongest evidence the boundary is transparent.
- **Full suite.** Baseline **21,919 passed, 34 skipped**. Report the count.
- **Verify all changes comply with the Engineering Principles in
  `.github/copilot-instructions.md`** — particularly Async Discipline (hold task
  references, handle cancellation, `async def stop()` for every `async def start()`).

## 5. Do NOT

- Do not change the global event loop policy or touch `__main__.py`.
- Do not modify `actions.py` handler bodies — marshal at the dispatch point.
- Do not change any action's behaviour, tier, or schema.
- Do not "fix" `_action_state`'s `list_elements` guard (BF-692, separate).
- Do not add a config flag. This is a correctness fix, not a feature; a flag would
  imply the broken path is a legitimate choice.

## 6. Commit

One commit. `git commit -F <file>`, never inline `-m`. **Do not `git add
config/system.yaml`** — skip-worktree (`S`). Do not push; the Architect reviews.
