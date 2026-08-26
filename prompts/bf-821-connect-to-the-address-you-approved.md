# BF-821: connect to the address you approved

**Issue:** [#1285](https://github.com/seangalliher/ProbOS/issues/1285)
**Status:** Ready to build
**Branch base:** `main` @ `39373c76`
**Dependencies:** BF-743 (`security/url_guard.py`), BF-819 (per-hop redirect validation), AD-270 (429 retry). All shipped.
**Estimated new tests:** 16–20 in `tests/test_bf821_pinned_address.py`
**No AD.** The property "connect to the address you approved" is the stated intent of the BF-743 floor, not a new architectural stance. Every choice below is forced by an enumerated consumer contract, not chosen. Nothing here needs a standing decision recorded.

---

## 1. Problem

`check_resolved_address` (`src/probos/security/url_guard.py:75-105`) resolves the hostname, judges every address it maps to, then **discards the addresses** and returns a verdict on the URL *string*. `httpx` resolves the same name again when it connects. Two lookups, no guarantee they agree.

Reproduced end-to-end on `39373c76` — `socket.getaddrinfo` stubbed to answer public on lookup 1 and `127.0.0.1` on every lookup after, against a real `HTTPServer` on loopback:

```
loopback victim listening on 127.0.0.1:56264
CONTROL  guard on a loopback-first name -> 'Blocked private/reserved IP: 127.0.0.1'
PREMISE  guard on the FIRST (public) answer -> None
fetch     -> HTTP 200 body='LOOPBACK REACHED'
total lookups for rebind.test: 2
loopback server hits: ['/x']
REPRODUCED: the guard approved a public address and the connection landed on 127.0.0.1.
```

The CONTROL line is load-bearing: it proves the stub actually reaches the guard, so "approved" is a real approval and not a probe that never fired. Reproduce the same way, or the green result you get after the fix is indistinguishable from a stub that never ran.

The AD-270 429 retry (`http_fetch.py:471-479`) re-requests without repeating validation, adding one more lookup to the window.

BF-819's docstring at `http_fetch.py:407-411` already names this gap and declines to claim it. That text is now false-by-fix and must be updated in Section 4.

---

## 2. The contract decision, made from the consumer table

The issue asks for the approved address to be "returned alongside the verdict." The question is *where*. Enumerated every consumer before choosing — the table decides this, not taste.

| Consumer | Anchor | What it needs | Effect of widening `validate_public_url`'s return |
|---|---|---|---|
| `HttpFetchAgent._validate_url` | `http_fetch.py:265` | reason only | — |
| `HttpFetchAgent._fetch_url` (pre-coalescing gate) | `http_fetch.py:325` | reason only | — |
| `HttpFetchAgent._follow_and_fetch` (per-hop) | `http_fetch.py:511` | reason **and the address** | this is the one caller that needs more |
| refusal-string equality assertions | `test_bf743_browser_ssrf_floor.py:95,105,110,115,116,128,140,148,153` | `str \| None` exactly | **breaks 9 assertions** |
| `test_the_mesh_fetch_refusal_strings_are_unchanged` | `test_bf743_browser_ssrf_floor.py:288,297,300,301` | `str \| None` exactly | **breaks a standing contract test** |
| `BrowserTool._check_domain` | `browser/tool.py:1032` | `check_url_shape` only, never resolves | unaffected |
| `_RouteGuard` | `browser/url_route_guard.py:418` | `check_url_shape` only | unaffected |

**Decision: `validate_public_url` keeps its exact `str | None` signature.** Fourteen assertions across two files pin the refusal strings, one of them a test whose entire purpose is that those strings never reword. A second function carrying `(reason, addresses)` is strictly cheaper than migrating them, and the migration would buy nothing — only one consumer wants the address.

Three further signatures are pinned by the same method, and each one closes off an implementation that would otherwise look tidier:

| Signature | Pinned by | Consequence |
|---|---|---|
| `HttpFetchAgent._validate_url(url) -> str \| None` | patched in `test_bf770:600`, `test_bf729:67`, `test_bf769:404`, `test_bf819:441,518`, `test_bf807:393,452`; overridden in `test_bf820:311`; **called** in `test_ad456b:235,256` and `test_expansion_agents:401-466` | cannot return a tuple; cannot be bypassed by production, or 8 patch sites stop suppressing DNS and start hitting the network |
| `_fetch_url(url, method, *, max_body_bytes=None)` | called positionally in `test_bf770` ×14, `test_bf729:68` | unchanged |
| `_fetch_url_uncoalesced(self, url, method, cap)` | **overridden with exactly 3 positional params** at `test_bf770:45`; called positionally at `test_bf770:157` | **cannot take the pin as a parameter** |

That last row is decisive. Threading the pin from the `:325` gate down to the request loop would break `test_bf770`'s override. So the pin is computed **inside `_follow_and_fetch`, per hop, including hop 0**, and never crosses a signature that a test has pinned.

Hop 0 therefore resolves twice: once at `:325` as the cheap pre-coalescing gate (unchanged), once in the loop to produce the pin. That is not the bug returning. The bug was that the address connected to was never judged; here the *second* lookup is both the judged one and the connected one, and the first is only an early reject. State that in the code comment so the next reader does not "fix" it.

---

## 3. Mechanism: how httpx is made to connect to the approved address

The issue predicts "a custom transport or resolver, not a parameter." **That prediction is wrong for httpx 0.28.1, and the prompt deliberately departs from it.** Verified against the installed tree:

- `httpcore/_async/connection.py:124` connects with `self._origin.host`. The origin comes from the request URL. A custom transport that leaves the URL as a *name* still hands httpcore a name, so a transport alone does not pin anything — the resolution just moves.
- `httpcore/_async/connection.py:107` reads `request.extensions["sni_hostname"]`, and `:151` passes it as `server_hostname` into `start_tls`. Python's `ssl` uses `server_hostname` for **both** the SNI extension and the certificate hostname check.
- `httpx/_client.py:353→388` passes `extensions` through `AsyncClient.request` unchanged.
- `httpx/_models.py:450-456` adds `Host: url.netloc` **only when no `Host` header is already present**, so an explicit `Host` wins.

So the mechanism is a per-request URL rewrite plus two request-level knobs — no custom transport, no custom resolver, no new dependency.

### Verified empirically, with a negative control

An HTTPS server on `127.0.0.1` holding a cert valid **only** for `pinned.test`, connected to as `https://127.0.0.1:PORT/x` three ways:

```
CONTROL   -> ConnectError: [SSL: CERTIFICATE_VERIFY_FAILED] ... not valid for '127.0.0.1'
HOSTONLY  -> ConnectError: [SSL: CERTIFICATE_VERIFY_FAILED] ... not valid for '127.0.0.1'
PINNED    -> HTTP 200 body='PINNED OK'
host headers seen by server: ['pinned.test']
```

- **CONTROL** (no `Host`, no SNI) fails — proves the cert genuinely does not cover the IP, so the probe discriminates.
- **HOSTONLY** (`Host: pinned.test`, no SNI) **also fails.** This is the trap the issue warns about: rewriting the URL and setting `Host` alone connects to the IP and validates the certificate *against the IP*, trading SSRF for a broken TLS chain. A fix that stops at the `Host` header is worse than the bug.
- **PINNED** (`Host` + `extensions={"sni_hostname": ...}`) succeeds, and the server saw the original name.

`copy_with(host=...)` was verified to bracket IPv6 and preserve port, path, query and fragment:

```
93.184.216.34                      -> https://93.184.216.34:8443/a/b?q=1#f
2606:2800:220:1:248:1893:25c8:1946 -> https://[2606:2800:220:1:248:1893:25c8:1946]:8443/a/b?q=1#f
```

For `http://` the SNI extension is inert — `connection.py:140` only reads it when the scheme is `https`/`wss`. Setting it unconditionally is harmless and keeps one code path.

### Multiple A records

`check_resolved_address` already refuses if **any** address is private, so a mixed answer never reaches the pin. When all are public, which one?

Today the stack tries them all: anyio implements Happy Eyeballs (`anyio/_core/_sockets.py:140` `happy_eyeballs_delay: float = 0.25`, iterating `gai_res` at `:215,239`). Pinning to a single address removes that fallback, which is a real regression for multi-homed hosts.

**Decision: carry every approved address in getaddrinfo order; connect to the first; on `httpx.ConnectError` try the remaining approved addresses in order; fail closed when exhausted.** All of them came from the one judged lookup, so trying the next is not a second window. Named residual: the retry is *sequential*, not overlapped at 0.25s as Happy Eyeballs would be, so a blackholed first address costs one connect timeout rather than 0.25s. Accepted — the whole chain already sits inside the `asyncio.timeout(DEFAULT_TIMEOUT)` budget at `http_fetch.py:432`, which bounds it.

### The 429 retry

Reuse the pinned address. The retry at `:479` re-requests the same `current` within the same hop; re-validating would open a *third* lookup, which is the defect. Reusing the pin is both cheaper and strictly safer.

### Redirects

Each hop pins independently, and the pin is a **loop-local rebound at the top of each hop** — never carried across hops. `current` must stay the **name** URL, because two things read it:

- `previous.join(location)` at `:509` resolves relative `Location` headers against it. If `current` were the IP URL, a relative redirect would lose the hostname.
- `"url": str(response.url)` at `:543` becomes the IP URL once the request URL is rewritten, and `test_bf819_redirect_ssrf.py:177` asserts `result["data"]["url"] == "https://example.com/moved"` (and `:210` likewise). Section 4 changes that field to the logical URL.

`_get_domain_state(url)` at `:587` keys the rate limiter on `netloc`. It must keep receiving the **name** URL or the limiter re-keys per-IP and every domain budget silently resets.

---

## 4. Implementation

### Section 1 — `src/probos/security/url_guard.py`: resolve once, return what you judged

Add a frozen result type and the pinning entry point, and re-express `check_resolved_address` over it so there is exactly one resolution implementation and the two cannot drift.

Insert after the `ALLOWED_SCHEMES` assignment (currently `url_guard.py:37`):

```python
@dataclass(frozen=True)
class PinnedTarget:
    """A verdict together with the addresses it was reached on.

    BF-821: the floor used to resolve, judge, then throw the addresses away and
    answer about the URL *string*. httpx resolved the name again when it
    connected, so a nameserver answering differently for the two lookups put a
    connection on loopback with the guard's blessing -- reproduced end to end.
    Handing back what was judged is what lets a caller connect to it.

    ``addresses`` is in getaddrinfo order and is non-empty exactly when
    ``reason`` is None.
    """

    reason: str | None
    addresses: tuple[str, ...] = ()
```

Requires `from dataclasses import dataclass` in the import block.

Then replace the body of `check_resolved_address` (`url_guard.py:85-105`, from `try:` through `return None`) so it delegates, and add the new function immediately after it:

```python
def check_resolved_address(url: str) -> str | None:
    """<existing docstring, unchanged>"""
    return resolve_and_pin(url).reason


def resolve_and_pin(url: str) -> PinnedTarget:
    """Resolve once, judge every address, and hand back the ones that passed.

    Same refusals as ``check_resolved_address`` in the same order -- that
    function is now this one's verdict half, so the two cannot drift.
    """
    try:
        hostname = urlparse(url).hostname
    except Exception:
        return PinnedTarget("Malformed URL")
    if not hostname:
        return PinnedTarget(None)

    try:
        addrinfo = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return PinnedTarget(f"Cannot resolve hostname: {hostname}")

    approved: list[str] = []
    for _family, _type, _proto, _canon, sockaddr in addrinfo:
        try:
            ip = ipaddress.ip_address(sockaddr[0])
        except ValueError:
            continue
        reason = _reject_address(ip)
        if reason:
            return reason_only(reason)
        approved.append(str(ip))

    return PinnedTarget(None, tuple(approved))
```

Use `PinnedTarget(reason)` directly rather than inventing a `reason_only` helper — the line above is illustrative of the early return, not a required helper.

**Behaviour that must not shift:** a hostname-less URL returns `None` with no addresses (matching `:92-93` today), and a `sockaddr[0]` that will not parse is *skipped*, not refused (`:99-101`). A literal-host URL never reaches here — `check_url_shape` judged it at `:69-74` — so `approved` being empty while `reason` is None is only possible for the hostname-less case.

Add a `validate_and_pin_public_url(url) -> PinnedTarget` mirroring `validate_public_url`'s shape/resolve split, so the one consumer that needs the pin still gets the shape refusals first:

```python
def validate_and_pin_public_url(url: str) -> PinnedTarget:
    """``validate_public_url`` plus the addresses the verdict was reached on.

    Separate from ``validate_public_url`` rather than widening it: fourteen
    assertions across ``test_bf743_browser_ssrf_floor`` pin that function's
    ``str | None`` shape, one of them a standing contract that its refusal
    strings never reword, and only one caller wants the address.
    """
    shape = check_url_shape(url)
    if shape is not None:
        return PinnedTarget(shape)
    return resolve_and_pin(url)
```

`validate_public_url` is **not touched**.

### Section 2 — `src/probos/agents/http_fetch.py`: pin the connection

Import `validate_and_pin_public_url` alongside the existing `validate_public_url` (`http_fetch.py:14`).

Add a private helper that pairs the pin with the AD-456b egress consultation, so the loop gets one call and `_validate_url` keeps its pinned signature:

```python
def _validate_and_pin(self, url: str) -> PinnedTarget:
    """The floor plus AD-456b egress, returning the addresses it approved.

    ``_validate_url`` stays the reason-only entry point: eight tests patch or
    override it to suppress DNS, and two more call it directly.
    """
    target = validate_and_pin_public_url(url)
    if target.reason is not None:
        return target
    egress = self._check_egress(url)
    return PinnedTarget(egress) if egress else target
```

Extract the existing AD-456b block (`http_fetch.py:269-285`) into `_check_egress(url) -> str | None` and have `_validate_url` call `validate_public_url` then `_check_egress`, so the egress rule has one implementation. `_validate_url`'s signature, return values and refusal strings are unchanged.

In `_follow_and_fetch` (`:444-568`), inside the hop loop and **before** `response = await client.request(...)` at `:464`, pin the current hop:

```python
for hop in range(self.MAX_REDIRECTS + 1):
    target = self._validate_and_pin(current)
    if target.reason:
        return {"success": False, "error": f"SSRF protection: {target.reason}"}
    logical = httpx.URL(current)
    request_kwargs = self._pin_kwargs(logical, target.addresses)
    ...
```

`_pin_kwargs` returns the per-attempt list of `(url, headers, extensions)` triples — one per approved address, in order:

```python
@staticmethod
def _pin_kwargs(
    logical: httpx.URL, addresses: tuple[str, ...]
) -> list[tuple[httpx.URL, dict[str, str], dict[str, str]]]:
    """One attempt per approved address: connect to the address, speak to the name.

    BF-821: ``Host`` alone is not enough. Measured against httpx 0.28.1 -- with
    only the header rewritten, TLS verifies the certificate against the literal
    address and a valid host fails to connect. ``sni_hostname`` becomes
    ``server_hostname`` in httpcore's ``start_tls``, which is what the ssl
    module matches the certificate against, so the chain is still checked
    against the original name.
    """
    host = logical.host
    if not addresses:  # hostname-less or literal: nothing to pin
        return [(logical, {}, {})]
    return [
        (
            logical.copy_with(host=addr),
            {"Host": logical.netloc.decode("ascii")},
            {"sni_hostname": host},
        )
        for addr in addresses
    ]
```

`logical.netloc` carries `host:port` (and any userinfo — `_get_domain_state:597` already strips that for its own key, and `Host` must not carry credentials, so strip with `rpartition("@")[2]` here too).

Replace the two `await client.request(method, current)` calls (`:464` and the 429 retry at `:479`) with a helper that walks the attempt list:

```python
async def _request_pinned(self, client, method, attempts):
    """Try each approved address in order; fail closed when they are exhausted.

    All of them came from the one judged lookup, so the next address is not a
    second rebinding window. Sequential rather than anyio's overlapped Happy
    Eyeballs -- a blackholed first address costs one connect timeout, bounded
    by the chain's own ``asyncio.timeout``.
    """
    last: Exception | None = None
    for url, headers, extensions in attempts:
        try:
            return await client.request(
                method, url, headers=headers, extensions=extensions
            )
        except httpx.ConnectError as e:
            last = e
    raise last if last is not None else httpx.ConnectError("No approved address")
```

The 429 retry passes the **same** `attempts` list — no re-resolution, so no third lookup.

Delete the now-redundant bottom-of-loop validation at `:511-516`; the top-of-loop pin covers every hop including the redirect target. Leave `:509`'s `current = str(previous.join(...))` and the `:517` `_redirect_method` / `:522-527` domain-switch block exactly where they are, so refusal ordering relative to the rate limiter is unchanged from BF-819.

Change `:543` from `"url": str(response.url)` to `"url": str(logical)`. `response.url` is now the pinned IP URL; `logical` is the name URL httpx would have reported before the rewrite. Verified `str(httpx.URL('https://example.com')) == 'https://example.com'`, so this adds no trailing slash.

### Section 3 — pinned-signature migration (mechanical)

Production now calls `_validate_and_pin` on the request path, so the eight sites that patch or override `_validate_url` to suppress DNS stop taking effect. Each is disabling validation in a test about something else; repoint each to `_validate_and_pin` returning `PinnedTarget(None, ("93.184.216.34",))`:

`test_bf770_fetch_coalescing.py:600` · `test_bf729_ad1222_chosen_limits.py:67` · `test_bf769_blocked_search_fails.py:404` · `test_bf819_redirect_ssrf.py:441,518` · `test_bf807_truncation_reaches_readers.py:393,452` · `test_bf820_domain_slot_serialisation.py:311`

Do **not** change `test_ad456b_runtime_sandboxing.py:235,256` or `test_expansion_agents.py:401-466` — those *call* `_validate_url` and its contract is unchanged.

`test_bf820_domain_slot_serialisation.py:307-312` is a subclass named `_Unguarded` whose docstring explains the override; add the `_validate_and_pin` override beside the existing one and extend the docstring rather than replacing it.

### Section 4 — the BF-819 docstring that is now false

`http_fetch.py:407-411` currently reads:

```
        What that does NOT close: the guard resolves the hostname, and httpx
        resolves it again when connecting, so a hostile nameserver can answer
        differently for the two lookups. Closing that needs the connection
        pinned to the address the guard approved -- tracked separately, and not
        claimed here.
```

Replace with a statement of what is now true and what still is not — the browser residual below. Do not delete the paragraph; a reader who arrives from #1283 needs to find the answer where the question was.

---

## 5. Tests — `tests/test_bf821_pinned_address.py`

**Assert on the address actually connected to. Never on the guard's verdict.** A verdict assertion is what shipped this bug: the guard was right every time and the connection went elsewhere.

Every test that stubs resolution **must carry a negative control** proving the stub reaches the code under test, in the shape of the reproduction in Section 1. Without one, a green result and a stub that never fired are the same observation.

1. **The seam, end to end.** Real `HTTPServer` on loopback. Global `socket.getaddrinfo` stubbed: public on lookup 1, `127.0.0.1` after. Assert (a) the fetch **fails**, (b) the loopback server recorded **zero** requests, (c) `total lookups == 1` — after the fix httpx receives a literal and never resolves, so a count of 2 means the pin is not being used.
2. **Negative control for #1.** Same stub, but answering `127.0.0.1` on lookup 1. The guard must refuse with `Blocked private/reserved IP: 127.0.0.1`. If this does not fail, #1 proves nothing.
3. **A legitimate fetch still succeeds**, via a real loopback server whose name resolves consistently to `127.0.0.1`, with `_reject_address` patched to permit loopback for that address only. Guards against a fix that fails everything closed and passes #1 for the wrong reason.
4. **TLS verifies against the name, not the address.** Self-signed cert for `pinned.test` (`cryptography` is installed, 48.0.0), served on `127.0.0.1`. Assert success **and** assert the negative: the same connection without `sni_hostname` raises `CERTIFICATE_VERIFY_FAILED`. Both halves, or the test does not distinguish a working pin from a disabled verifier.
5. **The server sees the original `Host`,** not the address, and no userinfo.
6. **IPv6 literal is bracketed** in the rewritten URL.
7. **Port, path, query and fragment survive** the rewrite.
8. **429 retry reuses the pin** — total lookups for the hop stays 1 across the retry, and the retried request carries the same rewritten URL.
9. **Redirect hops pin independently:** hop 1 to a public name, hop 2 to a rebinding name — assert hop 2's victim server got nothing, and that hop 1's pin was not reused for hop 2.
10. **Relative `Location` resolves against the name,** not the pinned address.
11. **`data["url"]` is the name URL** on both a plain fetch and a redirected one (guards `test_bf819:177,210` from the inside).
12. **Rate-limit key is the name,** not the address: two fetches to the same name resolving to two different public addresses share one `DomainRateState`.
13. **Multi-A fallback:** first approved address refuses connections, second serves. Assert success and that both were attempted in order.
14. **Fail closed when all approved addresses fail** — a `ConnectError`, not a silent success.
15. **A mixed answer is refused entirely** — one public and one private address must refuse, not pin the public one.
16. **`validate_public_url` is byte-for-byte unchanged** in behaviour: re-assert the four refusal strings from `test_bf743:288-301` here too, so a future edit to `resolve_and_pin` cannot drift the delegating path.

Also run, unchanged and green: `tests/test_bf743_browser_ssrf_floor.py` (35), `tests/test_bf819_redirect_ssrf.py` (42), `tests/test_bf822_browser_navigation_floor.py` (87), `tests/test_bf770_fetch_coalescing.py`, `tests/test_bf820_domain_slot_serialisation.py`, `tests/test_ad456b_runtime_sandboxing.py`, `tests/test_expansion_agents.py`, `tests/test_sandbox_fetch_broker.py`.

---

## 6. What this does NOT change — do not build

- **`BrowserTool` and the Playwright path are OUT OF SCOPE.** Playwright resolves inside the browser process; BF-822's `context.route("**/*")` floor (`a63d828c`) sees a URL, not an address, and cannot pin one. **Named residual, unchanged by this fix:** a hostname that resolves to a private address is still reachable through the browser, and a rebinding name is too. This is an acknowledged gap, not an implied fix — say so in the BF-819 docstring replacement in Section 4. Do not add resolution to the browser tool: `test_bf743:265-269` asserts `check_resolved_address(` does not appear in that module, and `browser/tool.py:1062-1070` states why.
- **Do not widen `validate_public_url`.** Section 2's table is the reason.
- **Do not change** `_validate_url`, `_fetch_url` or `_fetch_url_uncoalesced` signatures.
- **Do not add** an address check to `http_fetch` — `test_bf743:247-250` asserts `is_link_local` does not appear in that module. All address judgement stays in `url_guard`.
- **Do not touch** the domain allow/deny lists, `EgressPolicy`, the rate limiter's algorithm, `MAX_BODY_BYTES`, truncation reporting, or fetch coalescing.
- **Do not implement Happy Eyeballs.** Sequential fallback is the accepted trade, named in Section 3.
- **Do not add a custom transport, resolver or network backend.** Section 3 shows a per-request rewrite is sufficient on httpx 0.28.1.
- **No roadmap or `PROGRESS.md` row.** Verified: `rg -c "BF-8" docs/development/roadmap.md PROGRESS.md` → no matches; siblings BF-819 and BF-822 carry none either. Tracking is issue #1285 only.

---

## 7. Acceptance criteria

1. The Section 1 reproduction, re-run against the fix, reports the fetch failing and **zero** loopback hits, with its CONTROL line still refusing.
2. `total lookups == 1` per hop — the pin, not a re-resolution, is what httpx connects on.
3. TLS verifies against the original hostname; the no-SNI negative control still fails with `CERTIFICATE_VERIFY_FAILED`.
4. All of `test_bf743` (35), `test_bf819` (42), `test_bf822` (87) pass unchanged.
5. Focused gate green: `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_bf821_pinned_address.py tests/test_bf743_browser_ssrf_floor.py tests/test_bf819_redirect_ssrf.py tests/test_bf822_browser_navigation_floor.py tests/test_bf770_fetch_coalescing.py tests/test_bf820_domain_slot_serialisation.py tests/test_ad456b_runtime_sandboxing.py tests/test_expansion_agents.py -q -p no:randomly`
6. Adversarial `Diff Reviewer` run on the staged diff with a **different model than the author**, findings addressed before commit. Tell it: the change claims a connection lands only on a judged address; the consumer that must accept it is `httpx.AsyncClient`; the live probe in Section 1 is available to re-run.
7. Full repository gate green once the change is frozen, run synchronously with no timeout.
8. Issue #1285 closed, closure verified.
9. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## 8. Verified against codebase (2026-08-26, `39373c76`)

```
git log --oneline -1
  39373c76 (HEAD -> main, origin/main) fix(bf-837): the game is played over agents, not ballots

git log --oneline -1 a63d828c
  a63d828c BF-822: browser navigation past the first URL is guarded ... (#1286)

rg -n "def check_url_shape|def check_resolved_address|def validate_public_url|def _reject_address" src/probos/security/url_guard.py
  39: def check_url_shape(url: str) -> str | None:
  75: def check_resolved_address(url: str) -> str | None:
  108: def validate_public_url(url: str, *, resolve: bool = True) -> str | None:
  124: def _reject_address(ip: ...) -> str | None:

rg -n 'client\.request|previous\.join|str\(response\.url\)|httpx\.AsyncClient|self\._validate_url|def _follow_and_fetch|status_code == 429' src/probos/agents/http_fetch.py
  325: error = self._validate_url(url)
  444: async def _follow_and_fetch(
  456: async with httpx.AsyncClient(
  464: response = await client.request(method, current)
  471: if response.status_code == 429:
  479: response = await client.request(method, current)
  509: current = str(previous.join(response.headers["location"]))
  511: error = self._validate_url(current)
  543: "url": str(response.url),

rg -n "validate_public_url|check_resolved_address" src/ tests/     # full consumer set, §2 table
rg -n "_validate_url" --glob '*.py' -S                              # 8 patch/override + 2 call sites
rg -n "_fetch_url_uncoalesced" tests/
  test_bf770_fetch_coalescing.py:45   async def _fetch_url_uncoalesced(self, url, method, cap):
  test_bf770_fetch_coalescing.py:157  agent._fetch_url_uncoalesced(URL, "GET", HttpFetchAgent.MAX_BODY_BYTES)

rg -n "data..url" tests/test_bf819_redirect_ssrf.py
  177: assert result["data"]["url"] == "https://example.com/moved"
  210: assert result["data"]["url"] == "https://en.wikipedia.org/wiki/LangChain"

rg -n --no-ignore "sni_hostname" .venv/Lib/site-packages/httpcore
  _async/connection.py:107  sni_hostname = request.extensions.get("sni_hostname", None)
  _async/connection.py:151  "server_hostname": sni_hostname

rg -n --no-ignore "Host" .venv/Lib/site-packages/httpx/_models.py
  450: has_host = "Host" in self.headers
  456: auto_headers.append((b"Host", self.url.netloc))

rg -n --no-ignore "happy_eyeballs_delay" .venv/Lib/site-packages/anyio/_core/_sockets.py
  140: happy_eyeballs_delay: float = 0.25

python -c "import httpx, httpcore; print(httpx.__version__, httpcore.__version__)"
  0.28.1 1.0.9
python -c "import cryptography; print(cryptography.__version__)"
  48.0.0

pytest --collect-only -q  (per file)
  tests/test_bf743_browser_ssrf_floor.py     -> 35 tests collected
  tests/test_bf819_redirect_ssrf.py          -> 42 tests collected
  tests/test_bf822_browser_navigation_floor.py -> 87 tests collected
```

## 9. Absence verified (2026-08-26)

```
CLAIM: no consumer of validate_public_url outside http_fetch and its own tests
RUN:   rg -n "validate_public_url" src/ tests/
FOUND: src/probos/agents/http_fetch.py:14,265 · src/probos/security/url_guard.py:108,121
       · tests/test_bf743_browser_ssrf_floor.py (14 assertion sites)
       · tests/test_bf819_redirect_ssrf.py:13 (prose only)
HOLDS: yes -- the browser path imports check_url_shape, never validate_public_url

CLAIM: no test calls _follow_and_fetch directly
RUN:   rg -n "_follow_and_fetch" tests/
FOUND: (no matches)
HOLDS: yes -- its signature is free to change

CLAIM: BF-8xx bugs carry no roadmap or PROGRESS row
RUN:   rg -c "BF-8" docs/development/roadmap.md PROGRESS.md
FOUND: (no matches, exit 1)
HOLDS: yes -- issue-only tracking, matching BF-819 and BF-822

CAVEAT (not a blocker): tests/test_ad456b_runtime_sandboxing.py:194 cites
"security/url_guard.py:92" in prose. Section 1 inserts above line 92, so that
citation goes stale. It is a docstring, not an assertion -- update the number
while editing, do not leave it wrong.
```
