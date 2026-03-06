from __future__ import annotations

from pathlib import Path
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "safe_repl", *args],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=10,
    )


def test_cli_list_functions_subprocess() -> None:
    result = run_cli("--list-functions")
    assert result.returncode == 0
    assert "Allowed functions:" in result.stdout
    assert "abs" in result.stdout


def test_cli_list_nodes_subprocess() -> None:
    result = run_cli("--list-nodes")
    assert result.returncode == 0
    assert "Allowed AST nodes:" in result.stdout
    assert "Assign" in result.stdout


def test_cli_invalid_node_subprocess() -> None:
    result = run_cli("--allow-nodes", "DefinitelyNotAnAstNode")
    assert result.returncode == 1
    assert "Unknown node type" in result.stderr


def test_cli_invalid_import_subprocess() -> None:
    result = run_cli("--import", "definitely_not_a_real_module_xyz")
    assert result.returncode == 1
    assert "Failed to import" in result.stderr
