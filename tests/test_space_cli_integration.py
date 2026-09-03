# tests/test_space_cli_integration.py
"""End-to-end dry run of wave 1: contract in, verified artefacts out."""
import subprocess
import sys
from pathlib import Path

import pytest

from mcp_plugins.servers.grpc_host.space_cli import main

FIXTURE = Path(__file__).parent / "fixtures" / "space_notes_contract.yaml"


@pytest.fixture()
def target(tmp_path: Path) -> Path:
    """A vibemind-os-shaped tree with a populated registry."""
    (tmp_path / "config").mkdir(parents=True)
    (tmp_path / "config" / "space_agent_registry.yml").write_text(
        "version: 1\n"
        "defaults:\n"
        "  fallback_agent: brain-fallback\n"
        "spaces:\n"
        "  bubbles:\n"
        "    agent: brain-bubbles\n"
        "    prefixes: [bubble.]\n"
        "    enabled: true\n",
        encoding="utf-8",
    )
    (tmp_path / "brain" / "the_brain" / "configs" / "agents").mkdir(parents=True)
    (tmp_path / "voice" / "electron-app").mkdir(parents=True)
    return tmp_path


def test_full_chain_renders_and_verifies(target: Path):
    assert main(["render", "all", "--contract", str(FIXTURE),
                 "--target", str(target)]) == 0
    assert main(["verify", "contract", "--contract", str(FIXTURE),
                 "--target", str(target)]) == 0


def test_existing_space_survives_generation(target: Path):
    import yaml

    main(["render", "all", "--contract", str(FIXTURE),
          "--target", str(target)])
    data = yaml.safe_load(
        (target / "config" / "space_agent_registry.yml").read_text(encoding="utf-8")
    )
    assert "bubbles" in data["spaces"]
    assert "notes" in data["spaces"]
    assert data["defaults"]["fallback_agent"] == "brain-fallback"


def test_generated_tests_pass_against_generated_artefacts(target: Path):
    """The tests the pipeline writes must hold for what it produced."""
    main(["render", "all", "--contract", str(FIXTURE),
          "--target", str(target)])

    tests_dir = target / "spaces" / "notes" / "tests"
    result = subprocess.run(
        [sys.executable, "-m", "pytest", str(tests_dir), "-q", "-p",
         "no:cacheprovider"],
        cwd=str(target), capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_generated_mcp_server_imports_cleanly(target: Path):
    """The scaffold must be loadable, not just syntactically valid."""
    main(["render", "mcp-server", "--contract", str(FIXTURE),
          "--target", str(target)])

    server = target / "spaces" / "notes" / "server.py"
    result = subprocess.run(
        [sys.executable, "-c",
         f"import ast, pathlib; ast.parse(pathlib.Path(r'{server}').read_text())"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
