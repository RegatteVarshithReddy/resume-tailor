from resume_tailor import emailscan
from resume_tailor.config import Paths
from resume_tailor.emailscan import Suggestion, classify
from resume_tailor.store import Store


def test_classify_recognizes_common_patterns():
    assert classify("Interview invitation", "We'd love to schedule a call next week.") == "interview"
    assert classify("Your application to Acme", "Unfortunately we will not be moving forward.") == "rejected"
    assert classify("Great news!", "We are pleased to offer you the position.") == "offer"
    assert classify("Next step", "Please complete this online assessment within 5 days.") == "screening"


def test_classify_ignores_plain_acknowledgements():
    assert classify("Thanks for applying", "We have received your application.") is None


def test_classify_returns_none_for_unrelated_mail():
    assert classify("Your receipt from Acme", "Your order has shipped.") is None


def test_is_connected_false_without_token(home):
    assert emailscan.is_connected(Paths.resolve(home)) is False


def test_scan_active_applications_filters_status_and_unchanged(home, monkeypatch):
    paths = Paths.resolve(home)
    store = Store(paths.db)
    keep = store.create_application(profile="default", company="Acme", role="Eng",
                                     out_dir=str(home / "outputs" / "a"), status="applied")
    drop_same_status = store.create_application(profile="default", company="Beta", role="Eng",
                                                 out_dir=str(home / "outputs" / "b"), status="applied")
    store.create_application(profile="default", company="Gamma", role="Eng",
                              out_dir=str(home / "outputs" / "c"), status="rejected")  # not active

    def fake_scan(paths, app, **kw):
        if app["id"] == keep:
            return [Suggestion(app_id=app["id"], company=app["company"], role=app["role"],
                               current_status=app["status"], message_id="m1", thread_id="t1",
                               subject="Interview", snippet="let's chat", date="", from_addr="",
                               suggested_status="interview", link="https://mail.google.com/x")]
        if app["id"] == drop_same_status:
            return [Suggestion(app_id=app["id"], company=app["company"], role=app["role"],
                               current_status=app["status"], message_id="m2", thread_id="t2",
                               subject="Ack", snippet="received", date="", from_addr="",
                               suggested_status="applied", link="https://mail.google.com/y")]
        raise AssertionError("should not scan a non-active application")

    monkeypatch.setattr(emailscan, "scan_for_application", fake_scan)
    suggestions, errors = emailscan.scan_active_applications(paths, store)
    assert [s.app_id for s in suggestions] == [keep]
    assert errors == []


def test_scan_active_applications_collects_per_app_errors(home, monkeypatch):
    paths = Paths.resolve(home)
    store = Store(paths.db)
    store.create_application(profile="default", company="Acme", role="Eng",
                             out_dir=str(home / "outputs" / "a"), status="applied")

    def boom(paths, app, **kw):
        raise RuntimeError("network down")

    monkeypatch.setattr(emailscan, "scan_for_application", boom)
    suggestions, errors = emailscan.scan_active_applications(paths, store)
    assert suggestions == []
    assert len(errors) == 1 and "network down" in errors[0]
