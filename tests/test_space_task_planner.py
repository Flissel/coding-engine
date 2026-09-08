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
    assert types.count("space_capability") == 1
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
    """All three verify tasks must depend on every build task, not just one
    of them — this is what stops a partial generation from passing as
    complete."""
    tasks = _tasks()
    build_ids = {t.id for t in tasks if not t.type.startswith("verify_")}
    for verify_type in ("verify_space_contract", "verify_space_tests",
                        "verify_space_status"):
        verify_task = next(t for t in tasks if t.type == verify_type)
        assert build_ids <= set(verify_task.dependencies), (
            f"{verify_type} is missing build dependencies: "
            f"{build_ids - set(verify_task.dependencies)}"
        )


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


def test_every_planned_task_type_is_resolvable():
    """A planned type without a mapping entry would fail at runtime."""
    from mcp_plugins.servers.grpc_host.task_executor import (
        TASK_SKILL_MAPPING,
        VERIFICATION_COMMANDS,
    )

    for task in _tasks():
        assert task.type in TASK_SKILL_MAPPING, f"unmapped type: {task.type}"
        agent, skill, claude_agent, max_turns = TASK_SKILL_MAPPING[task.type]
        if agent == "BashExecutor":
            assert task.type in VERIFICATION_COMMANDS, (
                f"BashExecutor type without command: {task.type}"
            )
            assert skill is None and claude_agent is None


def test_verify_space_commands_do_not_call_a_model():
    from mcp_plugins.servers.grpc_host.task_executor import (
        TASK_SKILL_MAPPING,
    )

    for task_type in ("verify_space_contract", "verify_space_tests",
                      "verify_space_status"):
        agent, skill, claude_agent, _ = TASK_SKILL_MAPPING[task_type]
        assert agent == "BashExecutor"
        assert skill is None
        assert claude_agent is None

def test_a_contract_with_truth_gets_a_capability_task():
    """The capability entry is the only path from a contract's truth:
    to a world_observer re-query. Without a task for it, an orchestrated
    run renders every other artefact and the write event routes
    unverified."""
    tasks = {t.type: t for t in _tasks()}
    cap = tasks["space_capability"]
    assert "brain/the_brain/data/capabilities.yaml" in cap.output_files


def test_verification_waits_for_the_capability_task():
    tasks = {t.type: t for t in _tasks()}
    cap_id = tasks["space_capability"].id
    for verify_type in ("verify_space_contract", "verify_space_tests",
                        "verify_space_status"):
        assert cap_id in tasks[verify_type].dependencies, (
            f"{verify_type} would run before the capability entry exists"
        )

def test_read_only_space_gets_no_capability_task():
    """Nothing to carry, so no task - a no-op task in the graph would
    make an orchestrated run look like it wired something it did not."""
    import yaml
    from mcp_plugins.servers.grpc_host.space_contract import SpaceContract

    raw = yaml.safe_load(FIXTURE.read_text(encoding="utf-8"))
    raw["tools"] = [t for t in raw["tools"] if t["side_effect"] == "read"]
    raw["events"] = {"notes.list": raw["events"]["notes.list"]}
    types = [t.type for t in plan_space_tasks(SpaceContract(**raw))]
    assert "space_capability" not in types
