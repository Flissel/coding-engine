from pathlib import Path

from mcp_plugins.servers.grpc_host.space_contract import load_contract
from mcp_plugins.servers.grpc_host.space_task_planner import plan_space_tasks

FIXTURE = Path(__file__).parent / "fixtures" / "space_notes_contract.yaml"


def _tasks():
    return plan_space_tasks(load_contract(FIXTURE))


def test_plan_covers_every_artefact():
    types = [t.type for t in _tasks()]
    assert types.count("space_registry") == 1
    assert types.count("space_manifest") == 1
    assert types.count("space_mcp_server") == 1
    assert types.count("space_electron") == 1
    assert types.count("space_tests") == 1
    assert "verify_space_contract" in types
    assert "verify_space_tests" in types
    assert "verify_space_status" in types


def test_task_ids_are_unique_and_prefixed():
    ids = [t.id for t in _tasks()]
    assert len(ids) == len(set(ids))
    assert all(i.startswith("notes-") for i in ids)


def test_dependencies_form_a_valid_order():
    """Every dependency must be declared by an earlier task."""
    seen: set[str] = set()
    for task in _tasks():
        for dep in task.dependencies:
            assert dep in seen, f"{task.id} depends on unseen {dep}"
        seen.add(task.id)


def test_mcp_server_waits_for_registry_and_manifest():
    tasks = {t.type: t for t in _tasks()}
    deps = tasks["space_mcp_server"].dependencies
    assert tasks["space_registry"].id in deps
    assert tasks["space_manifest"].id in deps


def test_verify_runs_after_every_build_task():
    tasks = _tasks()
    build_ids = {t.id for t in tasks if not t.type.startswith("verify_")}
    contract_verify = next(t for t in tasks
                           if t.type == "verify_space_contract")
    assert build_ids <= set(contract_verify.dependencies)


def test_headless_space_has_no_electron_task():
    from mcp_plugins.servers.grpc_host.space_contract import SpaceContract

    contract = load_contract(FIXTURE)
    headless = SpaceContract(
        **{**contract.model_dump(), "ui": {"embed": "none"}}
    )
    types = [t.type for t in plan_space_tasks(headless)]
    assert "space_electron" not in types


def test_output_files_are_declared():
    tasks = {t.type: t for t in _tasks()}
    assert tasks["space_registry"].output_files == [
        "config/space_agent_registry.yml"
    ]
    assert tasks["space_manifest"].output_files == [
        "brain/the_brain/configs/agents/brain-notes.yaml"
    ]
