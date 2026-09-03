from pathlib import Path

import yaml

from mcp_plugins.servers.grpc_host.space_cli import main

FIXTURE = Path(__file__).parent / "fixtures" / "space_notes_contract.yaml"


def _target(tmp_path: Path) -> Path:
    """A minimal vibemind-os layout with an existing registry."""
    (tmp_path / "config").mkdir(parents=True)
    (tmp_path / "config" / "space_agent_registry.yml").write_text(
        "version: 1\nspaces:\n  existing:\n    agent: brain-existing\n",
        encoding="utf-8",
    )
    (tmp_path / "brain" / "the_brain" / "configs" / "agents").mkdir(parents=True)
    (tmp_path / "voice" / "electron-app").mkdir(parents=True)
    return tmp_path


def test_render_registry_inserts_without_dropping_other_spaces(tmp_path):
    target = _target(tmp_path)
    code = main(["render", "registry", "--contract", str(FIXTURE),
                 "--target", str(target)])
    assert code == 0

    data = yaml.safe_load(
        (target / "config" / "space_agent_registry.yml").read_text(encoding="utf-8")
    )
    assert "existing" in data["spaces"]
    assert data["spaces"]["notes"]["agent"] == "brain-notes"


def test_render_registry_refuses_to_overwrite_existing_space(tmp_path):
    target = _target(tmp_path)
    assert main(["render", "registry", "--contract", str(FIXTURE),
                 "--target", str(target)]) == 0
    # second run must refuse
    assert main(["render", "registry", "--contract", str(FIXTURE),
                 "--target", str(target)]) == 1


def test_render_all_writes_every_artefact(tmp_path):
    target = _target(tmp_path)
    assert main(["render", "all", "--contract", str(FIXTURE),
                 "--target", str(target)]) == 0

    assert (target / "brain" / "the_brain" / "configs" / "agents"
            / "brain-notes.yaml").is_file()
    assert (target / "spaces" / "notes" / "server.py").is_file()
    assert (target / "voice" / "electron-app" / "notes-manager.js").is_file()
    assert (target / "voice" / "electron-app" / "notes-preload.js").is_file()
    assert (target / "spaces" / "notes" / "tests"
            / "test_notes_registry.py").is_file()


def test_verify_contract_fails_when_artefacts_are_missing(tmp_path):
    target = _target(tmp_path)
    assert main(["verify", "contract", "--contract", str(FIXTURE),
                 "--target", str(target)]) == 1


def test_verify_contract_passes_after_render_all(tmp_path):
    target = _target(tmp_path)
    assert main(["render", "all", "--contract", str(FIXTURE),
                 "--target", str(target)]) == 0
    assert main(["verify", "contract", "--contract", str(FIXTURE),
                 "--target", str(target)]) == 0


def test_invalid_contract_exits_nonzero(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("id: notes\n", encoding="utf-8")  # missing everything else
    assert main(["verify", "contract", "--contract", str(bad),
                 "--target", str(_target(tmp_path))]) == 1
