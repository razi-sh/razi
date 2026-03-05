"""
razi.builder — public alias for razi.compiler.compile
Provides the flat API surface documented in the playbook.
"""
from razi.compiler.compile import compile_spec as build_spec, CompileError  # noqa: F401
from razi.spec.validator import validate_spec  # noqa: F401
