"""Tests for Phase 5 expansion agents — unit, integration, and error cases."""

import pytest

from probos.agents.directory_list import DirectoryListAgent
from probos.agents.file_search import FileSearchAgent
from probos.agents.http_fetch import HttpFetchAgent
from probos.agents.shell_command import ShellCommandAgent
from probos.cognitive.llm_client import MockLLMClient
from probos.runtime import ProbOSRuntime
from probos.types import IntentMessage


# ---------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------


@pytest.fixture
async def runtime(tmp_path):
    """Create a runtime with MockLLMClient, start it, yield, stop."""
    llm = MockLLMClient()
    rt = ProbOSRuntime(data_dir=tmp_path / "data", llm_client=llm)
    await rt.start()
    yield rt
    await rt.stop()


# ---------------------------------------------------------------
# Unit Tests: DirectoryListAgent
# ---------------------------------------------------------------


class TestDirectoryListAgent:
    def test_agent_type_and_capabilities(self):
        agent = DirectoryListAgent(pool="directory")
        assert agent.agent_type == "directory_list"
        assert any(c.can == "list_directory" for c in agent.capabilities)

    @pytest.mark.asyncio
    async def test_list_directory(self, tmp_path):
        (tmp_path / "file1.txt").write_text("a")
        (tmp_path / "file2.txt").write_text("b")
        (tmp_path / "subdir").mkdir()

        agent = DirectoryListAgent()
        intent = IntentMessage(intent="list_directory", params={"path": str(tmp_path)})
        result = await agent.handle_intent(intent)

        assert result is not None
        assert result.success
        assert len(result.result) == 3
        names = {e["name"] for e in result.result}
        assert "file1.txt" in names
        assert "subdir" in names
        dir_entry = next(e for e in result.result if e["name"] == "subdir")
        assert dir_entry["type"] == "dir"

    @pytest.mark.asyncio
    async def test_list_nonexistent_directory(self):
        agent = DirectoryListAgent()
        intent = IntentMessage(
            intent="list_directory", params={"path": "/nonexistent/xyz"}
        )
        result = await agent.handle_intent(intent)
        assert result is not None
        assert not result.success
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_list_empty_directory(self, tmp_path):
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        agent = DirectoryListAgent()
        intent = IntentMessage(
            intent="list_directory", params={"path": str(empty_dir)}
        )
        result = await agent.handle_intent(intent)
        assert result is not None
        assert result.success
        assert result.result == []

    @pytest.mark.asyncio
    async def test_list_not_a_directory(self, tmp_path):
        f = tmp_path / "file.txt"
        f.write_text("hello")

        agent = DirectoryListAgent()
        intent = IntentMessage(
            intent="list_directory", params={"path": str(f)}
        )
        result = await agent.handle_intent(intent)
        assert result is not None
        assert not result.success
        assert "not a directory" in result.error.lower()

    @pytest.mark.asyncio
    async def test_missing_path_returns_error(self):
        agent = DirectoryListAgent()
        intent = IntentMessage(intent="list_directory", params={})
        result = await agent.handle_intent(intent)
        assert result is not None
        assert not result.success
        assert "path" in result.error.lower()

    @pytest.mark.asyncio
    async def test_declines_unhandled_intent(self):
        agent = DirectoryListAgent()
        intent = IntentMessage(intent="read_file", params={})
        result = await agent.handle_intent(intent)
        assert result is None


# ---------------------------------------------------------------
# Unit Tests: FileSearchAgent
# ---------------------------------------------------------------


class TestFileSearchAgent:
    def test_agent_type_and_capabilities(self):
        agent = FileSearchAgent(pool="search")
        assert agent.agent_type == "file_search"
        assert any(c.can == "search_files" for c in agent.capabilities)

    @pytest.mark.asyncio
    async def test_search_matching_glob(self, tmp_path):
        (tmp_path / "a.txt").write_text("a")
        (tmp_path / "b.txt").write_text("b")
        (tmp_path / "c.md").write_text("c")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "d.txt").write_text("d")

        agent = FileSearchAgent()
        intent = IntentMessage(
            intent="search_files",
            params={"path": str(tmp_path), "pattern": "*.txt"},
        )
        result = await agent.handle_intent(intent)

        assert result is not None
        assert result.success
        assert len(result.result) == 3  # a.txt, b.txt, sub/d.txt

    @pytest.mark.asyncio
    async def test_search_no_matches(self, tmp_path):
        (tmp_path / "a.txt").write_text("a")

        agent = FileSearchAgent()
        intent = IntentMessage(
            intent="search_files",
            params={"path": str(tmp_path), "pattern": "*.xyz"},
        )
        result = await agent.handle_intent(intent)

        assert result is not None
        assert result.success
        assert result.result == []

    @pytest.mark.asyncio
    async def test_search_nonexistent_base_dir(self):
        agent = FileSearchAgent()
        intent = IntentMessage(
            intent="search_files",
            params={"path": "/nonexistent", "pattern": "*.txt"},
        )
        result = await agent.handle_intent(intent)
        assert result is not None
        assert not result.success

    @pytest.mark.asyncio
    async def test_missing_params(self):
        agent = FileSearchAgent()
        intent = IntentMessage(intent="search_files", params={})
        result = await agent.handle_intent(intent)
        assert result is not None
        assert not result.success

    @pytest.mark.asyncio
    async def test_declines_unhandled_intent(self):
        agent = FileSearchAgent()
        intent = IntentMessage(intent="read_file", params={})
        result = await agent.handle_intent(intent)
        assert result is None


# ---------------------------------------------------------------
# Unit Tests: ShellCommandAgent
# ---------------------------------------------------------------


class TestShellCommandAgent:
    def test_agent_type_and_capabilities(self):
        agent = ShellCommandAgent(pool="shell")
        assert agent.agent_type == "shell_command"
        assert any(c.can == "run_command" for c in agent.capabilities)

    @pytest.mark.asyncio
    async def test_echo_hello(self):
        agent = ShellCommandAgent()
        intent = IntentMessage(
            intent="run_command", params={"command": "echo hello"}
        )
        result = await agent.handle_intent(intent)

        assert result is not None
        assert result.success
        assert result.result["exit_code"] == 0
        assert "hello" in result.result["stdout"]

    @pytest.mark.asyncio
    async def test_failing_command(self):
        agent = ShellCommandAgent()
        # 'exit 42' works on both bash and cmd
        intent = IntentMessage(
            intent="run_command", params={"command": "exit 42"}
        )
        result = await agent.handle_intent(intent)

        assert result is not None
        assert result.success  # Still True per design
        assert result.result["exit_code"] != 0

    @pytest.mark.asyncio
    async def test_empty_command(self):
        agent = ShellCommandAgent()
        intent = IntentMessage(intent="run_command", params={"command": ""})
        result = await agent.handle_intent(intent)
        assert result is not None
        assert not result.success
        assert "command" in result.error.lower()

    @pytest.mark.asyncio
    async def test_declines_unhandled_intent(self):
        agent = ShellCommandAgent()
        intent = IntentMessage(intent="read_file", params={})
        result = await agent.handle_intent(intent)
        assert result is None

    @pytest.mark.asyncio
    async def test_rewrite_bare_python(self):
        """Bare 'python -c ...' should be rewritten to sys.executable."""
        import sys
        result = ShellCommandAgent._rewrite_python_interpreter('python -c "print(1)"')
        assert sys.executable in result
        if sys.platform == 'win32':
            assert result.startswith('& "')
        else:
            assert result.startswith('"')

    @pytest.mark.asyncio
    async def test_rewrite_python3(self):
        """Bare 'python3 -c ...' should be rewritten too."""
        import sys
        result = ShellCommandAgent._rewrite_python_interpreter('python3 -c "print(1)"')
        assert sys.executable in result
        if sys.platform == 'win32':
            assert result.startswith('& "')
        else:
            assert result.startswith('"')

    @pytest.mark.asyncio
    async def test_no_rewrite_other_commands(self):
        """Non-python commands should pass through unchanged."""
        cmd = "echo hello"
        assert ShellCommandAgent._rewrite_python_interpreter(cmd) == cmd

    @pytest.mark.asyncio
    async def test_no_rewrite_full_path_python(self):
        """Full path python should NOT be rewritten (already qualified)."""
        cmd = '/usr/bin/python -c "print(1)"'
        assert ShellCommandAgent._rewrite_python_interpreter(cmd) == cmd


# ---------------------------------------------------------------
# Unit Tests: HttpFetchAgent
# ---------------------------------------------------------------


class TestHttpFetchAgent:
    def test_agent_type_and_capabilities(self):
        agent = HttpFetchAgent(pool="http")
        assert agent.agent_type == "http_fetch"
        assert any(c.can == "http_fetch" for c in agent.capabilities)

    @pytest.mark.asyncio
    async def test_fetch_with_mock(self, monkeypatch):
        """Mock httpx to avoid network calls in unit tests."""
        import httpx

        class MockResponse:
            status_code = 200
            url = "https://example.com"
            content = b'{"ok": true}'
            headers = {"content-type": "application/json", "server": "mock"}

        class MockAsyncClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                pass

            async def request(self, method, url):
                return MockResponse()

        monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: MockAsyncClient())

        agent = HttpFetchAgent()
        intent = IntentMessage(
            intent="http_fetch",
            params={"url": "https://example.com", "method": "GET"},
        )
        result = await agent.handle_intent(intent)

        assert result is not None
        assert result.success
        assert result.result["status_code"] == 200
        assert result.result["body_length"] > 0

    @pytest.mark.asyncio
    async def test_fetch_connection_error(self, monkeypatch):
        """Simulate unreachable URL."""
        import httpx

        class MockAsyncClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                pass

            async def request(self, method, url):
                raise httpx.ConnectError("unreachable")

        monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: MockAsyncClient())
        # Mock DNS so SSRF validation passes (test is about connection errors, not DNS)
        monkeypatch.setattr(
            "socket.getaddrinfo",
            lambda *a, **kw: [(2, 1, 6, "", ("93.184.216.34", 0))],
        )

        agent = HttpFetchAgent()
        intent = IntentMessage(
            intent="http_fetch",
            params={"url": "https://unreachable.invalid", "method": "GET"},
        )
        result = await agent.handle_intent(intent)

        assert result is not None
        assert not result.success
        assert "connection" in result.error.lower()

    @pytest.mark.asyncio
    async def test_missing_url(self):
        agent = HttpFetchAgent()
        intent = IntentMessage(intent="http_fetch", params={})
        result = await agent.handle_intent(intent)
        assert result is not None
        assert not result.success
        assert "url" in result.error.lower()

    @pytest.mark.asyncio
    async def test_declines_unhandled_intent(self):
        agent = HttpFetchAgent()
        intent = IntentMessage(intent="read_file", params={})
        result = await agent.handle_intent(intent)
        assert result is None


class TestHttpFetchSSRF:
    """AD-285: SSRF protection tests."""

    def test_ssrf_blocks_localhost(self, monkeypatch):
        monkeypatch.setattr(
            "socket.getaddrinfo",
            lambda *a, **kw: [(2, 1, 6, "", ("127.0.0.1", 0))],
        )
        agent = HttpFetchAgent()
        error = agent._validate_url("http://127.0.0.1/secret")
        assert error is not None
        assert "private" in error.lower() or "loopback" in error.lower()

    def test_ssrf_blocks_private_10(self, monkeypatch):
        monkeypatch.setattr(
            "socket.getaddrinfo",
            lambda *a, **kw: [(2, 1, 6, "", ("10.0.0.1", 0))],
        )
        agent = HttpFetchAgent()
        error = agent._validate_url("http://10.0.0.1/internal")
        assert error is not None
        assert "private" in error.lower()

    def test_ssrf_blocks_private_172(self, monkeypatch):
        monkeypatch.setattr(
            "socket.getaddrinfo",
            lambda *a, **kw: [(2, 1, 6, "", ("172.16.0.1", 0))],
        )
        agent = HttpFetchAgent()
        error = agent._validate_url("http://172.16.0.1/internal")
        assert error is not None
        assert "private" in error.lower()

    def test_ssrf_blocks_private_192(self, monkeypatch):
        monkeypatch.setattr(
            "socket.getaddrinfo",
            lambda *a, **kw: [(2, 1, 6, "", ("192.168.1.1", 0))],
        )
        agent = HttpFetchAgent()
        error = agent._validate_url("http://192.168.1.1/admin")
        assert error is not None
        assert "private" in error.lower()

    def test_ssrf_blocks_metadata(self, monkeypatch):
        monkeypatch.setattr(
            "socket.getaddrinfo",
            lambda *a, **kw: [(2, 1, 6, "", ("169.254.169.254", 0))],
        )
        agent = HttpFetchAgent()
        error = agent._validate_url("http://169.254.169.254/latest/meta-data/")
        assert error is not None

    def test_ssrf_blocks_file_scheme(self):
        agent = HttpFetchAgent()
        error = agent._validate_url("file:///etc/passwd")
        assert error is not None
        assert "scheme" in error.lower()

    def test_ssrf_allows_public_url(self, monkeypatch):
        monkeypatch.setattr(
            "socket.getaddrinfo",
            lambda *a, **kw: [(2, 1, 6, "", ("93.184.216.34", 0))],
        )
        agent = HttpFetchAgent()
        error = agent._validate_url("http://example.com")
        assert error is None

    def test_ssrf_dns_rebinding(self, monkeypatch):
        """evil.com DNS returning 127.0.0.1 should be blocked."""
        monkeypatch.setattr(
            "socket.getaddrinfo",
            lambda *a, **kw: [(2, 1, 6, "", ("127.0.0.1", 0))],
        )
        agent = HttpFetchAgent()
        error = agent._validate_url("http://evil.com/steal-secrets")
        assert error is not None
        assert "private" in error.lower() or "loopback" in error.lower()


class TestHttpFetchRateLimiter:
    """AD-270: Per-domain rate limiter tests."""

    def setup_method(self):
        # Clear shared domain state between tests
        HttpFetchAgent._domain_state.clear()

    @pytest.mark.asyncio
    async def test_domain_state_created(self, monkeypatch):
        """Fetching a URL creates domain state with last_request_time > 0."""
        import httpx

        class MockResponse:
            status_code = 200
            url = "https://example.com/test"
            content = b"ok"
            headers = {"content-type": "text/plain"}

        class MockAsyncClient:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *a):
                pass
            async def request(self, method, url):
                return MockResponse()

        monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: MockAsyncClient())
        monkeypatch.setattr(
            "socket.getaddrinfo",
            lambda *a, **kw: [(2, 1, 6, "", ("93.184.216.34", 0))],
        )

        agent = HttpFetchAgent()
        intent = IntentMessage(intent="http_fetch", params={"url": "https://example.com/test"})
        await agent.handle_intent(intent)

        assert "example.com" in HttpFetchAgent._domain_state
        assert HttpFetchAgent._domain_state["example.com"].last_request_time > 0

    def test_known_domain_interval(self):
        """api.coingecko.com should get 3.0s interval."""
        agent = HttpFetchAgent()
        _, state = agent._get_domain_state("https://api.coingecko.com/api/v3/simple/price")
        assert state.min_interval_seconds == 3.0

    def test_unknown_domain_default_interval(self):
        """Unknown domain should get 2.0s default."""
        agent = HttpFetchAgent()
        _, state = agent._get_domain_state("https://unknown-api.example.org/data")
        assert state.min_interval_seconds == 2.0

    def test_consecutive_429_backoff(self):
        """Two consecutive 429s should escalate the interval."""
        import httpx

        agent = HttpFetchAgent()
        _, state = agent._get_domain_state("https://test429.example.com")

        # Simulate first 429
        resp1 = httpx.Response(429, headers={}, request=httpx.Request("GET", "https://test429.example.com"))
        agent._update_rate_state(state, resp1)
        assert state.consecutive_429s == 1
        assert state.min_interval_seconds == 2  # 2^1

        # Simulate second 429
        resp2 = httpx.Response(429, headers={}, request=httpx.Request("GET", "https://test429.example.com"))
        agent._update_rate_state(state, resp2)
        assert state.consecutive_429s == 2
        assert state.min_interval_seconds == 4  # 2^2

    def test_success_resets_429_counter(self):
        """A 200 after 429s should reset the counter."""
        import httpx

        agent = HttpFetchAgent()
        _, state = agent._get_domain_state("https://testreset.example.com")

        # Simulate 429 then 200
        resp_429 = httpx.Response(429, headers={}, request=httpx.Request("GET", "https://testreset.example.com"))
        agent._update_rate_state(state, resp_429)
        assert state.consecutive_429s == 1

        resp_200 = httpx.Response(200, headers={}, request=httpx.Request("GET", "https://testreset.example.com"))
        agent._update_rate_state(state, resp_200)
        assert state.consecutive_429s == 0

    def test_retry_after_header_respected(self):
        """Retry-After header should set retry_after on state."""
        import httpx
        import time

        agent = HttpFetchAgent()
        _, state = agent._get_domain_state("https://testretry.example.com")

        before = time.monotonic()
        resp = httpx.Response(429, headers={"retry-after": "5"}, request=httpx.Request("GET", "https://testretry.example.com"))
        agent._update_rate_state(state, resp)

        assert state.retry_after is not None
        assert state.retry_after >= before + 5

    @pytest.mark.asyncio
    async def test_rate_limit_delay_in_result(self, monkeypatch):
        """Successful result should contain rate_limit_delay field."""
        import httpx

        class MockResponse:
            status_code = 200
            url = "https://delaytest.example.com"
            content = b"ok"
            headers = {"content-type": "text/plain"}

        class MockAsyncClient:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *a):
                pass
            async def request(self, method, url):
                return MockResponse()

        monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: MockAsyncClient())
        monkeypatch.setattr(
            "socket.getaddrinfo",
            lambda *a, **kw: [(2, 1, 6, "", ("93.184.216.34", 0))],
        )

        agent = HttpFetchAgent()
        intent = IntentMessage(intent="http_fetch", params={"url": "https://delaytest.example.com"})
        result = await agent.handle_intent(intent)

        assert result is not None
        assert result.success
        assert "rate_limit_delay" in result.result


# ---------------------------------------------------------------
# Integration Tests (full runtime)
# ---------------------------------------------------------------


class TestExpansionIntegration:
    @pytest.mark.asyncio
    async def test_pools_created(self, runtime):
        """New pools should exist after boot."""
        assert "directory" in runtime.pools
        assert "search" in runtime.pools
        assert "shell" in runtime.pools
        assert "http" in runtime.pools

    @pytest.mark.asyncio
    async def test_nl_list_directory(self, runtime, tmp_path):
        """NL 'what files are in <path>' -> list_directory."""
        (tmp_path / "a.txt").write_text("a")
        (tmp_path / "b.txt").write_text("b")

        result = await runtime.process_natural_language(
            f"what files are in {tmp_path}"
        )
        assert result["node_count"] == 1
        assert result["completed_count"] == 1

    @pytest.mark.asyncio
    async def test_nl_search_files(self, runtime, tmp_path):
        """NL 'find files named *.txt in <path>' -> search_files."""
        (tmp_path / "x.txt").write_text("x")

        result = await runtime.process_natural_language(
            f"find files named *.txt in {tmp_path}"
        )
        assert result["node_count"] == 1
        assert result["completed_count"] == 1

    @pytest.mark.asyncio
    async def test_nl_run_command(self, runtime):
        """NL 'run the command echo hello' -> run_command with consensus."""
        result = await runtime.process_natural_language(
            "run the command echo hello"
        )
        assert result["node_count"] == 1
        assert result["completed_count"] == 1

    @pytest.mark.asyncio
    async def test_nl_http_fetch_mock(self, runtime, monkeypatch):
        """NL 'fetch https://...' -> http_fetch without consensus (mocked)."""
        import httpx

        class MockResponse:
            status_code = 200
            url = "https://httpbin.org/get"
            content = b'{"ok": true}'
            headers = {"content-type": "application/json"}

        class MockAsyncClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                pass

            async def request(self, method, url):
                return MockResponse()

        monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: MockAsyncClient())
        monkeypatch.setattr(
            "socket.getaddrinfo",
            lambda *a, **kw: [(2, 1, 6, "", ("34.117.59.81", 0))],
        )

        result = await runtime.process_natural_language(
            "fetch https://httpbin.org/get"
        )
        assert result["node_count"] == 1
        assert result["completed_count"] == 1

    @pytest.mark.asyncio
    async def test_submit_list_directory(self, runtime, tmp_path):
        """Direct submit_intent for list_directory returns results."""
        (tmp_path / "f.txt").write_text("x")
        results = await runtime.submit_intent(
            "list_directory", params={"path": str(tmp_path)}, timeout=5.0
        )
        assert len(results) == 3  # 3 agents in pool
        for r in results:
            assert r.success

    @pytest.mark.asyncio
    async def test_submit_run_command_with_consensus(self, runtime):
        """Direct submit_intent_with_consensus for run_command."""
        result = await runtime.submit_intent_with_consensus(
            "run_command",
            params={"command": "echo consensus_test"},
            timeout=5.0,
        )
        assert len(result["results"]) == 3
        assert result["consensus"].outcome.value in (
            "approved", "rejected", "insufficient"
        )


# ---------------------------------------------------------------
# Error Case Tests
# ---------------------------------------------------------------


class TestExpansionErrors:
    @pytest.mark.asyncio
    async def test_list_nonexistent_via_runtime(self, runtime):
        results = await runtime.submit_intent(
            "list_directory", params={"path": "/nonexistent/xyz"}, timeout=5.0
        )
        assert len(results) == 3
        for r in results:
            assert not r.success

    @pytest.mark.asyncio
    async def test_search_nonexistent_via_runtime(self, runtime):
        results = await runtime.submit_intent(
            "search_files",
            params={"path": "/nonexistent", "pattern": "*.txt"},
            timeout=5.0,
        )
        assert len(results) == 3
        for r in results:
            assert not r.success

    @pytest.mark.asyncio
    async def test_failing_command_via_runtime(self, runtime):
        results = await runtime.submit_intent(
            "run_command", params={"command": "exit 42"}, timeout=5.0
        )
        assert len(results) == 3
        for r in results:
            assert r.success  # success=True even with nonzero exit code
            assert r.result["exit_code"] != 0
