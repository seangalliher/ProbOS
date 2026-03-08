#!/usr/bin/env bash
# Launch a two-node ProbOS federation cluster.
#
# Usage:
#   ./scripts/launch-cluster.sh
#
# Requires pyzmq: pip install pyzmq

set -euo pipefail

cd "$(dirname "$0")/.."

echo "Starting ProbOS node-1..."
uv run python -m probos --config config/node-1.yaml &
PID1=$!

echo "Starting ProbOS node-2..."
uv run python -m probos --config config/node-2.yaml &
PID2=$!

echo "ProbOS cluster running: node-1 (PID $PID1), node-2 (PID $PID2)"
echo "Press Ctrl-C to stop both nodes."

trap "echo 'Shutting down cluster...'; kill $PID1 $PID2 2>/dev/null; wait" INT TERM

wait
