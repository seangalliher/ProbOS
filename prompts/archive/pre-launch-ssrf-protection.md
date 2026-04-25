# Pre-Launch: SSRF Protection for HttpFetchAgent (AD-285)

> **Context:** HttpFetchAgent currently fetches any URL without restriction.
> Before the OSS repo goes public, we need to block requests to private/internal
> networks, cloud metadata endpoints, and localhost. This is a security requirement
> for any system that fetches user-supplied URLs.
>
> The research module (`cognitive/research.py`) routes through the mesh's
> `http_fetch` intent, so it's automatically covered by this fix.

## Pre-read

Before starting, read these files:
- `src/probos/agents/http_fetch.py` — full HttpFetchAgent implementation. The fix goes in `decide()` (URL validation before fetch) or as a dedicated `_validate_url()` method called from `_fetch_url()`
- `tests/test_expansion_agents.py` — existing HttpFetchAgent tests (class `TestHttpFetchAgent`, line ~281). Add SSRF tests here
- `PROGRESS.md` line 2 — current test count

## Step 1: Add URL Validation (AD-285)

Add a `_validate_url()` method to `HttpFetchAgent` that rejects dangerous URLs
before any network request is made. Call it at the top of `_fetch_url()`.

**What to block:**

1. **Private IPv4 ranges:**
   - `10.0.0.0/8`
   - `172.16.0.0/12`
   - `192.168.0.0/16`
   - `127.0.0.0/8` (loopback)
   - `169.254.0.0/16` (link-local)
   - `0.0.0.0/8`

2. **Private IPv6:**
   - `::1` (loopback)
   - `fc00::/7` (unique local)
   - `fe80::/10` (link-local)

3. **Cloud metadata endpoints:**
   - `169.254.169.254` (AWS/GCP/Azure metadata)
   - `metadata.google.internal`
   - `169.254.170.2` (AWS ECS task metadata)

4. **Scheme restrictions:**
   - Only allow `http` and `https` schemes
   - Block `file://`, `ftp://`, `gopher://`, `dict://`, etc.

5. **DNS rebinding defense:**
   - Resolve the hostname to IP BEFORE making the request
   - Check the resolved IP against the blocklist
   - Use `socket.getaddrinfo()` for resolution
   - This prevents `attacker.com` DNS returning `127.0.0.1`

**Implementation approach:**

```python
import ipaddress
import socket

def _validate_url(self, url: str) -> str | None:
    """Validate URL is safe to fetch. Returns error message or None if safe."""
    parsed = urllib.parse.urlparse(url)

    # Scheme check
    if parsed.scheme not in ("http", "https"):
        return f"Blocked scheme: {parsed.scheme}"

    # Extract hostname
    hostname = parsed.hostname
    if not hostname:
        return "No hostname in URL"

    # Resolve DNS to catch rebinding
    try:
        addrinfo = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return f"Cannot resolve hostname: {hostname}"

    for family, _, _, _, sockaddr in addrinfo:
        ip = ipaddress.ip_address(sockaddr[0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return f"Blocked private/reserved IP: {ip}"

    # Cloud metadata hostnames
    blocked_hosts = {"metadata.google.internal"}
    if hostname.lower() in blocked_hosts:
        return f"Blocked metadata endpoint: {hostname}"

    return None
```

**Call site** — at the top of `_fetch_url()`, before rate limiting:

```python
async def _fetch_url(self, url: str, method: str) -> dict[str, Any]:
    error = self._validate_url(url)
    if error:
        return {"success": False, "error": f"SSRF protection: {error}"}
    # ... rest of existing code
```

**Do NOT modify the `requires_consensus` setting.** HTTP GET is non-destructive
and doesn't require consensus. The SSRF check is a safety net, not a governance
gate.

## Step 2: Add Tests

Add to `tests/test_expansion_agents.py` in the `TestHttpFetchAgent` class:

1. **test_ssrf_blocks_localhost** — URL `http://127.0.0.1/secret` returns error with "SSRF protection"
2. **test_ssrf_blocks_private_10** — URL `http://10.0.0.1/internal` blocked
3. **test_ssrf_blocks_private_172** — URL `http://172.16.0.1/internal` blocked
4. **test_ssrf_blocks_private_192** — URL `http://192.168.1.1/admin` blocked
5. **test_ssrf_blocks_metadata** — URL `http://169.254.169.254/latest/meta-data/` blocked
6. **test_ssrf_blocks_file_scheme** — URL `file:///etc/passwd` blocked
7. **test_ssrf_allows_public_url** — URL `http://example.com` passes validation (mock the DNS resolution to return a public IP like `93.184.216.34`)
8. **test_ssrf_dns_rebinding** — Mock `socket.getaddrinfo` to return `127.0.0.1` for `evil.com`, verify it's blocked

For tests that call `_validate_url()` directly, you don't need to mock httpx.
For tests that need DNS resolution mocked, monkeypatch `socket.getaddrinfo`.

**Run tests:** `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`

## Step 3: Update PROGRESS.md

- Update test count on line 2
- Add a note to the Pre-Launch section marking SSRF protection as complete: `- ✅ **SSRF protection** (AD-285)`
- Update the Pre-Launch item description to note it's done

## Verification

After the fix:
- `http://127.0.0.1:8080/anything` → blocked
- `http://169.254.169.254/latest/meta-data/` → blocked
- `http://10.0.0.1/internal` → blocked
- `file:///etc/passwd` → blocked
- `http://example.com` → allowed (passes validation)
- All existing tests still pass
- Report final test count
