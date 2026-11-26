from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage

from tracker.models import PriceDrop


class MailNotConfigured(Exception):
    pass


def _rate_suffix(drop: PriceDrop) -> str:
    if drop.list_price is None or drop.list_price <= drop.current:
        return ""
    rate = round((drop.list_price - drop.current) / drop.list_price * 100)
    return f" ({rate}% 할인)"


def _drop_block(drop: PriceDrop) -> str:
    if drop.kind == "sale_start":
        head = f"[세일 시작] {drop.name}: {drop.current:,}원{_rate_suffix(drop)}"
    else:
        head = f"{drop.name}: {drop.previous:,}원 → {drop.current:,}원{_rate_suffix(drop)}"
        if drop.is_lowest:
            head += " · 역대 최저가"
    return f"{head}\n{drop.url}"


def _with_site_url(body: str) -> str:
    site = os.environ.get("SITE_URL", "").strip()
    return f"{body}\n\n{site}" if site else body


def build_drop_email(drops: list[PriceDrop]) -> tuple[str, str]:
    subject = f"[세일 알림] {len(drops)}개 상품 가격 하락"
    body = "\n\n".join(_drop_block(d) for d in drops)
    return subject, _with_site_url(body)


def build_failure_email(brands: list[str]) -> tuple[str, str]:
    subject = f"[세일 트래커] {', '.join(brands)} 수집 3회 연속 실패"
    body = "다음 브랜드의 수집이 3회 연속 실패했습니다.\n\n" + "\n".join(f"- {b}" for b in brands)
    return subject, _with_site_url(body)


def send_email(subject: str, body: str) -> None:
    sender = os.environ.get("GMAIL_ADDRESS", "")
    password = os.environ.get("GMAIL_APP_PASSWORD", "")
    recipient = os.environ.get("ALERT_TO", "")
    if not (sender and password and recipient):
        raise MailNotConfigured(
            "GMAIL_ADDRESS, GMAIL_APP_PASSWORD, ALERT_TO 환경변수가 모두 필요합니다"
        )

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient
    msg.set_content(body, charset="utf-8")

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(sender, password)
        smtp.send_message(msg)
