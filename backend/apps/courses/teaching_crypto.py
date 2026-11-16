"""Recoverable invitation codes, encrypted with a domain-separated server key."""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


def invitation_cipher() -> Fernet:
    key = hashlib.sha256(
        b"course-invitation-display-v1\0" + str(settings.COURSE_INVITATION_HMAC_KEY).encode()
    ).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def readable_invitation(invitation) -> str:
    if invitation.code_encrypted:
        try:
            return invitation_cipher().decrypt(invitation.code_encrypted.encode()).decode()
        except InvalidToken:
            pass
    return invitation.code_masked
