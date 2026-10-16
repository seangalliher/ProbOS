"""AD-1328 S1 repair (R6): the argv probe the shell oracle runs.

Appends the arguments this process received, as one JSON line, to the file named by
``AD1328_PROBE_LOG``; prints nothing. Started by the shells under test, never imported.
"""

import json
import os
import sys

with open(os.environ["AD1328_PROBE_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps(sys.argv[1:]) + "\n")
