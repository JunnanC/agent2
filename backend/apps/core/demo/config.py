"""Scale configuration, deterministic naming, and shared context for the demo dataset.

Every generated row lives inside a dedicated demo namespace so that the dataset is
idempotent and fully purgeable:

- usernames: ``demo-*``; e-mails: ``*.demo@example.edu``
- course codes: ``DEMO-*``; template/rubric names: ``演示*``
- governance codes/keys: ``DEMO-*`` / ``demo-*``
- all services invoked by the builder carry ``trace_id`` values starting with
  ``demo`` (hex strings cannot start with those letters, so the prefix cannot
  collide with existing seeds).
"""

from __future__ import annotations

import hashlib
import random
import secrets
from dataclasses import dataclass
from typing import Final

from apps.accounts.models import User

DEMO_USERNAME_PREFIX: Final[str] = "demo-"
DEMO_EMAIL_SUFFIX: Final[str] = ".demo@example.edu"
DEMO_TRACE_PREFIX: Final[str] = "demo"

DEFAULT_DEMO_PASSWORD: Final[str] = "Demo-Seed-Only-2026!"


@dataclass(frozen=True)
class DemoConfig:
    """Scale preset plus per-run knobs for the demo dataset builder."""

    scale: str
    teachers: int
    students: int
    courses: int
    publications_per_course: tuple[int, int]  # (first, second) publication indices
    chapters_per_course: int
    analytics_days: int
    draft_course: bool
    closed_course: bool

    @property
    def publication_total(self) -> int:
        extra = 1 if self.publications_per_course[1] > 0 else 0
        return 1 + extra


SMALL: Final[DemoConfig] = DemoConfig(
    scale="small",
    teachers=2,
    students=6,
    courses=2,
    publications_per_course=(1, 0),
    chapters_per_course=2,
    analytics_days=3,
    draft_course=False,
    closed_course=False,
)

DEMO: Final[DemoConfig] = DemoConfig(
    scale="demo",
    teachers=6,
    students=60,
    courses=8,
    publications_per_course=(2, 1),  # course 1 gets a second publication
    chapters_per_course=3,
    analytics_days=14,
    draft_course=True,
    closed_course=True,
)

LARGE: Final[DemoConfig] = DemoConfig(
    scale="large",
    teachers=60,
    students=600,
    courses=100,
    publications_per_course=(5, 2),
    chapters_per_course=3,
    analytics_days=30,
    draft_course=True,
    closed_course=True,
)

SCALE_PRESETS: Final[dict[str, DemoConfig]] = {
    "small": SMALL,
    "demo": DEMO,
    "large": LARGE,
}


@dataclass(frozen=True)
class BuildContext:
    """Per-run context passed through all demo builders."""

    config: DemoConfig
    rnd: random.Random
    password: str

    @property
    def trace_id(self) -> str:
        return new_trace_id()


def context_for(config: DemoConfig, *, seed: int, password: str) -> BuildContext:
    return BuildContext(config=config, rnd=random.Random(seed), password=password)


def new_trace_id() -> str:
    """A 32-char trace id starting with the demo marker."""
    return f"{DEMO_TRACE_PREFIX}{secrets.token_hex(14)}"


def named_context(actor: User, portal: str, trace_id: str) -> object:
    """Return an ``ActorContext`` without importing services at module import time.

    ``ActorContext`` lives in ``apps.courses.services``; importing it lazily keeps
    the demo package importable from management commands without cycles.
    """

    from apps.courses.services import ActorContext

    return ActorContext(actor.public_id, portal, trace_id)


def admin_username() -> str:
    return f"{DEMO_USERNAME_PREFIX}admin"


def admin_email() -> str:
    return f"admin{DEMO_EMAIL_SUFFIX}"


def teacher_username(index: int) -> str:
    return f"{DEMO_USERNAME_PREFIX}teacher-{index:02d}"


def teacher_email(index: int) -> str:
    return f"teacher-{index:02d}{DEMO_EMAIL_SUFFIX}"


def teacher_display_name(index: int, surname: str, given_names: str) -> str:
    return f"{surname}{given_names[index % len(given_names)]}老师（演示）"


def student_username(index: int) -> str:
    return f"{DEMO_USERNAME_PREFIX}student-{index:03d}"


def student_email(index: int) -> str:
    return f"student-{index:03d}{DEMO_EMAIL_SUFFIX}"


def student_display_name(index: int, surnames: str, given_names: str) -> str:
    return (
        surnames[index % len(surnames)]
        + given_names[(index * 7) % len(given_names)]
        + given_names[(index * 3 + 1) % len(given_names)]
    )


def course_code(index: int) -> str:
    return f"DEMO-CS-{index:02d}"


def term_code(index: int) -> str:
    return f"DEMO-TERM-{index:02d}"


def stable_digest(*parts: str) -> str:
    payload = "|".join(parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def run_stamp() -> str:
    """Short, unique suffix used inside per-run generated tokens/digests."""
    return secrets.token_hex(6)


PERSONA_BANDS: Final[tuple[tuple[int, str], ...]] = (
    # (bucket size, persona); buckets sum to 100 and are assigned by index % 100.
    (8, "assigned"),
    (4, "provisioning"),
    (5, "ready"),
    (12, "in_progress"),
    (10, "report_draft"),
    (12, "submitted"),
    (5, "rejected_resubmit"),
    (10, "approved"),
    (15, "completed"),
    (2, "failed"),
    (2, "cancelled"),
    (2, "expired"),
    (9, "assigned"),
    (4, "report_draft"),
)


PERSONA_CUTOFFS: Final[tuple[tuple[int, str], ...]] = tuple(
    zip(
        [sum(size for size, _ in PERSONA_BANDS[: i + 1]) for i in range(len(PERSONA_BANDS))],
        [persona for _, persona in PERSONA_BANDS], strict=False,
    )
)


def persona_for(index: int) -> str:
    """Deterministic task persona bucket for one (student) index.

    The full lifecycle is spread evenly across every publication so all three
    portals see realistic lists.
    """

    bucket = index % 100
    for cutoff, persona in PERSONA_CUTOFFS:
        if bucket < cutoff:
            return persona
    return "assigned"

