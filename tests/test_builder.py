"""
Tests for the builder (compiler) module.
Validates that .aispec files compile to the correct IR, DAG, and lockfile artifacts.
"""
import json
import pytest
from pathlib import Path
from razi.compiler.compile import compile_spec


BASE_DIR = Path(__file__).parent.parent


def test_build_escalation_spec(tmp_path):
    """escalation.aispec must compile without errors."""
    build_dir = compile_spec("examples/escalation.aispec", BASE_DIR)
    assert build_dir.exists()
    assert (build_dir / "ir.json").exists()
    assert (build_dir / "dag.json").exists()
    assert (build_dir / "lock.json").exists()
    assert (build_dir / "policy.json").exists()


def test_build_produces_valid_ir(tmp_path):
    """Compiled IR must contain required fields."""
    build_dir = compile_spec("examples/escalation.aispec", BASE_DIR)
    with open(build_dir / "ir.json") as f:
        ir = json.load(f)
    assert "name" in ir
    assert "input_schema" in ir
    assert "output_schema" in ir


def test_build_produces_valid_dag():
    """Compiled DAG must contain at least one evidence.index and one synth.json node."""
    build_dir = compile_spec("examples/escalation.aispec", BASE_DIR)
    with open(build_dir / "dag.json") as f:
        dag = json.load(f)
    ops = [n["op"] for n in dag]
    assert "evidence.index" in ops
    assert "synth.json" in ops


def test_build_produces_lock_with_hashes():
    """Lockfile must contain spec and template hashes for determinism."""
    build_dir = compile_spec("examples/escalation.aispec", BASE_DIR)
    with open(build_dir / "lock.json") as f:
        lock = json.load(f)
    assert "spec_hash" in lock
    assert "template_sha256" in lock


def test_build_invalid_spec_raises():
    """Compiling a non-existent spec must raise an error."""
    with pytest.raises(Exception):
        compile_spec("examples/nonexistent.aispec", BASE_DIR)
