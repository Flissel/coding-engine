from pathlib import Path

import yaml

from mcp_plugins.servers.grpc_host.space_cli import main

FIXTURE = Path(__file__).parent / "fixtures" / "space_notes_contract.yaml"
READONLY_FIXTURE = (
    Path(__file__).parent / "fixtures" / "space_readonly_contract.yaml"
)


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


def test_render_registry_refuses_colliding_prefix(tmp_path, capsys):
    """FIX 2: bindings_registry builds a plain prefix -> binding dict, so a
    second space claiming an already-registered prefix would silently win
    every routing lookup for it. This must be refused before anything is
    written, naming both the prefix and the space that already holds it."""
    target = _target(tmp_path)
    registry_path = target / "config" / "space_agent_registry.yml"
    registry_path.write_text(
        "version: 1\n"
        "spaces:\n"
        "  other:\n"
        "    agent: brain-other\n"
        "    prefixes: [notes.]\n",
        encoding="utf-8",
    )

    code = main(["render", "registry", "--contract", str(FIXTURE),
                 "--target", str(target)])
    assert code == 1

    err = capsys.readouterr().err
    assert "notes." in err
    assert "other" in err

    # the registry must be untouched - no partial write for a refused space
    data = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    assert "notes" not in data["spaces"]


def test_render_registry_allows_non_colliding_prefix(tmp_path):
    """A space with a prefix nobody else holds must still register fine -
    the collision check must not be over-broad."""
    target = _target(tmp_path)
    registry_path = target / "config" / "space_agent_registry.yml"
    registry_path.write_text(
        "version: 1\n"
        "spaces:\n"
        "  other:\n"
        "    agent: brain-other\n"
        "    prefixes: [totally_different.]\n",
        encoding="utf-8",
    )

    code = main(["render", "registry", "--contract", str(FIXTURE),
                 "--target", str(target)])
    assert code == 0


def test_render_registry_rolls_back_on_any_verification_error(
    tmp_path, monkeypatch,
):
    """FIX 6: the post-write re-read only caught yaml.YAMLError, so any
    other exception - an OSError, or a defensive-check gap - would
    propagate straight out of main() and skip the rollback, leaving the
    shared registry half-written. Any exception during that re-read must
    now be treated as "did not land" and trigger the rollback."""
    import mcp_plugins.servers.grpc_host.space_cli as space_cli_module

    target = _target(tmp_path)
    registry_path = target / "config" / "space_agent_registry.yml"
    original_text = registry_path.read_text(encoding="utf-8")

    real_load = space_cli_module.yaml.safe_load
    calls = {"n": 0}

    def flaky_load(text):
        calls["n"] += 1
        # Call order: (1) load_contract parsing the contract YAML,
        # (2) _render_registry parsing the original registry text,
        # (3) _render_registry's post-write verification re-read - the one
        # this test targets.
        if calls["n"] == 3:
            # Simulate a non-YAMLError failure (e.g. a transient OSError
            # surfacing through the read-back) on the post-write
            # verification load specifically, not the earlier parses.
            raise OSError("simulated failure while reading back the registry")
        return real_load(text)

    monkeypatch.setattr(space_cli_module.yaml, "safe_load", flaky_load)

    code = main(["render", "registry", "--contract", str(FIXTURE),
                 "--target", str(target)])
    assert code == 1
    assert calls["n"] == 3, "test did not exercise the intended read-back call"
    assert registry_path.read_text(encoding="utf-8") == original_text


def test_render_registry_rolls_back_when_landed_entry_is_not_a_mapping(
    tmp_path, monkeypatch,
):
    """FIX 6: the old check called entry.get("agent") straight after
    `entry is not None`, so a landed-but-non-mapping entry (a scalar or
    list where the space's block should be) would raise AttributeError
    instead of being treated as "did not land". The shape check must be
    defensive, not just a None check."""
    import mcp_plugins.servers.grpc_host.space_cli as space_cli_module

    target = _target(tmp_path)
    registry_path = target / "config" / "space_agent_registry.yml"
    original_text = registry_path.read_text(encoding="utf-8")

    real_load = space_cli_module.yaml.safe_load
    calls = {"n": 0}

    def flaky_load(text):
        calls["n"] += 1
        # See test_render_registry_rolls_back_on_any_verification_error for
        # why call 3 is the post-write verification re-read.
        if calls["n"] == 3:
            return {"spaces": {"notes": "not-a-mapping"}}
        return real_load(text)

    monkeypatch.setattr(space_cli_module.yaml, "safe_load", flaky_load)

    code = main(["render", "registry", "--contract", str(FIXTURE),
                 "--target", str(target)])
    assert code == 1
    assert calls["n"] == 3, "test did not exercise the intended read-back call"
    assert registry_path.read_text(encoding="utf-8") == original_text


def test_render_registry_refuses_when_registry_has_no_spaces_key(tmp_path):
    """A registry without a `spaces:` mapping must not be appended to."""
    target = _target(tmp_path)
    registry_path = target / "config" / "space_agent_registry.yml"
    registry_path.write_text("version: 1\n", encoding="utf-8")

    code = main(["render", "registry", "--contract", str(FIXTURE),
                 "--target", str(target)])
    assert code == 1

    # the registry is untouched and still parsable
    data = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    assert data == {"version": 1}


def test_render_registry_refuses_when_a_key_follows_the_spaces_block(tmp_path):
    """A raw textual append mis-nests under a top-level key that follows
    `spaces:` - this must be caught and rolled back, not silently succeed
    with the space unregistered."""
    target = _target(tmp_path)
    registry_path = target / "config" / "space_agent_registry.yml"
    registry_path.write_text(
        "version: 1\n"
        "spaces:\n"
        "  existing:\n"
        "    agent: brain-existing\n"
        "metadata:\n"
        "  owner: ops\n",
        encoding="utf-8",
    )

    code = main(["render", "registry", "--contract", str(FIXTURE),
                 "--target", str(target)])
    assert code == 1

    # the registry is rolled back to its original content and still parses
    data = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    assert "notes" not in data["spaces"]
    assert data["metadata"] == {"owner": "ops"}


def test_verify_contract_fails_when_artefacts_are_missing(tmp_path):
    target = _target(tmp_path)
    assert main(["verify", "contract", "--contract", str(FIXTURE),
                 "--target", str(target)]) == 1


def test_verify_contract_fails_on_uncarried_truth_validator_after_render_all(
    tmp_path, capsys,
):
    """FIX 1: a write event's truth validator is checked by space_contract
    at load time but no renderer emits it anywhere downstream, so a fully
    rendered write-event space must still fail verify contract - loudly,
    and naming the event - rather than reporting "contract satisfied" over
    a silently missing ground-truth re-query."""
    target = _target(tmp_path)
    assert main(["render", "all", "--contract", str(FIXTURE),
                 "--target", str(target)]) == 0
    assert main(["verify", "contract", "--contract", str(FIXTURE),
                 "--target", str(target)]) == 1

    err = capsys.readouterr().err
    assert "truth validator for 'notes.create'" in err
    assert "carried by no generated artefact" in err
    # The message must read as a known, documented limitation of this
    # wave, not as evidence the generated space is broken/corrupt.
    assert "wave-1" in err
    assert "not a" in err and "corrupted space" in err


def test_verify_contract_passes_for_read_only_contract(tmp_path):
    """A contract with no write events (so no truth validators at all)
    must still get a clean pass after render all - FIX 1 only tightens
    the check for events that actually declare a truth validator."""
    target = _target(tmp_path)
    assert main(["render", "all", "--contract", str(READONLY_FIXTURE),
                 "--target", str(target)]) == 0
    assert main(["verify", "contract", "--contract", str(READONLY_FIXTURE),
                 "--target", str(target)]) == 0


def test_invalid_contract_exits_nonzero(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("id: notes\n", encoding="utf-8")  # missing everything else
    assert main(["verify", "contract", "--contract", str(bad),
                 "--target", str(_target(tmp_path))]) == 1
