from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core.audit import append_audit, hash_client_ip
from apps.core.concurrency import compare_and_swap
from apps.core.errors import ResourceNotFound, RowVersionConflict
from apps.core.identifiers import normalize_trace_id
from apps.core.models import ObjectAsset
from apps.core.outbox import append_outbox_event, enqueue_relay_after_commit

from . import events
from .errors import (
    AccountAlreadyExists,
    AccountStateConflict,
    InvalidCredentials,
    LastPlatformAdminProtected,
    QualificationStateConflict,
    VerificationStateConflict,
)
from .models import (
    IdentityVerification,
    PlatformAdminAssignment,
    PlatformAdminAssignmentEvent,
    TeacherQualification,
    TeacherQualificationEvent,
    User,
)
from .security import (
    identity_number_digest,
    mask_identity_number,
    normalize_email,
    normalize_username,
    validate_new_password,
)
from .selectors import user_by_login


@dataclass(frozen=True)
class ActorContext:
    actor_ref: str
    portal: str
    trace_id: str
    client_ip: str = ""
    user_agent: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "trace_id", normalize_trace_id(self.trace_id))


def _audit(
    context: ActorContext,
    *,
    action: str,
    target_type: str,
    target_ref: str,
    before: Any = None,
    after: Any = None,
) -> None:
    append_audit(
        actor_ref=context.actor_ref,
        actor_portal=context.portal,
        actor_context={},
        action=action,
        target_type=target_type,
        target_ref=target_ref,
        before=before,
        after=after,
        result="SUCCEEDED",
        client_ip_hash=hash_client_ip(context.client_ip, salt=settings.AUDIT_IP_HASH_SALT),
        user_agent_summary=context.user_agent,
        trace_id=context.trace_id,
    )


def _event(
    context: ActorContext,
    *,
    event_type: str,
    aggregate_type: str,
    aggregate_ref: str,
    payload: dict[str, Any],
) -> None:
    append_outbox_event(
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_ref=aggregate_ref,
        payload=payload,
        trace_id=context.trace_id,
    )
    enqueue_relay_after_commit(trace_id=context.trace_id)


def authenticate_credentials(identifier: str, password: str) -> User:
    user = user_by_login(identifier)
    encoded = user.password if user is not None else make_password(None)
    valid = check_password(password, encoded)
    if user is None or not valid or user.account_status != User.AccountStatus.ACTIVE:
        raise InvalidCredentials()
    return user


def verify_session_password(user: User, password: str) -> bool:
    return check_password(password, user.password)


@transaction.atomic
def record_login(user: User, *, expected_version: int) -> User:
    return compare_and_swap(
        User,
        pk=user.pk,
        expected_version=expected_version,
        changes={"last_login_at": timezone.now()},
    )  # type: ignore[return-value]


@transaction.atomic
def create_user(
    *,
    email: str,
    username: str,
    display_name: str,
    password: str,
    context: ActorContext,
) -> User:
    validate_new_password(password)
    return create_user_with_password_hash(
        email=email,
        username=username,
        display_name=display_name,
        password_hash=make_password(password),
        context=context,
    )


@transaction.atomic
def create_user_with_password_hash(
    *,
    email: str,
    username: str,
    display_name: str,
    password_hash: str,
    context: ActorContext,
    registration_role: str = User.RegistrationRole.STUDENT,
) -> User:
    try:
        user = User.objects.create(
            email=normalize_email(email),
            username=normalize_username(username),
            display_name=display_name.strip(),
            password=password_hash,
            registration_role=registration_role,
        )
        IdentityVerification.objects.create(user=user)
    except IntegrityError as exc:
        raise AccountAlreadyExists() from exc
    _audit(
        context,
        action="account.create",
        target_type="account",
        target_ref=user.public_id,
        after={"account_status": user.account_status},
    )
    _event(
        context,
        event_type=events.ACCOUNT_CREATED,
        aggregate_type="account",
        aggregate_ref=user.public_id,
        payload={"user_id": user.public_id, "status": user.account_status},
    )
    return user


@transaction.atomic
def update_own_profile(
    *, user: User, display_name: str, expected_version: int, context: ActorContext
) -> User:
    changed = compare_and_swap(
        User,
        pk=user.pk,
        expected_version=expected_version,
        changes={"display_name": display_name.strip()},
    )
    _audit(
        context,
        action="account.profile.update",
        target_type="account",
        target_ref=user.public_id,
        before={"display_name": user.display_name},
        after={"display_name": changed.display_name},
    )
    return changed  # type: ignore[return-value]


@transaction.atomic
def change_password(
    *,
    user: User,
    current_password: str,
    new_password: str,
    expected_version: int,
    context: ActorContext,
) -> User:
    if not check_password(current_password, user.password):
        raise InvalidCredentials()
    validate_new_password(new_password)
    changed = compare_and_swap(
        User,
        pk=user.pk,
        expected_version=expected_version,
        changes={
            "password": make_password(new_password),
            "security_version": user.security_version + 1,
        },
    )
    _audit(
        context,
        action="account.password.change",
        target_type="account",
        target_ref=user.public_id,
        after={"sessions_revoked": True},
    )
    return changed  # type: ignore[return-value]


@transaction.atomic
def revoke_all_sessions(
    *, user: User, expected_version: int, context: ActorContext, action: str
) -> User:
    changed = compare_and_swap(
        User,
        pk=user.pk,
        expected_version=expected_version,
        changes={"security_version": user.security_version + 1},
    )
    _audit(
        context,
        action=action,
        target_type="account",
        target_ref=user.public_id,
        after={"sessions_revoked": True},
    )
    return changed  # type: ignore[return-value]


@transaction.atomic
def set_account_status(
    *,
    user_public_id: str,
    status: str,
    reason: str,
    expected_version: int,
    context: ActorContext,
) -> User:
    try:
        user = User.objects.select_for_update().get(public_id=user_public_id)
    except User.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    if status not in User.AccountStatus.values or status == user.account_status:
        raise AccountStateConflict(detail={"status": user.account_status})
    changes: dict[str, Any] = {
        "account_status": status,
        "is_active": status == User.AccountStatus.ACTIVE,
    }
    if status == User.AccountStatus.DISABLED:
        changes["security_version"] = user.security_version + 1
    changed = compare_and_swap(
        User,
        pk=user.pk,
        expected_version=expected_version,
        changes=changes,
    )
    _audit(
        context,
        action="account.status.change",
        target_type="account",
        target_ref=user.public_id,
        before={"status": user.account_status},
        after={"status": status, "reason": reason},
    )
    _event(
        context,
        event_type=events.ACCOUNT_STATUS_CHANGED,
        aggregate_type="account",
        aggregate_ref=user.public_id,
        payload={"user_id": user.public_id, "status": status},
    )
    return changed  # type: ignore[return-value]


@transaction.atomic
def update_identity_verification(
    *,
    user: User,
    identity_type: str,
    organization_name: str,
    identity_number: str,
    material_asset_id: str,
    submit: bool,
    expected_version: int,
    context: ActorContext,
) -> IdentityVerification:
    verification = IdentityVerification.objects.select_for_update().get(user=user)
    if verification.status not in {
        IdentityVerification.Status.DRAFT,
        IdentityVerification.Status.REJECTED,
    }:
        raise VerificationStateConflict(detail={"status": verification.status})
    material = None
    if material_asset_id:
        try:
            material = ObjectAsset.objects.get(
                public_id=material_asset_id,
                owner_ref=user.public_id,
                purpose="IDENTITY_VERIFICATION",
                status=ObjectAsset.Status.ACTIVE,
                scan_status=ObjectAsset.ScanStatus.CLEAN,
            )
        except ObjectAsset.DoesNotExist as exc:
            raise ResourceNotFound(detail={"material_asset_id": material_asset_id}) from exc
    next_status = (
        IdentityVerification.Status.SUBMITTED if submit else IdentityVerification.Status.DRAFT
    )
    changed = compare_and_swap(
        IdentityVerification,
        pk=verification.pk,
        expected_version=expected_version,
        changes={
            "identity_type": identity_type,
            "organization_name": organization_name.strip(),
            "identity_number_hmac": identity_number_digest(identity_number),
            "identity_number_masked": mask_identity_number(identity_number),
            "material_asset": material,
            "status": next_status,
            "submitted_at": timezone.now() if submit else None,
            "reviewed_by": None,
            "reviewed_at": None,
            "review_reason": "",
        },
    )
    _audit(
        context,
        action="identity.verification.submit" if submit else "identity.verification.update",
        target_type="identity_verification",
        target_ref=verification.public_id,
        before={"status": verification.status},
        after={
            "status": next_status,
            "identity_number": changed.identity_number_masked,
            "material_asset": str(material.public_id) if material else "",
        },
    )
    if submit:
        _event(
            context,
            event_type=events.IDENTITY_VERIFICATION_CHANGED,
            aggregate_type="identity_verification",
            aggregate_ref=verification.public_id,
            payload={"verification_id": verification.public_id, "status": next_status},
        )
    return changed  # type: ignore[return-value]


@transaction.atomic
def review_identity_verification(
    *,
    verification_public_id: str,
    decision: str,
    reason: str,
    expected_version: int,
    actor: User,
    context: ActorContext,
) -> IdentityVerification:
    try:
        verification = IdentityVerification.objects.select_for_update().get(
            public_id=verification_public_id
        )
    except IdentityVerification.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    if verification.status != IdentityVerification.Status.SUBMITTED:
        raise VerificationStateConflict(detail={"status": verification.status})
    next_status = {
        "APPROVE": IdentityVerification.Status.APPROVED,
        "REJECT": IdentityVerification.Status.REJECTED,
    }[decision]
    changed = compare_and_swap(
        IdentityVerification,
        pk=verification.pk,
        expected_version=expected_version,
        changes={
            "status": next_status,
            "reviewed_by": actor,
            "reviewed_at": timezone.now(),
            "review_reason": reason.strip(),
        },
    )
    _audit(
        context,
        action="identity.verification.review",
        target_type="identity_verification",
        target_ref=verification.public_id,
        before={"status": verification.status},
        after={"status": next_status, "reason": reason},
    )
    _event(
        context,
        event_type=events.IDENTITY_VERIFICATION_CHANGED,
        aggregate_type="identity_verification",
        aggregate_ref=verification.public_id,
        payload={"verification_id": verification.public_id, "status": next_status},
    )
    return changed  # type: ignore[return-value]


@transaction.atomic
def grant_teacher_qualification(
    *,
    user_public_id: str,
    reason: str,
    expected_user_version: int,
    actor: User,
    context: ActorContext,
) -> TeacherQualification:
    try:
        user = User.objects.select_for_update().get(public_id=user_public_id)
    except User.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    if user.account_status != User.AccountStatus.ACTIVE:
        raise AccountStateConflict(detail={"status": user.account_status})
    ensure_expected_version(user.row_version, expected_user_version)
    now = timezone.now()
    qualification = TeacherQualification.objects.select_for_update().filter(user=user).first()
    if qualification is None:
        qualification = TeacherQualification.objects.create(
            user=user,
            status=TeacherQualification.Status.ACTIVE,
            granted_by=actor,
            granted_at=now,
            reason=reason.strip(),
        )
        from_status = ""
    else:
        if qualification.status == TeacherQualification.Status.ACTIVE:
            raise QualificationStateConflict(detail={"status": qualification.status})
        from_status = qualification.status
        qualification = compare_and_swap(
            TeacherQualification,
            pk=qualification.pk,
            expected_version=qualification.row_version,
            changes={
                "status": TeacherQualification.Status.ACTIVE,
                "granted_by": actor,
                "granted_at": now,
                "reason": reason.strip(),
                "suspended_by": None,
                "suspended_at": None,
                "revoked_by": None,
                "revoked_at": None,
            },
        )
    TeacherQualificationEvent.objects.create(
        qualification=qualification,
        from_status=from_status,
        to_status=TeacherQualification.Status.ACTIVE,
        actor=actor,
        reason=reason.strip(),
        trace_id=context.trace_id,
    )
    _record_qualification_change(qualification, from_status, context)
    return qualification  # type: ignore[return-value]


@transaction.atomic
def change_teacher_qualification(
    *,
    qualification_public_id: str,
    status: str,
    reason: str,
    expected_version: int,
    actor: User,
    context: ActorContext,
) -> TeacherQualification:
    try:
        qualification = TeacherQualification.objects.select_for_update().get(
            public_id=qualification_public_id
        )
    except TeacherQualification.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    if status not in {
        TeacherQualification.Status.SUSPENDED,
        TeacherQualification.Status.REVOKED,
        TeacherQualification.Status.REJECTED,
    }:
        raise QualificationStateConflict(detail={"target_status": status})
    if (
        qualification.status == status
        or qualification.status == TeacherQualification.Status.REVOKED
        or (
            status == TeacherQualification.Status.REJECTED
            and qualification.status != TeacherQualification.Status.PENDING
        )
        or (
            qualification.status == TeacherQualification.Status.PENDING
            and status != TeacherQualification.Status.REJECTED
        )
        or qualification.status == TeacherQualification.Status.REJECTED
    ):
        raise QualificationStateConflict(detail={"status": qualification.status})
    from apps.courses.errors import OwnerTransferRequired
    from apps.courses.selectors import owned_active_course_refs

    owned_courses = owned_active_course_refs(qualification.user)
    if owned_courses:
        raise OwnerTransferRequired(detail={"course_ids": owned_courses})
    now = timezone.now()
    changes: dict[str, Any] = {"status": status, "reason": reason.strip()}
    if status == TeacherQualification.Status.SUSPENDED:
        changes.update({"suspended_by": actor, "suspended_at": now})
    elif status == TeacherQualification.Status.REVOKED:
        changes.update({"revoked_by": actor, "revoked_at": now})
    previous = qualification.status
    changed = compare_and_swap(
        TeacherQualification,
        pk=qualification.pk,
        expected_version=expected_version,
        changes=changes,
    )
    TeacherQualificationEvent.objects.create(
        qualification=changed,
        from_status=previous,
        to_status=status,
        actor=actor,
        reason=reason.strip(),
        trace_id=context.trace_id,
    )
    _record_qualification_change(changed, previous, context)
    return changed  # type: ignore[return-value]


def _record_qualification_change(
    qualification: TeacherQualification, from_status: str, context: ActorContext
) -> None:
    _audit(
        context,
        action="teacher.qualification.change",
        target_type="teacher_qualification",
        target_ref=qualification.public_id,
        before={"status": from_status},
        after={"status": qualification.status, "reason": qualification.reason},
    )
    _event(
        context,
        event_type=events.TEACHER_QUALIFICATION_CHANGED,
        aggregate_type="teacher_qualification",
        aggregate_ref=qualification.public_id,
        payload={
            "qualification_id": qualification.public_id,
            "user_id": qualification.user.public_id,
            "status": qualification.status,
        },
    )


@transaction.atomic
def grant_platform_admin(
    *,
    user_public_id: str,
    reason: str,
    expected_user_version: int,
    actor: User | None,
    context: ActorContext,
) -> PlatformAdminAssignment:
    try:
        user = User.objects.select_for_update().get(public_id=user_public_id)
    except User.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    if user.account_status != User.AccountStatus.ACTIVE:
        raise AccountStateConflict(detail={"status": user.account_status})
    ensure_expected_version(user.row_version, expected_user_version)
    now = timezone.now()
    assignment = PlatformAdminAssignment.objects.select_for_update().filter(user=user).first()
    if assignment is None:
        assignment = PlatformAdminAssignment.objects.create(
            user=user,
            status=PlatformAdminAssignment.Status.ACTIVE,
            granted_by=actor,
            granted_at=now,
            reason=reason.strip(),
        )
        previous = ""
    else:
        if assignment.status == PlatformAdminAssignment.Status.ACTIVE:
            raise QualificationStateConflict(detail={"status": assignment.status})
        previous = assignment.status
        assignment = compare_and_swap(
            PlatformAdminAssignment,
            pk=assignment.pk,
            expected_version=assignment.row_version,
            changes={
                "status": PlatformAdminAssignment.Status.ACTIVE,
                "granted_by": actor,
                "granted_at": now,
                "revoked_by": None,
                "revoked_at": None,
                "reason": reason.strip(),
            },
        )
    PlatformAdminAssignmentEvent.objects.create(
        assignment=assignment,
        from_status=previous,
        to_status=PlatformAdminAssignment.Status.ACTIVE,
        actor=actor,
        reason=reason.strip(),
        trace_id=context.trace_id,
    )
    _record_admin_change(assignment, previous, context)
    return assignment  # type: ignore[return-value]


@transaction.atomic
def revoke_platform_admin(
    *,
    assignment_public_id: str,
    reason: str,
    expected_version: int,
    actor: User,
    context: ActorContext,
) -> PlatformAdminAssignment:
    active_assignments = list(
        PlatformAdminAssignment.objects.select_for_update()
        .filter(status=PlatformAdminAssignment.Status.ACTIVE)
        .order_by("id")
    )
    assignment = next(
        (item for item in active_assignments if item.public_id == assignment_public_id), None
    )
    if assignment is None:
        if PlatformAdminAssignment.objects.filter(public_id=assignment_public_id).exists():
            raise QualificationStateConflict(detail={"status": "REVOKED"})
        raise ResourceNotFound()
    if len(active_assignments) <= 1:
        raise LastPlatformAdminProtected()
    changed = compare_and_swap(
        PlatformAdminAssignment,
        pk=assignment.pk,
        expected_version=expected_version,
        changes={
            "status": PlatformAdminAssignment.Status.REVOKED,
            "revoked_by": actor,
            "revoked_at": timezone.now(),
            "reason": reason.strip(),
        },
    )
    PlatformAdminAssignmentEvent.objects.create(
        assignment=changed,
        from_status=PlatformAdminAssignment.Status.ACTIVE,
        to_status=PlatformAdminAssignment.Status.REVOKED,
        actor=actor,
        reason=reason.strip(),
        trace_id=context.trace_id,
    )
    _record_admin_change(changed, PlatformAdminAssignment.Status.ACTIVE, context)
    return changed  # type: ignore[return-value]


def _record_admin_change(
    assignment: PlatformAdminAssignment, from_status: str, context: ActorContext
) -> None:
    _audit(
        context,
        action="platform.admin.assignment.change",
        target_type="platform_admin_assignment",
        target_ref=assignment.public_id,
        before={"status": from_status},
        after={"status": assignment.status, "reason": assignment.reason},
    )
    _event(
        context,
        event_type=events.PLATFORM_ADMIN_ASSIGNMENT_CHANGED,
        aggregate_type="platform_admin_assignment",
        aggregate_ref=assignment.public_id,
        payload={
            "assignment_id": assignment.public_id,
            "user_id": assignment.user.public_id,
            "status": assignment.status,
        },
    )


def ensure_expected_version(resource_version: int, expected_version: int) -> None:
    if resource_version != expected_version:
        raise RowVersionConflict(detail={"expected_row_version": expected_version})
