# Task 5 Report: Experiment Image Lifecycle

## Outcome

Task 5 adds a teacher-owned experiment-image lifecycle for `BUILD_CONTEXT` and
`EXTERNAL_REFERENCE` sources. Both sources resolve to a validated, immutable
digest and a `READY` experiment image backed by the existing governance
`ImageAsset` record. No student-facing build or pull behavior was introduced.

## Data model

`ExperimentImage` records the template version, source type, requested
registry/repository/tag, optional clean build-context asset, lifecycle state,
scan state, resolved digest, masked build arguments/logs, validation details,
error code, trace id, and creator. Its constraints require build-context
sources to have a context asset and external references to have none.

`ImageBuildJob` records preparation attempts, masked arguments/logs, status,
timings, and masked failure code. Both models use the existing versioned-row
concurrency model and protected relationships.

## Runtime Boundary

The provisioning runtime protocol and fake runtime now expose three focused
image operations: `build_image`, `resolve_image`, and `validate_image`. The
labtemplates service checks capability presence before use, so views never call
Docker or a concrete runtime client. The fake implementation deterministically
produces SHA-256 digests and supports the existing failure injection pattern.

## Lifecycle Behavior

`create_experiment_image` validates source-specific inputs and records masked
build arguments. `prepare_experiment_image` is idempotent for `READY` and
`RETIRED` rows, transitions queued/failed work through preparation, branches to
build or resolve, validates the digest format, probes runtime image validity,
and refuses to promote an existing governance digest unless it is clean and
approved. Failure updates are masked and append a failure record.

Successful preparation creates or reuses the existing approved/clean
`ImageAsset`, persists the digest, marks the experiment image `READY`, and
records audit/outbox events. The Celery task retries failed preparation twice.

## API

Teacher routes were added for image collection/create, detail, prepare, events,
and retire under `/teaching/courses/{course_id}/experiment-images`. Create and
prepare operations use existing idempotency and on-commit task conventions;
responses expose requested tag separately from resolved digest and never expose
unmasked build arguments.

## Verification

- `backend/.venv/Scripts/python.exe -m pytest education_experiment_platform/apps/labtemplates/tests -q`
- Result: `24 passed`
- `git diff --check`: passed
- Migration generated as `0005_experiment_image_build_job.py`.

## Review Round 1 Fixes

- New images now use governance `create_image` and remain `PENDING_APPROVAL`
  until an existing governance record is clean and approved; preparation never
  self-approves a new image.
- Docker Local and Docker Swarm implement build, pull/resolve, and validation
  through their existing API client boundary. Student runtime flows remain
  unchanged.
- Raw build arguments are passed transiently to the runtime only. Persisted
  build arguments, validation details, logs, audit payloads, and failure data
  are sanitized with key and value redaction.
- Preparation uses a row lock and one running `ImageBuildJob`; READY and
  RETIRED states are terminal for preparation and cannot be downgraded.
- API collection and item routes enforce `MANAGE_TEMPLATE` and course scope,
  map missing images to `ResourceNotFound`, use idempotency, and enforce
  `If-Match` for prepare and retire. Retirement emits audit and outbox events.
- External digest resolution now requires an experiment image, probes the
  configured runtime, validates the SHA-256 digest, and requires governance
  approval before returning it.
- Build context validation requires `TEMPLATE_VERSION` ownership and the
  `BUILD_CONTEXT` purpose. Resolved digest changes are rejected by the service
  guard, and the governance relationship is reusable across experiment images.

Review-round verification: labtemplates, provisioning, and governance tests
pass (`87 passed`); Ruff passes; `makemigrations --check --dry-run` reports no
changes. Django checks and migration history checks still warn that the
configured MySQL host `mysql` is unavailable in this environment.

## Concerns

- Real Docker Swarm/Local adapters do not implement the new image operations;
  they will fail preparation with `RUNTIME_IMAGE_LIFECYCLE_UNAVAILABLE` until
  their image service integration is supplied. This is intentional at this
  task boundary and prevents views from bypassing the runtime port.
- Migration generation and Django checks could not connect to the configured
  MySQL host in this environment; pytest uses the repository test setup and
  passed all labtemplates tests.
