# Feature Specification: User Notes

**Feature Branch**: `001-user-notes`
**Created**: 2026-08-14
**Status**: Draft

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Create note (Priority: P1)

As a registered user, I want to create a note with a title and body so that I can capture ideas quickly.

**Why this priority**: Core value of the product; nothing works without note creation.

**Acceptance Scenarios**:

1. **Given** an authenticated user, **When** they submit a title and body, **Then** a note is persisted and returned with an id.
2. **Given** an empty title, **When** the user submits, **Then** the request is rejected with a validation error.

### User Story 2 - List notes (Priority: P2)

As a registered user, I want to see my notes ordered by last update so that I can find recent work first.

**Why this priority**: Retrieval is the second half of the core loop.

**Acceptance Scenarios**:

1. **Given** three existing notes, **When** the user opens the list, **Then** all three appear ordered by update time descending.

### User Story 3 - Delete note (Priority: P3)

As a registered user, I want to delete a note so that outdated content disappears.

**Acceptance Scenarios**:

1. **Given** an existing note, **When** the user deletes it, **Then** it no longer appears in the list.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST allow creating a note with a non-empty title and an optional body.
- **FR-002**: System MUST return the persisted note including its generated id.
- **FR-003**: System MUST list a user's notes ordered by update time descending.
- **FR-004**: System MUST allow deleting a note owned by the requesting user.

### Key Entities

- **Note**: id, title, body, updated_at, owner_id
