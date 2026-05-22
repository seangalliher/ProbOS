"""AD-801: built-in doctor checks. Importing the package runs each
sub-module's `register_check` side effect, so the registry is populated
on first `from probos.doctor import ...`.
"""

from probos.doctor.checks import (  # noqa: F401
    config_check,
    data_dir_check,
    llm_check,
    nats_check,
    chroma_check,
    security_check,
    disk_check,
    federation_check,
    overlay_check,
    sandbox_check,
    pairing_check,
    channel_telegram_check,
    channel_slack_check,
)
