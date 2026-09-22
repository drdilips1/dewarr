from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.domain.permissions import (
    ADMIN,
    ALL,
    APPROVER,
    AUTO_APPROVE,
    AUTO_APPROVE_EBOOK,
    MANAGE_USERS,
    REQUEST,
    REQUEST_AUDIO,
    REQUEST_EBOOK,
    REQUESTER,
    access_label,
    assert_can_request,
    auto_approves,
    bits_from_names,
    coerce_recovery_permissions,
    download_authorization,
    effective_permissions,
    names_from_bits,
    prepare_manual_approval,
    preset_bits,
    unauthorized_grant,
)


def account(role="member", permissions=None, can_automate=False, active=True):
    return SimpleNamespace(
        id=uuid4(),
        role=role,
        active=active,
        permissions=permissions,
        can_automate=can_automate,
        permission_role_id=None,
    )


def spec(mode="audio", **kwargs):
    return SimpleNamespace(
        mode=mode,
        ebook_version_id=kwargs.get("ebook_version_id"),
        audio_version_id=kwargs.get("audio_version_id"),
        required_narrators=kwargs.get("required_narrators") or [],
        download_constraints=kwargs.get("download_constraints"),
        abridged=kwargs.get("abridged"),
        standalone=kwargs.get("standalone", False),
    )


def reason(status="approved", decided_by=None):
    return SimpleNamespace(
        approval_status=status,
        decided_by=decided_by,
        decided_at=None,
        decision_note=None,
    )


def test_legacy_roles_keep_their_current_download_behavior():
    assert effective_permissions(account("admin")) == ALL
    assert effective_permissions(account("viewer", permissions=ALL)) == 0
    assert effective_permissions(account(can_automate=True)) == preset_bits("member", automate=True)
    assert auto_approves(account())
    assert not auto_approves(account("viewer"))
    assert access_label(account()) == "Member"
    assert access_label(account(permissions=REQUESTER)) == "Requester"
    assert access_label(account(permissions=APPROVER)) == "Approver"


def test_media_specific_auto_download_does_not_cover_the_other_medium():
    user = account(permissions=REQUESTER | AUTO_APPROVE_EBOOK)
    assert auto_approves(user, spec("ebook"))
    assert not auto_approves(user, spec("audio"))
    assert not auto_approves(user, spec("both"))


def test_requester_waits_and_keeps_an_approvers_decision():
    user = account(permissions=REQUESTER)
    pending = reason()
    prepare_manual_approval(user, spec(), pending, set(), spec(), None)
    assert pending.approval_status == "pending"
    assert pending.decided_by is None

    approved = reason("approved", decided_by=uuid4())
    prepare_manual_approval(user, spec(), approved, set(), spec(), None)
    assert approved.approval_status == "approved"

    with pytest.raises(HTTPException) as denied:
        prepare_manual_approval(
            user,
            spec("ebook"),
            reason(),
            {"ebook_version_id"},
            spec(ebook_version_id=uuid4()),
            None,
        )
    assert denied.value.status_code == 403


def test_request_checkboxes_match_what_the_server_allows():
    ebook_only = account(permissions=REQUEST_EBOOK)
    assert_can_request(ebook_only, spec("ebook"), set(), spec("ebook"), None)
    with pytest.raises(HTTPException) as audio:
        assert_can_request(ebook_only, spec("audio"), set(), spec("audio"), None)
    assert audio.value.status_code == 403

    general = account(permissions=REQUEST)
    assert_can_request(general, spec("both"), set(), spec("both"), None)

    narrowed = account(permissions=REQUEST | REQUEST_AUDIO)
    assert_can_request(narrowed, spec("audio"), set(), spec("audio"), None)
    with pytest.raises(HTTPException) as ebook:
        assert_can_request(narrowed, spec("ebook"), set(), spec("ebook"), None)
    assert ebook.value.status_code == 403

    immediate = account(permissions=REQUEST_EBOOK | AUTO_APPROVE_EBOOK)
    approved = reason()
    prepare_manual_approval(immediate, spec("ebook"), approved, set(), spec("ebook"), None)
    assert approved.approval_status == "approved"

    for mode in ("both", "either"):
        with pytest.raises(HTTPException) as both:
            assert_can_request(ebook_only, spec(mode), set(), spec(mode), None)
        assert both.value.status_code == 403
        assert "audiobooks" in both.value.detail
    with pytest.raises(HTTPException) as widened:
        assert_can_request(narrowed, spec("both"), set(), spec("both"), None)
    assert "ebooks" in widened.value.detail


def test_user_managers_cannot_grant_bits_they_do_not_hold():
    manager = account(permissions=MANAGE_USERS | REQUEST)
    assert unauthorized_grant(manager, REQUEST) is None
    assert "already have" in unauthorized_grant(manager, REQUEST | AUTO_APPROVE)
    kept = unauthorized_grant(manager, REQUEST | AUTO_APPROVE, current=REQUEST | AUTO_APPROVE)
    assert kept is None
    assert "administrator" in unauthorized_grant(manager, ADMIN)
    assert unauthorized_grant(account(role="admin"), ALL) is None


def test_one_medium_auto_download_authorizes_only_that_download():
    from app.domain.automatic_routes import permitted

    user = account(permissions=REQUEST_EBOOK | AUTO_APPROVE_EBOOK)
    with pytest.raises(HTTPException):
        permitted(user)
    token = download_authorization.set(spec("ebook"))
    try:
        permitted(user)
    finally:
        download_authorization.reset(token)
    token = download_authorization.set(spec("audio"))
    try:
        with pytest.raises(HTTPException) as blocked:
            permitted(user)
        assert blocked.value.status_code == 403
    finally:
        download_authorization.reset(token)


def test_unknown_permission_names_are_rejected():
    with pytest.raises(HTTPException) as error:
        bits_from_names(["request", "not-a-permission"])
    assert error.value.status_code == 422
    assert names_from_bits(REQUESTER) == ["request", "request_ebook", "request_audio"]


def test_an_approver_can_dispatch_a_download_without_list_automation():
    from app.domain.automatic_routes import permitted
    from app.domain.permissions import approval_dispatch

    user = account(permissions=APPROVER)
    with pytest.raises(HTTPException) as blocked:
        permitted(user)
    assert blocked.value.status_code == 403
    token = approval_dispatch.set(True)
    try:
        permitted(user)
    finally:
        approval_dispatch.reset(token)


def test_batch_messages_say_when_requests_are_waiting():
    from app.domain.permissions import list_batch_message, series_batch_message

    assert "sent it for approval" in list_batch_message(1, 1)
    assert "downloads have not been started" in list_batch_message(2, 0)
    assert "1 is waiting for approval" in list_batch_message(3, 1)
    assert "waiting for approval" in series_batch_message(2, 2)
    assert "choose releases to continue" in series_batch_message(2, 0)


def test_recovery_preserves_custom_member_grants_and_resets_viewers():
    assert coerce_recovery_permissions("viewer", False, REQUESTER) == 0
    assert coerce_recovery_permissions("admin", False, 0) == ALL
    assert coerce_recovery_permissions("member", False, REQUESTER) == REQUESTER
    assert coerce_recovery_permissions("member", True, 0) & REQUESTER == REQUESTER
