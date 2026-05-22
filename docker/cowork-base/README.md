# ProbOS Cowork Base Image (AD-815d)

Default container image consumed by AD-815a `TaskSession` runs when no
custom `container_image` is set. Provides:

* Python 3.12-slim base on a non-root `probos` UID 1500 user
* `/workspace` mountpoint (matches AD-799 per-thread workspace mount)
* Pre-installed office / PDF / data / markup / HTTP stack
* Playwright + Chromium pre-installed (powers AD-815f)
* Entrypoint that auto-installs declared extras (AD-815e)

## Build

```bash
docker build -t probos/cowork-base:latest docker/cowork-base
```

Image size ≈ 1.5 GB (Chromium dominates). First build is ~3-5 min on
broadband; subsequent rebuilds reuse layers.

## Pinned versions (AD-815d-pins)

Update the table and the `Dockerfile` in lockstep when pin-bumping.

| Package        | Version |
|----------------|---------|
| python         | 3.12-slim |
| python-docx    | 1.1.2 |
| openpyxl       | 3.1.5 |
| python-pptx    | 0.6.23 |
| xlsxwriter     | 3.2.0 |
| weasyprint     | 62.3 |
| reportlab      | 4.2.5 |
| Pillow         | 10.4.0 |
| pandas         | 2.2.3 |
| markdown       | 3.7 |
| beautifulsoup4 | 4.12.3 |
| lxml           | 5.3.0 |
| pyyaml         | 6.0.2 |
| jinja2         | 3.1.4 |
| httpx          | 0.28.1 |
| requests       | 2.32.3 |
| playwright     | 1.47.0 |

## Smoke test

After building locally:

```bash
docker run --rm probos/cowork-base:latest \
  python -c "import docx, openpyxl, pptx, weasyprint, pandas, playwright; print('OK')"
```

Expected output: `OK`.

## AD-815e — declaring extra packages

The entrypoint inspects two sources for extra packages to install at
startup:

1. `/workspace/requirements.txt` or `/workspace/scratch/requirements.txt`
2. The `PROBOS_PIP_EXTRAS` env var (comma-separated)

Installs use `pip install --user --no-deps` so the base cohort stays
internally consistent. Failed installs log a warning and continue;
successful installs are summarized in a final `AD-815e: installed
extras: [...]` line that the runtime parses into
`task_session_runs.pip_installed_extras`.

## AD-815f — Playwright usage

Chromium is pre-installed at build time. Inside a TaskSession the agent
can:

```python
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto("https://example.com")
    page.screenshot(path="/workspace/outputs/screenshot.png")
    browser.close()
```

The CDP "shared browser" mode (operator's local browser session) is
documented in AD-815f.

## Honest-degrade

If this image is not present on the host, the `DockerContainerSandbox`
backend (AD-798) returns a `CommandOutcome` with
`error="image not found: probos/cowork-base:latest"` rather than
silently falling back to a different image. Operators see the gap and
can either pull/build the image or set a custom `container_image` on
the TaskSession.
