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
    verifier_check,
    nats_check,
    chroma_check,
    crew_enrollment_check,
    token_accounting_check,
    role_template_check,  # BF-917/BF-915: after token_accounting, which stays next to crew_enrollment
    security_check,
    crew_scope_check,
    disk_check,
    federation_check,
    overlay_check,
    sandbox_check,
    command_policy_check,
    pairing_check,
    channel_telegram_check,
    channel_slack_check,
    channel_matrix_check,
    channel_discord_check,
    channel_teams_check,
    channel_gmail_check,
)
