import smtplib

import pytest

from tracker.models import PriceDrop
from tracker.notify import (
    MailNotConfigured, build_drop_email, build_failure_email, send_email,
)


def D(**kw):
    base = dict(key="k", kind="drop", name="n", url="u", previous=None,
                current=10000, list_price=None, is_lowest=False)
    base.update(kw)
    return PriceDrop(**base)


MAIL_ENV = ("GMAIL_ADDRESS", "GMAIL_APP_PASSWORD", "ALERT_TO")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in MAIL_ENV + ("SITE_URL",):
        monkeypatch.delenv(name, raising=False)


def test_drop_email():
    subj, body = build_drop_email([D(kind="drop", name="히트텍", previous=19900, current=14900, list_price=19900, is_lowest=True, url="https://x")])
    assert subj == "[세일 알림] 1개 상품 가격 하락"
    assert "히트텍" in body and "19,900원 → 14,900원" in body and "25%" in body and "역대 최저가" in body and "https://x" in body


def test_sale_start_email_line():
    _, body = build_drop_email([D(kind="sale_start", name="셔츠", previous=None, current=24900, list_price=29900, is_lowest=False, url="https://y")])
    assert "세일 시작" in body and "24,900원" in body and "17%" in body


def test_drop_email_without_list_price_omits_rate():
    _, body = build_drop_email([D(kind="drop", name="n", previous=19900, current=14900, list_price=None, is_lowest=False, url="u")])
    assert "%" not in body


def test_drop_email_subject_counts_all_items():
    subj, _ = build_drop_email([
        D(key="a", kind="drop", name="a", previous=2000, current=1000),
        D(key="b", kind="sale_start", name="b", current=3000),
    ])
    assert subj == "[세일 알림] 2개 상품 가격 하락"


def test_site_url_appended_when_set(monkeypatch):
    monkeypatch.setenv("SITE_URL", "https://example.github.io/tracker")
    _, body = build_drop_email([D(previous=2000, current=1000, url="u")])
    assert body.rstrip().splitlines()[-1] == "https://example.github.io/tracker"


def test_site_url_omitted_when_unset():
    _, body = build_drop_email([D(previous=2000, current=1000, url="u")])
    assert "SITE_URL" not in body
    assert body.rstrip().splitlines()[-1] == "u"


def test_failure_email():
    subj, _ = build_failure_email(["musinsa"])
    assert subj == "[세일 트래커] musinsa 수집 3회 연속 실패"


def test_send_email_requires_env(monkeypatch):
    monkeypatch.delenv("GMAIL_ADDRESS", raising=False)
    with pytest.raises(MailNotConfigured): send_email("s", "b")


class FakeSMTP:
    instances = []

    def __init__(self, host, port):
        self.host, self.port = host, port
        self.logged_in = None
        self.sent = []
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def login(self, user, password):
        self.logged_in = (user, password)

    def send_message(self, msg):
        self.sent.append(msg)


def test_send_email_uses_smtp(monkeypatch):  # smtplib.SMTP_SSL를 가짜로 바꿔 login/send_message 호출 확인
    FakeSMTP.instances.clear()
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)
    monkeypatch.setenv("GMAIL_ADDRESS", "sender@example.com")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "app-pw")
    monkeypatch.setenv("ALERT_TO", "owner@example.com")

    send_email("[세일 알림] 테스트", "본문입니다")

    (smtp,) = FakeSMTP.instances
    assert (smtp.host, smtp.port) == ("smtp.gmail.com", 465)
    assert smtp.logged_in == ("sender@example.com", "app-pw")
    (msg,) = smtp.sent
    assert msg["From"] == "sender@example.com"
    assert msg["To"] == "owner@example.com"
    assert msg["Subject"] == "[세일 알림] 테스트"
    assert "본문입니다" in msg.get_content()
