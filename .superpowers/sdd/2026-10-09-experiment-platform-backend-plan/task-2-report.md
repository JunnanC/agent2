# Task 2 Report: Academic Terms and Unified Course Context

## Scope

Implemented Task 2 in `backend/education_experiment_platform/apps/courses` only. Existing unrelated worktree changes were preserved.

## Files

- Added `models.AcademicTerm` with public ULID, versioning fields, `UPCOMING`/`CURRENT`/`CLOSED` status, date-window validation, current-status validation, and a conditional one-current-term uniqueness constraint.
- Added the required `Course.term` relation with a current-term default for legacy direct `Course.objects.create(...)` call sites. Explicit `term=None` remains invalid at the database level.
- Added migration `0005_academicterm_course_term.py`. It creates a compatibility current term, derives per-course terms from legacy teaching windows when present, and makes the course term required after backfill.
- Added `current_academic_term()`, term reference resolution, `teacher_courses_for_term(actor, term_ref)`, and `student_courses_for_term(actor, term_ref)`.
- Added `GET /api/v2/context`, preserving the existing `{data, meta}` response wrapper and exposing current term plus course id/code/title/status and staff/enrollment role.
- Added model, selector/service, API, authentication, student-context, and closed/archived exclusion tests.

## Behavior

- Teacher courses require active `CourseStaff` rows.
- Student courses require active `Enrollment` rows.
- Closed and archived courses are excluded from term-aware course selectors and context.
- Context is read-only and available to authenticated portal sessions; the user role follows the authenticated portal (`TEACHER`, `STUDENT`, or `PLATFORM_ADMIN`).
- Existing course creation and existing course response/API behavior remain unchanged apart from assigning the new term relation internally.

## Verification

- `python -m pytest education_experiment_platform/apps/courses/tests/test_models.py education_experiment_platform/apps/courses/tests/test_services.py education_experiment_platform/apps/courses/tests/test_api.py -q`
  - Result: `16 passed in 24.94s`.
- `git diff --check`
  - Result: passed.
- Migration setup was exercised by the SQLite test database and completed successfully.
- `manage.py makemigrations --check --dry-run` could not complete under default settings because the configured MySQL host `mysql` is unavailable locally (`OperationalError: Unknown server host 'mysql'`). This is an environment limitation, not a test-database failure.

## Portability concern

The one-current-term rule is represented by a conditional unique constraint and enforced by the service/model test path. SQLite accepts the conditional constraint used by the test settings. Backend-specific migration validation against MySQL could not be run because the local MySQL service/host was unavailable.

## Commit

Commit created after final verification: `feat: add academic term and course context`.

## Review Round 1 Fixes

- Corrected migration ownership: courses with no teaching window or a window active at migration time remain attached to the deterministic `LEGACY-CURRENT` term. Historical and future windows receive separate non-current terms, so active courses remain visible through current-term selectors.
- Restricted `/api/v2/context` to the authenticated portal. Teaching sessions receive only active teacher staff courses; user sessions receive only active student enrollment courses. Cross-portal memberships are no longer combined in one response.
- Standardized the context course identifier to `id`.
- Added current-window selector regression coverage and cross-portal API coverage. The migration callback itself was reviewed against historical `0004` state; the SQLite test harness cannot safely roll the shared test schema backward and forward inside one test transaction, so the stable regression asserts the same current-window ownership contract at the selector boundary.

## Review Round 1 Verification

- Focused course tests: `17 passed in 24.03s`.
- Ruff: `All checks passed!`.

## Final Task 2 Fix

- Restored PLATFORM portal support for `GET /api/v2/context` through the existing `IsPlatformPortal` convention.
- Platform sessions now return `PLATFORM_ADMIN`, the current term, and an empty course list. Teacher and student memberships are intentionally excluded to preserve portal isolation and prevent cross-portal leakage.
- Added a platform context regression test covering the authenticated platform session and empty membership list.

## Final Verification

- Focused course tests: `18 passed in 23.11s`.
- Ruff: `All checks passed!`.
