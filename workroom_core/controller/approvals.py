"""Approval tokens bound to one release digest, one principal, an expiry and a single use."""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass


class ApprovalError(Exception):
    """The approval is not valid for this release."""


@dataclass(frozen=True)
class Approval:
    release_id: str
    digest: str
    principal: str
    channel: str
    expires_at: float
    nonce: str
    signature: str

    def payload(self) -> bytes:
        return json.dumps(
            {"release_id": self.release_id, "digest": self.digest, "principal": self.principal,
             "channel": self.channel, "expires_at": self.expires_at, "nonce": self.nonce},
            sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")


def sign(key: bytes, release_id: str, digest: str, principal: str, channel: str, expires_at: float, nonce: str) -> Approval:
    unsigned = Approval(release_id, digest, principal, channel, expires_at, nonce, "")
    sig = hmac.new(key, unsigned.payload(), hashlib.sha256).hexdigest()
    return Approval(release_id, digest, principal, channel, expires_at, nonce, sig)


def verify(key: bytes, approval: Approval, release_id: str, digest: str, now: float, allowed_principals: frozenset[str]) -> None:
    """Raise ApprovalError unless the approval is authentic, for this release and digest, unexpired and from an allowed principal."""
    expected = hmac.new(key, Approval(approval.release_id, approval.digest, approval.principal, approval.channel,
                                      approval.expires_at, approval.nonce, "").payload(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, approval.signature):
        raise ApprovalError("signature does not match")
    if approval.release_id != release_id:
        raise ApprovalError("approval is for a different release")
    if not hmac.compare_digest(approval.digest, digest):
        raise ApprovalError("approval is for a different set of changes")
    if now > approval.expires_at:
        raise ApprovalError("approval has expired")
    if approval.principal not in allowed_principals:
        raise ApprovalError("principal is not allowed to approve")
