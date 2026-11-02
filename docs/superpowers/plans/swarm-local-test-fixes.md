# 真实运行环境 Local Test Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the local Compose test workflow reliable under MySQL while preserving production traceability and runtime reconciliation visibility.

**Architecture:** Normalize trace IDs at context and persistence boundaries without widening database columns. Replace the MySQL-incompatible conditional current-term uniqueness constraint with the same nullable generated-slot pattern already used for course ownership and live enrollment. Make runtime reconciliation report unavailable legacy adapters and continue processing other adapters.

**Tech Stack:** Django 6.1, MySQL 8.4, Docker Compose, Django TestCase.

**Spec:** Existing local-test findings from the 真实运行环境 backend refactor.

## Global Constraints

- Do not change production runtime mode requirements.
- Do not widen trace ID columns beyond 32 characters.
- Keep reconciliation report-only by default; `--apply` remains the only mutating mode.
- Do not commit or create a branch.

---

### Task 1: Normalize trace IDs

**Files:**
- Modify: `backend/apps/core/identifiers.py`
- Modify: `backend/apps/core/audit.py`
- Modify: `backend/apps/core/outbox.py`
- Modify: `backend/apps/accounts/services.py`
- Modify: `backend/apps/courses/services.py`
- Modify: `backend/apps/governance/services.py`
- Test: `backend/apps/core/tests/test_services.py`

- [ ] Add a deterministic 32-character trace normalization helper and regression tests.
- [ ] Normalize immutable actor contexts on construction.
- [ ] Normalize audit, failure, and outbox persistence inputs.
- [ ] Run core, experiment, lab-template, and provisioning tests.

### Task 2: Make current-term uniqueness portable

**Files:**
- Modify: `backend/apps/courses/models.py`
- Create: `backend/apps/courses/migrations/0006_academicterm_current_slot.py`
- Test: `backend/apps/courses/tests/test_models.py`

- [ ] Add a nullable generated current slot and a normal unique constraint.
- [ ] Replace the conditional unique constraint.
- [ ] Run migration checks and course model tests on SQLite and MySQL.

### Task 3: Make runtime reconciliation resilient

**Files:**
- Modify: `backend/apps/provisioning/management/commands/reconcile_runtime_resources.py`
- Test: `backend/apps/provisioning/tests/test_runtime_matrix.py`

- [ ] Add a regression test for an unavailable legacy adapter alongside a healthy adapter.
- [ ] Record adapter errors in the report and continue processing remaining adapter groups.
- [ ] Run the reconciliation tests and the report-only command against local Compose data.

### Task 4: Verify the local workflow

- [ ] Run Django system checks and migration drift checks.
- [ ] Run the focused and full backend test suites.
- [ ] Run Compose health and HTTP smoke checks.
- [ ] Inspect the final diff and leave pre-existing dirty files untouched.
