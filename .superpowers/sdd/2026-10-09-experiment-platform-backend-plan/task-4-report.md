# Task 4 Report: Normalize Resource Profiles and Reservation Semantics

## Status

Completed and committed as `feat: enforce cpu memory resource reservations`.

## Implemented

- Added CPU request/limit millicore and memory request/limit MB fields to `ResourceProfile`.
- Added migration `governance.0003_resource_request_limits` that copies legacy CPU/memory values into both request and limit fields, then makes the new fields non-null and enforces positive request/limit constraints.
- Added `validate_resource_profile` with legacy normalization, positive-value validation, and request-not-greater-than-limit validation.
- Added `effective_resource_profile` to resolve frozen task snapshots and safely fall back for legacy snapshots.
- Exposed request/limit values in governance serializers and resource-profile responses.
- Added `RuntimeCapacityReservation` and migration `provisioning.0002_reservation_binding`.
- Implemented row-locked, capacity-safe runtime admission using the profile request values. Active bindings are reused only when reservation, runtime, and dimensions match.
- Implemented idempotent runtime release. CPU and memory are restored independently, including adapters that report only one capacity dimension.
- Connected runtime capacity admission to provisioning start and runtime release to existing provisioning cancellation, failure, compensation, and destruction paths.
- Left prewarm and scaling quota reservation behavior on the existing legacy resource fields.
- Confirmed template/publication creation does not decrement runtime capacity.

## Verification

- `python -m pytest education_experiment_platform/apps/governance/tests/test_services.py education_experiment_platform/apps/provisioning/tests/test_services.py -q`: **26 passed**
- `python -m pytest education_experiment_platform/apps/governance/tests education_experiment_platform/apps/provisioning/tests/test_services.py -q`: **34 passed**
- `python -m pytest education_experiment_platform/apps/labtemplates/tests education_experiment_platform/apps/experiments/tests/test_services.py -q`: **31 passed**
- Django `check` under `education_experiment_platform.settings.test`: **passed**
- Django `makemigrations --check --dry-run` under `education_experiment_platform.settings.test`: **No changes detected**
- Full backend Ruff check: **passed**
- `git diff --check`: **passed**

## Concerns and Assumptions

- Runtime capacity values of zero retain the existing meaning of an unreported/unbounded dimension; configured positive dimensions are enforced and restored.
- The automated tests use the repository SQLite test settings. A live MySQL check was not possible because the configured `mysql` host is unavailable in this workspace; production admission relies on MySQL row-lock behavior from `select_for_update`.
- Unrelated dirty files, including `settings/prod.py`, generated artifacts, and unrelated documentation/output directories, were not staged or changed.

## Review Round 1 Fixes

- Legacy task snapshots now derive all request/limit dimensions from snapshot CPU/memory values when the newer keys are absent; current profile edits no longer alter those frozen tasks.
- Runtime capacity release logs failures and still attempts quota release independently. Provisioning failure state remains the original failure, while quota release is committed when runtime binding release fails.
- Lab-template precheck execution and active rule resource validation now use profile CPU/memory limits with legacy fallback. The governance snapshot also carries normalized request/limit values.
- Added request/limit fields to the governance response serializer, checked-in OpenAPI contract, and generated TypeScript API schema.

## Review Round 1 Verification

- Governance, provisioning, lab-template, and experiment tests: **73 passed**
- Ruff: **passed**
- Django `check`: **passed**
- Django `makemigrations --check --dry-run`: **No changes detected**
- `git diff --check`: **passed**
- OpenAPI contract generation: **completed** with the new fields. Validation still reports the pre-existing `ContextView` serializer issue and existing enum naming warnings; no new Task 4 schema issue was reported.

## Review Round 2 Fixes

- Legacy resource snapshots now explicitly retain snapshot disk and network values while still falling back to the linked profile for genuinely empty snapshots.
- Provisioning runtime specs and quota reservation values now consume the normalized effective snapshot directly for profile identity, CPU/memory requests, disk, and network mode; mutable profile fallback cannot overwrite a populated legacy snapshot.
- Extended the legacy snapshot regression to mutate profile disk and network settings after snapshot creation and verify the frozen values remain effective.

## Review Round 2 Verification

- Targeted legacy snapshot and provisioning service tests: **19 passed**
- Governance, provisioning, lab-template, and experiment tests: **99 passed**
- Ruff: **passed**
- Django `check`: **passed**
- Django `makemigrations --check --dry-run`: **No changes detected**
- `git diff --check`: **passed**
