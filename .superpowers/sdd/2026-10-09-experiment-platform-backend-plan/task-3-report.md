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
- The content routes currently use the existing teaching portal/API envelope conventions but do not add separate OpenAPI response decorators for every new view; runtime behavior and serializers are covered by the shared version serialization and service tests.
