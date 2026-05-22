#!/usr/bin/env bash
# AD-815d/e: Cowork base entrypoint.
#
# Responsibilities:
#   1. If /workspace/requirements.txt or /workspace/scratch/requirements.txt
#      exists, install it with `pip install --user --no-deps` (AD-815e).
#   2. If env var PROBOS_PIP_EXTRAS is set (comma-separated), install those.
#   3. Exec the agent's command (CMD or `docker run ... <cmd>`).
#
# The --no-deps flag is intentional: the base image already pins a coherent
# cohort of libs; transitive resolution at run-time could pull a conflicting
# newer release. Agents that need bigger deps should request a custom image
# via TaskSession.container_image.
#
# Honest about what we installed: stdout includes a single
# "AD-815e: installed extras: [...]" line that the runtime parses to record
# pip_installed_extras into task_session_runs.

set -euo pipefail

INSTALLED=()

install_one() {
    local pkg="$1"
    [ -z "$pkg" ] && return 0
    if pip install --user --no-deps --disable-pip-version-check --no-cache-dir "$pkg"; then
        INSTALLED+=("$pkg")
    else
        echo "AD-815e: warning — pip install '$pkg' failed (continuing)" >&2
    fi
}

# Source 1: requirements.txt files in expected locations.
for reqs in /workspace/requirements.txt /workspace/scratch/requirements.txt; do
    if [ -f "$reqs" ]; then
        echo "AD-815e: installing from $reqs"
        while IFS= read -r line; do
            # Skip blank lines + comments.
            stripped="$(echo "$line" | sed 's/#.*//' | xargs || true)"
            [ -z "$stripped" ] && continue
            install_one "$stripped"
        done < "$reqs"
    fi
done

# Source 2: env var PROBOS_PIP_EXTRAS (comma-separated).
if [ -n "${PROBOS_PIP_EXTRAS:-}" ]; then
    echo "AD-815e: installing from PROBOS_PIP_EXTRAS"
    IFS=',' read -ra extras <<< "$PROBOS_PIP_EXTRAS"
    for pkg in "${extras[@]}"; do
        install_one "$(echo "$pkg" | xargs)"
    done
fi

if [ "${#INSTALLED[@]}" -gt 0 ]; then
    # JSON-ish list so the runtime regex can pluck it out reliably.
    printf 'AD-815e: installed extras: ['
    for i in "${!INSTALLED[@]}"; do
        [ "$i" -gt 0 ] && printf ', '
        printf '"%s"' "${INSTALLED[$i]}"
    done
    printf ']\n'
fi

exec "$@"
