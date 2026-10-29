# Task 3 Report: Versioned Chapters and Tasks

## Status

Implemented and committed as `feat: add versioned experiment chapters and tasks`.

## Data model

- Added `TemplateChapter` and `TemplateTask` to `labtemplates`.
- Both use the existing `public_id_field`, `VersionedModel`, managed timestamps, and row versions.
- Chapters belong to `TemplateVersion`; tasks belong to `TemplateChapter`.
- Both models have draft/published status checks, positive ordering checks, scoped unique ordering constraints, JSON policy fields, and protected optional `ResourceProfile` foreign keys.
- Added migration `0004_template_chapter_task.py` without changing existing template tables or migrations.

## Service behavior

- Added transactional `create_chapter`, `update_chapter`, `create_task`, `update_task`, `reorder_chapters`, and `reorder_tasks` services.
- All mutations require `CourseStaffGrant.MANAGE_TEMPLATE` and use the existing course visibility checks.
- All mutations require the expected template-version row version and advance that version through compare-and-swap; child rows also use compare-and-swap for updates and reorder steps.
- Content edits are restricted to `TemplateVersion.DRAFT`; published and other non-draft versions are rejected.
- Duplicate, non-positive, unknown, cross-version, and mixed-parent ordering inputs are rejected with `TemplateValidationError`.
- Resource profiles are validated as active before assignment.
- Chapter/task creation emits audit and outbox events following the existing labtemplates patterns.

## API and serialization

- Added teaching routes for chapter/task collection, detail patch, and batch reorder operations.
- Added write serializers for chapter/task content and reorder payloads.
- Version responses now include chapters ordered by `sort_order`, with tasks nested and ordered by `sort_order`.
- Effective resource serialization is deterministic: task override, chapter override, then template-version default.
- Chapter/task payloads expose resource profile ids and effective resource profile ids only; publication-only image/digest fields remain on version serialization and are not introduced into content APIs.

## Verification

- `python -m pytest backend/education_experiment_platform/apps/labtemplates/tests -q`: 18 passed.
- `python manage.py check`: passed.
- `python manage.py makemigrations --check --dry-run`: passed with no changes detected.
- `python -m compileall -q education_experiment_platform/apps/labtemplates`: passed.
- `git diff --check`: passed.

## Notes and residual concerns

- The existing unrelated worktree changes were preserved and excluded from the commit.
- The content routes use the existing teaching portal/API envelope conventions and now include explicit OpenAPI request, response, parameter, and portal metadata.

## Review Round 1 Fixes

- Child chapter/task updates now require the request `If-Match` to match the parent `TemplateVersion` row version; child CAS and parent CAS occur in one transaction, preserving independent child row versions.
- Reorders now require the complete sibling collection exactly once, reject partial/duplicate/foreign ids, use a data-derived temporary offset, and emit audit/outbox records.
- Version cloning now copies chapters and tasks into the new draft version with new public ids and preserved content/resource overrides.
- Chapter/task update operations emit audit/outbox records.
- Task-create and task-reorder views map nonexistent or cross-course chapter ids to `ResourceNotFound` before precondition parsing.
- Added OpenAPI response serializers/declarations and API coverage for ETags, missing preconditions, and missing chapter mapping.

Review-round verification: `21 passed`; Ruff clean; Django system check clean; migration drift check clean.

## Review Round 2 Fixes

- Added the missing `@extend_schema` declaration to task creation, including request/response serializers, `If-Match` and `Idempotency-Key`, and teaching portal metadata.
- Version cloning now preserves the source execution specification while retaining the existing image/manual/test asset safety semantics.
- Added regression coverage proving the clone retains its execution entrypoint and passes the existing execution-spec validation/command path.

Review-round verification: `21 passed`; Ruff clean; Django system check clean; migration drift check clean; diff check clean.
