# AD-815d: ProbOS Cowork base image.
#
# Provides the default container that AD-815a TaskSessions run in when the
# operator doesn't override container_image. Pinned version table is in the
# adjacent README.md; bump pins via a follow-up AD when the upstream cohort
# has a coherent set of compatible releases.
#
# Architecture: python:3.12-slim base + non-root user + pre-installed
# office/PDF/Playwright stack + entrypoint that honors per-session
# requirements.txt (AD-815e auto pip-install).

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DEBIAN_FRONTEND=noninteractive

# System deps: Playwright Chromium needs a long list of libs; WeasyPrint
# needs the fontconfig + cairo stack. Apt install in one layer to keep
# image size sane.
RUN apt-get update && apt-get install -y --no-install-recommends \
        # Playwright (Chromium runtime deps)
        libnss3 libnspr4 libdbus-1-3 libatk1.0-0 libatk-bridge2.0-0 \
        libcups2 libdrm2 libxcomposite1 libxdamage1 libxfixes3 \
        libxrandr2 libgbm1 libxkbcommon0 libpango-1.0-0 libcairo2 \
        libasound2 libatspi2.0-0 \
        # WeasyPrint / cairo / fontconfig
        libpangocairo-1.0-0 libpangoft2-1.0-0 fonts-liberation \
        # build/runtime convenience
        ca-certificates curl tini \
    && rm -rf /var/lib/apt/lists/*

# Non-root user + workspace mount point.
RUN useradd --create-home --uid 1500 --shell /bin/bash probos && \
    mkdir -p /workspace && chown probos:probos /workspace && chmod 0750 /workspace

WORKDIR /workspace

# Base Python stack. Version pins are documented in the adjacent README.md
# (AD-815d-pins). Update the README in lockstep when you bump anything here.
RUN pip install --no-cache-dir \
        # Office docs
        "python-docx==1.1.2" \
        "openpyxl==3.1.5" \
        "python-pptx==0.6.23" \
        "xlsxwriter==3.2.0" \
        # PDF
        "weasyprint==62.3" \
        "reportlab==4.2.5" \
        # Images
        "Pillow==10.4.0" \
        # Data / tabular
        "pandas==2.2.3" \
        # Markup
        "markdown==3.7" \
        "beautifulsoup4==4.12.3" \
        "lxml==5.3.0" \
        "pyyaml==6.0.2" \
        "jinja2==3.1.4" \
        # HTTP
        "httpx==0.28.1" \
        "requests==2.32.3" \
        # Playwright (AD-815f) — install browsers in a separate layer
        # so a Chromium re-pin doesn't invalidate the python deps layer.
        "playwright==1.47.0"

# Install Chromium for Playwright. --with-deps not used here because we
# already apt-installed runtime libs above (keeps the layer deterministic).
RUN python -m playwright install chromium

USER probos
ENV PATH="/home/probos/.local/bin:${PATH}"

COPY cowork-entrypoint.sh /usr/local/bin/cowork-entrypoint
USER root
RUN chmod +x /usr/local/bin/cowork-entrypoint
USER probos

ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/cowork-entrypoint"]
CMD ["python", "-c", "print('probos cowork-base ready')"]
