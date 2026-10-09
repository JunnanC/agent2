# Task 1 Report

## Status

DONE_WITH_CONCERNS

Task 1 was implemented in the original commit `bd1f708`. Review round 1 fixes
were implemented in `6dab6e4`.

## Files Changed

Original Task 1 commit:

- `.env.example`
- `backend/education_experiment_platform/apps/provisioning/adapters.py`
- `backend/education_experiment_platform/apps/provisioning/ports.py`
- `backend/education_experiment_platform/apps/provisioning/services.py`
- `backend/education_experiment_platform/apps/provisioning/tests/test_adapter_contract.py`
- `backend/education_experiment_platform/apps/provisioning/tests/test_services.py`
- `backend/education_experiment_platform/education_experiment_platform/settings/base.py`

Review fix commit `6dab6e4`:

- `.env.example`
- `backend/education_experiment_platform/apps/provisioning/adapters.py`
- `backend/education_experiment_platform/apps/provisioning/services.py`
- `backend/education_experiment_platform/apps/provisioning/tests/test_adapter_contract.py`
- `backend/education_experiment_platform/apps/provisioning/tests/test_services.py`
- `backend/education_experiment_platform/education_experiment_platform/settings/base.py`

## Behavior

- Added the frozen `RuntimeAdapter.capabilities()` port method.
- Added `runtime_adapter_for(code: str)` with explicit `RUNTIME_MODE` values:
  `fake`, `local`, and `swarm`.
- The resolver uses `RUNTIME_ADAPTER_CODE` and `RUNTIME_ADAPTER_CONFIGS` for
  non-fake modes and rejects unknown modes or missing production configuration.
- Fake, Local Docker, and Docker Swarm adapters expose capability payloads with
  `image_build`, `real_container`, `resource_limits`, and `workspace_access`.
- Fake runtime now accurately reports `workspace_access: false`, matching its
  unsupported capture/restore methods.
- Provisioning execution, compensation, destroy, inventory, resource cleanup,
  capacity/inventory, and health snapshot paths use the configured resolver for
  the selected governance row. Explicitly different legacy rows retain the
  existing driver resolver for compatibility.
- Default `RUNTIME_ADAPTER_CODE` now matches the default fake mode, and the
  example environment file uses `runtime/fake`.
- Existing adapter method signatures and real Docker Local behavior remain
  unchanged.

## Tests and Commands

The required test-first red run for the review fixes produced the expected
failures: 3 failed, 28 passed. Failures covered provisioning bypassing the
resolver and Fake advertising unsupported workspace access.

Focused verification:

```text
.venv/Scripts/python.exe -m pytest education_experiment_platform/apps/provisioning/tests/test_adapter_contract.py education_experiment_platform/apps/provisioning/tests/test_services.py -q
...............................                                          [100%]
31 passed in 19.60s
```

Ruff verification:

```text
.venv/Scripts/python.exe -m ruff check education_experiment_platform/apps/provisioning/adapters.py education_experiment_platform/apps/provisioning/services.py education_experiment_platform/apps/provisioning/tests/test_adapter_contract.py education_experiment_platform/apps/provisioning/tests/test_services.py education_experiment_platform/education_experiment_platform/settings/base.py
All checks passed!
```

`git diff --check` also passed before the fix commit.

## Commits

- `bd1f708 refactor: define configurable runtime modes`
- `6dab6e4 fix: apply configured runtime mode to provisioning`
- The report itself is recorded separately after verification.

## Concerns

- The worktree contains pre-existing unrelated changes that were not touched:
  `backend/education_experiment_platform/education_experiment_platform/settings/prod.py`,
  `.commandcode/`, `_review_extract.txt`, `_xlsx_utf8.txt`, `docs/superpowers/plans/`,
  `documents/`, and `outputs/`.
- The broader repository test suite was not run; verification was limited to
  the requested focused provisioning tests, Ruff, and whitespace validation.

## Review Round 2

Round-2 findings were fixed in the follow-up change after `0d2ab9e`.

### Fixes

- Governance runtime health probing and capacity reconciliation now use the
  shared row-aware provisioning resolver. Explicitly different legacy rows
  still use their stored driver/configuration.
- `runtime_inventory()` now accepts an explicit `code`, and
  `enabled_runtime_inventory()` passes `adapter_config.code` separately from
  `config_ref`. Configured rows therefore resolve correctly when their code
  differs from the config reference or when the config reference is empty.
- Added regression coverage for governance health resolution and both inventory
  configuration edge cases.

### Round-2 Verification

```text
.venv/Scripts/python.exe -m pytest education_experiment_platform/apps/provisioning/tests/test_adapter_contract.py education_experiment_platform/apps/provisioning/tests/test_services.py education_experiment_platform/apps/governance/tests/test_services.py -q
.......................................                                  [100%]
39 passed in 21.10s
```

```text
.venv/Scripts/python.exe -m ruff check education_experiment_platform/apps/provisioning/adapters.py education_experiment_platform/apps/provisioning/services.py education_experiment_platform/apps/provisioning/tests/test_adapter_contract.py education_experiment_platform/apps/provisioning/tests/test_services.py education_experiment_platform/apps/governance/tasks.py education_experiment_platform/apps/governance/tests/test_services.py
All checks passed!
```

`git diff --check` passed. The round-2 fix commit is recorded after this
report update.
