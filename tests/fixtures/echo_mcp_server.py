"""AD-1014 test fixture: a tiny NDJSON echo MCP server over stdio.

Launched via ``sys.executable``. Reads one JSON-RPC request per stdin line and
writes one JSON-RPC response per stdout line (echoing the request ``id``).

Supported methods:
  - ``initialize``  -> capabilities. Emits a spec-legal ``notifications/*`` line
    (no ``id``) *before* the response to exercise the client's skip-until-id read.
  - ``tools/list``  -> a fixed tool list.
  - ``tools/call``  -> echoes ``arguments``. Special tool names drive the
    failure paths:
      * ``"slow"``    -> writes nothing (drives the client read timeout).
      * ``"badjson"`` -> writes one malformed line (drives ``reason="bad_json"``).

All logging goes to stderr; protocol bytes only on stdout (per the MCP stdio
spec). Designed for deterministic single-flight tests: after a slow/badjson
call the server simply loops back to read the next request, so the bridge stays
usable.
"""

import json
import sys


def _send(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def main() -> None:
    sent_notification = False
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            sys.stderr.write("echo_mcp_server: bad request line\n")
            sys.stderr.flush()
            continue

        method = req.get("method", "")
        req_id = req.get("id")
        params = req.get("params") or {}

        if method == "initialize":
            # Spec-legal notification (no id) BEFORE the response -> exercises the
            # client's skip-until-matching-id read.
            if not sent_notification:
                _send({"jsonrpc": "2.0", "method": "notifications/initialized"})
                sent_notification = True
            _send(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "capabilities": {"tools": {"listChanged": False}},
                        "serverInfo": {"name": "echo", "version": "0.0.1"},
                    },
                }
            )
        elif method == "tools/list":
            _send(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "tools": [
                            {"name": "echo", "description": "echo back arguments"},
                            {"name": "slow", "description": "never responds"},
                            {"name": "badjson", "description": "emits malformed json"},
                        ]
                    },
                }
            )
        elif method == "tools/call":
            tool = params.get("name", "")
            arguments = params.get("arguments", {})
            if tool == "slow":
                # Write nothing -> the client times out; loop to the next request.
                sys.stderr.write("echo_mcp_server: 'slow' -> no response\n")
                sys.stderr.flush()
                continue
            if tool == "badjson":
                sys.stdout.write("{not valid json\n")
                sys.stdout.flush()
                continue
            _send(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [
                            {"type": "text", "text": json.dumps(arguments)}
                        ]
                    },
                }
            )
        else:
            _send(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {
                        "code": -32601,
                        "message": f"method not found: {method}",
                    },
                }
            )


if __name__ == "__main__":
    main()
