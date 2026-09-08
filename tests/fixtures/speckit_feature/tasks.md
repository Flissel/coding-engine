# Tasks: User Notes

**Input**: Design documents from `specs/001-user-notes/`
**Prerequisites**: plan.md (required), spec.md (required)

**Organization**: Tasks are grouped by user story. `[P]` marks tasks that can run in parallel
because they touch different files and have no dependency on an incomplete task.

## Phase 1: Setup

- [ ] T001 Create project structure per implementation plan
- [ ] T002 [P] Configure linting and formatting in pyproject.toml

## Phase 2: Foundational

- [ ] T003 Create database migration for notes table in migrations/001_create_notes.sql

## Phase 3: User Story 1 - Create note (Priority: P1)

- [ ] T004 [P] [US1] Create Note model in src/models/note.py
- [ ] T005 [US1] Implement POST /notes endpoint in src/api/notes.py
- [ ] T006 [US1] Add validation for empty titles in src/api/notes.py

**Checkpoint**: User Story 1 is independently testable via POST /notes.

## Phase 4: User Story 2 - List notes (Priority: P2)

- [ ] T007 [P] [US2] Implement GET /notes endpoint in src/api/notes.py
- [ ] T008 [P] [US2] Add list ordering test in tests/test_notes.py

## Phase 5: User Story 3 - Delete note (Priority: P3)

- [x] T009 [US3] Implement DELETE /notes/{id} endpoint in src/api/notes.py

## Phase 6: Polish

- [ ] T010 [P] Update API documentation in docs/api.md
