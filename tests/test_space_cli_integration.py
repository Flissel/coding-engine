# tests/test_space_cli_integration.py
"""End-to-end dry run of wave 1: contract in, verified artefacts out."""
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

from mcp_plugins.servers.grpc_host.space_cli import main

FIXTURE = Path(__file__).parent / "fixtures" / "space_notes_contract.yaml"


REGISTRY_TEXT = (
    "# VibeMind space -> agent registry. Hand-maintained; each space below\n"
    "# documents its own wiring inline. Keep comments when editing.\n"
    "version: 1\n"
    "defaults:\n"
    "  fallback_agent: brain-fallback\n"
    "spaces:\n"
    "  bubbles:\n"
    "    agent: brain-bubbles\n"
    "    prefixes: [bubble.]  # canvas + list events funnel through this prefix\n"
    "    enabled: true\n"
    "    description: \"Idea bubbles on the canvas.\"\n"
    "    mcp_servers: [spaces-bubbles]\n"
    "    mcp_tools:\n"
    "      spaces-bubbles: [bubble_create, bubble_list]  # keep sorted\n"
    "    events:\n"
    "      bubble.list:\n"
    "        tool: bubble_list\n"
    "        required_params: []\n"
    "      bubble.create:\n"
    "        tool: bubble_create\n"
    "        required_params: [title]\n"
    "        # write event: needs full provenance, not just a required param\n"
    "        required_provenance: [approval_ref, cost_ref]\n"
    "        execution: {kind: mcp, server: spaces-bubbles}\n"
)


@pytest.fixture()
def target(tmp_path: Path) -> Path:
    """A vibemind-os-shaped tree with a populated registry.

    The registry mirrors the real config/space_agent_registry.yml: a full
    mcp_tools/events block for the pre-existing space, and inline `#`
    comments including one *inside* that space's own entry. render_registry
    appends rather than parses-and-rewrites specifically so those survive
    (see space_cli._render_registry's docstring); a comment-free,
    single-key stub would never exercise that promise.
    """
    (tmp_path / "config").mkdir(parents=True)
    (tmp_path / "config" / "space_agent_registry.yml").write_text(
        REGISTRY_TEXT, encoding="utf-8",
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


def test_registry_comments_survive_generation(target: Path):
    """render_registry appends specifically to keep the real registry's
    hand-written comments intact (see space_cli._render_registry's
    docstring) - a parse-and-rewrite via yaml.safe_dump would silently
    drop every one of them. Assert that promise on the raw text, since
    yaml.safe_load discards comments and so cannot see this regression.
    """
    registry_path = target / "config" / "space_agent_registry.yml"

    main(["render", "all", "--contract", str(FIXTURE), "--target", str(target)])

    text_after = registry_path.read_text(encoding="utf-8")
    # The whole original file, comments included, must still be a literal
    # prefix of the result: render_registry only ever appends.
    assert text_after.startswith(REGISTRY_TEXT)
    # And, explicitly, the comment that sits *inside* the pre-existing
    # space's own entry (not just a file-header comment) survived.
    assert "# canvas + list events funnel through this prefix\n" in text_after
    assert "# keep sorted\n" in text_after
    assert (
        "# write event: needs full provenance, not just a required param\n"
        in text_after
    )


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
    """The scaffold must be loadable, not just syntactically valid.

    ``ast.parse`` only proves the file is well-formed Python - it would
    happily accept a call to a name that doesn't exist in the imported
    module (e.g. ``FastMCPXXX``). Actually loading the module exercises
    the real imports (``mcp``, ``starlette``) and the module-level
    ``FastMCP(...)`` construction, which is what "loadable" means here.
    """
    main(["render", "mcp-server", "--contract", str(FIXTURE),
          "--target", str(target)])

    server = target / "spaces" / "notes" / "server.py"
    spec = importlib.util.spec_from_file_location("space_notes_server", server)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # raises if an import or name is broken
    assert hasattr(module, "mcp")
