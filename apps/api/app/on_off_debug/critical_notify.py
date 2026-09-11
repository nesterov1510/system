# ruff: noqa: BLE001  -- порт из архива: широкий except и локальное время — намеренно
# on_off_debug/critical_notify.py
import json
import smtplib
import time
import urllib.parse
import urllib.request
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.on_off_debug.env_tools import env_bool, env_int, env_str, read_env_file
from app.on_off_debug.internal_logger import write_internal_error
from app.on_off_debug.time_utils import local_now

DEFAULT_NOTIFY_ENABLED = False
DEFAULT_TELEGRAM_ENABLED = False
DEFAULT_EMAIL_ENABLED = False
DEFAULT_WEBHOOK_ENABLED = False
DEFAULT_TIMEOUT_SECONDS = 8
DEFAULT_COOLDOWN_SECONDS = 0

_LAST_NOTIFY_TS = 0.0


def _split_csv(value: str) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in str(value).split(",") if item.strip()]


def _build_notify_text(
    message: str,
    app_name: str,
    app_ip: str,
    app_env: str,
    app_instance: str,
    source: str | None,
    log_path: str | None,
) -> str:
    """
    Формирует текст уведомления.

    app_name и app_ip используются только здесь, чтобы в уведомлении было
    понятно, какое приложение и какой сервер прислал тревогу.
    """
    now = local_now().strftime("%d.%m.%Y %H:%M:%S")
    source_text = source if source else "unknown"
    log_text = log_path if log_path else "not provided"

    text = (
        "🚨 CRITICAL ERROR\n\n"
        f"App: {app_name}\n"
        f"IP: {app_ip}\n"
        f"Env: {app_env}\n"
        f"Instance: {app_instance}\n"
        f"Source: {source_text}\n"
        f"Time: {now}\n\n"
        "Message:\n"
        f"{message}\n\n"
        "Log:\n"
        f"{log_text}"
    )

    if len(text) > 3800:
        text = text[:3800] + "\n...[truncated]"

    return text


def _send_telegram(token: str, chat_id: str, text: str, timeout_seconds: int) -> bool:
    if not token or not chat_id:
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
    data = urllib.parse.urlencode(payload).encode("utf-8")
    request = urllib.request.Request(
        url=url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        return 200 <= response.status < 300


def _send_webhook(webhook_url: str, payload: dict, timeout_seconds: int) -> bool:
    if not webhook_url:
        return False

    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url=webhook_url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"},
    )

    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        return 200 <= response.status < 300


def _send_email(
    smtp_host: str,
    smtp_port: int,
    use_tls: bool,
    smtp_username: str,
    smtp_password: str,
    email_from: str,
    email_to: str,
    subject: str,
    text: str,
    timeout_seconds: int,
) -> bool:
    recipients = _split_csv(email_to)

    if not smtp_host or not email_from or not recipients:
        return False

    msg = MIMEMultipart()
    msg["From"] = email_from
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    msg.attach(MIMEText(text, "plain", "utf-8"))

    with smtplib.SMTP(smtp_host, smtp_port, timeout=timeout_seconds) as server:
        if use_tls:
            server.starttls()
        if smtp_username and smtp_password:
            server.login(smtp_username, smtp_password)
        server.sendmail(email_from, recipients, msg.as_string())

    return True


def _cooldown_allows_send(cooldown_seconds: int) -> bool:
    """Защита от спама critical-уведомлений."""
    global _LAST_NOTIFY_TS

    if cooldown_seconds <= 0:
        _LAST_NOTIFY_TS = time.time()
        return True

    now_ts = time.time()

    if (now_ts - _LAST_NOTIFY_TS) < cooldown_seconds:
        return False

    _LAST_NOTIFY_TS = now_ts
    return True


def send_critical_notification(
    message: str,
    app_name: str,
    app_ip: str,
    app_env: str,
    app_instance: str,
    source: str | None = None,
    log_path: str | None = None,
) -> None:
    """
    Отправляет уведомление о критической ошибке.

    Эта функция не должна ломать основную программу: если уведомление
    не отправилось, ошибка пишется во внутренний аварийный лог.
    """
    env_data = read_env_file()

    notify_enabled = env_bool(env_data, "DEBUG_CRITICAL_NOTIFY_ENABLED", DEFAULT_NOTIFY_ENABLED)
    if not notify_enabled:
        return

    timeout_seconds = env_int(
        env_data, "DEBUG_CRITICAL_NOTIFY_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS
    )
    cooldown_seconds = env_int(
        env_data,
        "DEBUG_CRITICAL_NOTIFY_COOLDOWN_SECONDS",
        DEFAULT_COOLDOWN_SECONDS,
        min_value=0,
    )

    if not _cooldown_allows_send(cooldown_seconds):
        write_internal_error(
            "critical_notify.cooldown",
            f"Notification skipped by cooldown. app={app_name}, ip={app_ip}, source={source or 'unknown'}",
        )
        return

    telegram_enabled = env_bool(env_data, "DEBUG_CRITICAL_NOTIFY_TELEGRAM", DEFAULT_TELEGRAM_ENABLED)
    email_enabled = env_bool(env_data, "DEBUG_CRITICAL_NOTIFY_EMAIL", DEFAULT_EMAIL_ENABLED)
    webhook_enabled = env_bool(env_data, "DEBUG_CRITICAL_NOTIFY_WEBHOOK", DEFAULT_WEBHOOK_ENABLED)

    # Канал-фильтр: "all" шлёт во все включённые каналы, иначе — только указанный.
    channel = env_str(env_data, "DEBUG_CRITICAL_NOTIFY_CHANNEL", "all").strip().lower()
    if channel in {"none", "off", "0", "false"}:
        return
    if channel in {"telegram", "email", "webhook"}:
        telegram_enabled = telegram_enabled and channel == "telegram"
        email_enabled = email_enabled and channel == "email"
        webhook_enabled = webhook_enabled and channel == "webhook"

    text = _build_notify_text(
        message=str(message),
        app_name=app_name,
        app_ip=app_ip,
        app_env=app_env,
        app_instance=app_instance,
        source=source,
        log_path=log_path,
    )

    payload = {
        "level": "critical",
        "app": app_name,
        "ip": app_ip,
        "env": app_env,
        "instance": app_instance,
        "source": source or "unknown",
        "message": str(message),
        "created_at": local_now().isoformat(),
        "log_path": log_path or "",
    }

    if telegram_enabled:
        try:
            ok = _send_telegram(
                token=env_str(env_data, "DEBUG_TELEGRAM_BOT_TOKEN", ""),
                chat_id=env_str(env_data, "DEBUG_TELEGRAM_CHAT_ID", ""),
                text=text,
                timeout_seconds=timeout_seconds,
            )
            if not ok:
                write_internal_error("critical_notify.telegram", "Telegram notification returned False")
        except Exception as e:
            write_internal_error("critical_notify.telegram", str(e))

    if email_enabled:
        try:
            subject = f"[CRITICAL] {app_name} / {app_ip} / {app_env} / {source or 'unknown'}"
            ok = _send_email(
                smtp_host=env_str(env_data, "DEBUG_SMTP_HOST", ""),
                smtp_port=env_int(env_data, "DEBUG_SMTP_PORT", 587),
                use_tls=env_bool(env_data, "DEBUG_SMTP_USE_TLS", True),
                smtp_username=env_str(env_data, "DEBUG_SMTP_USERNAME", ""),
                smtp_password=env_str(env_data, "DEBUG_SMTP_PASSWORD", ""),
                email_from=env_str(env_data, "DEBUG_EMAIL_FROM", ""),
                email_to=env_str(env_data, "DEBUG_EMAIL_TO", ""),
                subject=subject,
                text=text,
                timeout_seconds=timeout_seconds,
            )
            if not ok:
                write_internal_error("critical_notify.email", "Email notification returned False")
        except Exception as e:
            write_internal_error("critical_notify.email", str(e))

    if webhook_enabled:
        try:
            ok = _send_webhook(
                webhook_url=env_str(env_data, "DEBUG_CRITICAL_WEBHOOK_URL", ""),
                payload=payload,
                timeout_seconds=timeout_seconds,
            )
            if not ok:
                write_internal_error("critical_notify.webhook", "Webhook notification returned False")
        except Exception as e:
            write_internal_error("critical_notify.webhook", str(e))
