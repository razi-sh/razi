"""
razi.runner — public alias for razi.runtime.runtime
Provides the flat API surface documented in the playbook.
"""
from razi.runtime.runtime import execute_run as run_spec, RunError  # noqa: F401
