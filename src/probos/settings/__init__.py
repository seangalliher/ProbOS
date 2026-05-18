"""AD-741: HXI Settings panel — section registry + config API support.

The registry (``section_registry.py``) is the single source of truth for
the operator-facing sidebar in the Settings overlay panel. Both the
``/api/config`` router (server) and the SettingsSidebar component (UI)
consume it.
"""
