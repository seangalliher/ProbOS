"""AD-801: built-in doctor checks. Importing the package runs each
sub-module's `register_check` side effect, so the registry is populated
on first `from probos.doctor import ...`.

AD-1137: the Python version check runs first and the optional-extras check
follows the LLM check, so the getting-started checks lead the report.
"""

from probos.doctor.checks import (  # noqa: F401
    python_check,
    config_check,
    data_dir_check,
    llm_check,
    extras_check,
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
    channel_matrix_check,
    channel_discord_check,
    channel_teams_check,
    channel_gmail_check,
)
