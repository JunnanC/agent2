# Prototype-aligned frontend reconstruction

Prototype governs visuals and interactions. Backend guides govern real API contracts.
Preserve the dirty backend baseline; edit frontend in place without commits, resets or data changes.

## Work items

1. Public UI: horizontal navigation, profile menu, tokens, panels, dialogs, accessible request states.
2. Student: overview, enrolled courses, discover/applications, task list/detail, notifications/settings.
3. Workbench: chapter/report rail, workspace tools, tests, versions/checkpoints/executions/submit/exit dialogs.
4. Teacher: overview, courses, enrollments, templates, publishing, process, reviews, analytics.
5. Admin: overview, governance, resources, incidents, audit and nested management tools.
6. Verify: prototype smoke, React tests, typecheck, build, lint and rendered comparison.

## Constraints and ledger

- Same-origin cookie/CSRF auth; no gateway-reserved headers or tokens in storage/URLs/logs.
- ETags, idempotency, backend action eligibility, and trace IDs remain authoritative.
- No production mock data, backend edits, runtime downgrade, commits, or branches.
- Ruling: work in place to retain the required uncommitted backend integration baseline.
- Main agent owns UI/student. Teacher/admin are disjoint implementation tasks.
- Inspection done; implementation/verification pending.
