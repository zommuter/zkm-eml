"""zkm-eml — filesystem-discovery shim; delegates to the zkm_eml package.

Loaded by core when the plugin is filesystem-discovered (dev-symlink workflow).
Core's _inject_plugin_venv (SB2) adds plugins/zkm-eml/src/ to sys.path before
loading this file, making zkm_eml importable here.
"""

from zkm_eml.convert import convert, reprocess, scrub  # noqa: F401
