# tests/engine/test_spec_adapter_speckit.py
"""
Tests for SpecFormat.SPEC_KIT — the fifth spec input format.

A spec-kit feature directory contains the artifact conventions produced by the
github/spec-kit workflow: spec.md (user stories + functional requirements),
plan.md (technical context) and tasks.md (task lines `[ID] [P?] [Story]`
with file paths, grouped into phases). The adapter normalizes it into
NormalizedSpec; speckit_tasks_to_slices maps parsed tasks onto TaskSlice
for the slicer/planning_engine chain. Execution stays with the engine —
this is an input format only.
"""
import shutil
from pathlib import Path

import pytest

from src.engine.spec_adapter import (
    NormalizedSpec,
    SpecAdapter,
    SpecFormat,
    speckit_tasks_to_slices,
)

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "speckit_feature"


def _copy_fixture(tmp_path: Path, *, without: str | None = None) -> Path:
    """Copy the committed fixture directory, optionally dropping one file."""
    target = tmp_path / "001-user-notes"
    shutil.copytree(FIXTURE_DIR, target)
    if without is not None:
        (target / without).unlink()
    return target


class TestSpecKitDetection:
    def test_spec_format_has_spec_kit_member(self):
        assert SpecFormat.SPEC_KIT.value == "spec_kit"

    def test_detects_speckit_directory(self):
        adapter = SpecAdapter()
        spec = adapter.load(FIXTURE_DIR)
        assert isinstance(spec, NormalizedSpec)
        assert adapter.last_format == SpecFormat.SPEC_KIT

    def test_json_detection_unchanged(self):
        # Existing file-based formats must keep working exactly as before.
        adapter = SpecAdapter()
        spec = adapter.load(Path("tests/fixtures/minimal_requirements.json"))
        assert adapter.last_format == SpecFormat.SIMPLE
        assert len(spec.requirements) == 3

    def test_documentation_detection_takes_precedence(self, tmp_path, monkeypatch):
        # A directory that matches the DOCUMENTATION indicators keeps routing
        # to the documentation normalizer even if spec-kit files are present.
        target = _copy_fixture(tmp_path)
        (target / "MASTER_DOCUMENT.md").write_text("# Master", encoding="utf-8")

        sentinel = NormalizedSpec(
            project_name="doc", project_description="", requirements=[],
            tech_stack={}, context_layers=None, raw_spec={},
        )
        monkeypatch.setattr(
            SpecAdapter, "_normalize_documentation", lambda self, p: sentinel
        )
        adapter = SpecAdapter()
        assert adapter.load(target) is sentinel
        assert adapter.last_format == SpecFormat.DOCUMENTATION

    def test_dir_without_tasks_md_is_not_speckit(self, tmp_path):
        # spec.md alone is not a spec-kit feature directory; the existing
        # directory fallback (spec file lookup) applies and fails as before.
        target = _copy_fixture(tmp_path, without="tasks.md")
        with pytest.raises(FileNotFoundError):
            SpecAdapter().load(target)


class TestSpecKitParsing:
    @pytest.fixture()
    def spec(self) -> NormalizedSpec:
        return SpecAdapter().load(FIXTURE_DIR)

    def test_project_name_from_spec_title(self, spec):
        assert spec.project_name == "User Notes"

    def test_requirements_from_user_stories(self, spec):
        ids = [r.req_id for r in spec.requirements]
        assert "US1" in ids and "US2" in ids and "US3" in ids
        us1 = next(r for r in spec.requirements if r.req_id == "US1")
        assert us1.title == "Create note"
        assert "capture ideas" in us1.description
        assert us1.source == "spec.md:user_story"

    def test_requirements_from_functional_requirements(self, spec):
        ids = [r.req_id for r in spec.requirements]
        for fr in ("FR-001", "FR-002", "FR-003", "FR-004"):
            assert fr in ids
        fr1 = next(r for r in spec.requirements if r.req_id == "FR-001")
        assert "non-empty title" in fr1.title
        assert fr1.source == "spec.md:functional_requirement"

    def test_story_priority_mapping(self, spec):
        by_id = {r.req_id: r for r in spec.requirements}
        assert by_id["US1"].priority == "high"    # P1
        assert by_id["US2"].priority == "medium"  # P2
        assert by_id["US3"].priority == "low"     # P3

    def test_tech_stack_from_plan(self, spec):
        assert spec.tech_stack["id"] == "spec_kit_stack"
        assert spec.tech_stack["backend"]["language"] == "Python 3.11"
        assert spec.tech_stack["backend"]["framework"] == "FastAPI"
        assert spec.tech_stack["database"]["type"] == "PostgreSQL"

    def test_tasks_parsed_with_ids_flags_and_paths(self, spec):
        tasks = spec.context_layers.tasks
        assert len(tasks) == 10
        by_id = {t["task_id"]: t for t in tasks}

        assert by_id["T002"]["parallel"] is True
        assert by_id["T001"]["parallel"] is False

        assert by_id["T004"]["story"] == "US1"
        assert by_id["T004"]["file_paths"] == ["src/models/note.py"]
        assert by_id["T001"]["story"] is None

        assert by_id["T003"]["file_paths"] == ["migrations/001_create_notes.sql"]
        assert by_id["T009"]["completed"] is True
        assert by_id["T008"]["completed"] is False

    def test_tasks_keep_phase_grouping(self, spec):
        by_id = {t["task_id"]: t for t in spec.context_layers.tasks}
        assert by_id["T001"]["phase"] == "Phase 1: Setup"
        assert by_id["T004"]["phase"].startswith("Phase 3: User Story 1")

    def test_parse_is_deterministic(self):
        first = SpecAdapter().load(FIXTURE_DIR).to_dict()
        second = SpecAdapter().load(FIXTURE_DIR).to_dict()
        assert first == second


class TestSpecKitTaskSlices:
    @pytest.fixture()
    def slices(self):
        spec = SpecAdapter().load(FIXTURE_DIR)
        return speckit_tasks_to_slices(spec, job_id=42)

    def test_one_slice_per_task(self, slices):
        assert len(slices) == 10
        assert [s.slice_id for s in slices] == [
            f"sk-t{n:03d}" for n in range(1, 11)
        ]

    def test_parallel_flag_maps_to_can_parallelize(self, slices):
        by_id = {s.slice_id: s for s in slices}
        assert by_id["sk-t002"].can_parallelize is True
        assert by_id["sk-t001"].can_parallelize is False
        assert by_id["sk-t007"].can_parallelize is True

    def test_depth_follows_phase_order(self, slices):
        by_id = {s.slice_id: s for s in slices}
        assert by_id["sk-t001"].depth == 0  # Phase 1
        assert by_id["sk-t003"].depth == 1  # Phase 2
        assert by_id["sk-t004"].depth == 2  # Phase 3
        assert by_id["sk-t010"].depth == 5  # Phase 6

    def test_story_becomes_feature(self, slices):
        by_id = {s.slice_id: s for s in slices}
        assert by_id["sk-t004"].feature == "US1"
        assert by_id["sk-t001"].feature is None

    def test_sequential_tasks_chain_within_phase(self, slices):
        by_id = {s.slice_id: s for s in slices}
        # T005 and T006 are sequential ([P] absent) and follow T004 in Phase 3.
        assert by_id["sk-t005"].depends_on == ["sk-t004"]
        assert by_id["sk-t006"].depends_on == ["sk-t005"]
        # Parallel tasks carry no intra-phase dependency.
        assert by_id["sk-t004"].depends_on == []
        assert by_id["sk-t007"].depends_on == []

    def test_requirement_details_carry_file_paths(self, slices):
        by_id = {s.slice_id: s for s in slices}
        detail = by_id["sk-t004"].requirement_details[0]
        assert detail["id"] == "T004"
        assert detail["file_paths"] == ["src/models/note.py"]


class TestSpecKitFailClosed:
    def test_missing_plan_md_raises_clear_error(self, tmp_path):
        target = _copy_fixture(tmp_path, without="plan.md")
        with pytest.raises(FileNotFoundError, match="plan.md"):
            SpecAdapter().load(target)

    def test_tasks_md_without_tasks_raises(self, tmp_path):
        target = _copy_fixture(tmp_path)
        (target / "tasks.md").write_text("# Tasks: empty\n\nno task lines\n", encoding="utf-8")
        with pytest.raises(ValueError, match="no tasks"):
            SpecAdapter().load(target)

    def test_duplicate_task_id_raises(self, tmp_path):
        target = _copy_fixture(tmp_path)
        tasks = (target / "tasks.md").read_text(encoding="utf-8")
        (target / "tasks.md").write_text(
            tasks + "\n- [ ] T004 Duplicate id in src/models/other.py\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="[Dd]uplicate"):
            SpecAdapter().load(target)
