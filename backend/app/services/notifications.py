from __future__ import annotations

import json
import smtplib
import urllib.request
from email.message import EmailMessage

from app.core.config import settings
from app.db_models import NotificationEndpointTable
from app.models import AlertRecord, NotificationChannel


def deliver_alert_notification(endpoint: NotificationEndpointTable, alert: AlertRecord) -> str:
    if endpoint.channel == NotificationChannel.WEBHOOK.value:
        payload = json.dumps(
            {
                "alert_id": alert.alert_id,
                "server_id": alert.server_id,
                "severity": alert.severity.value,
                "signal": alert.signal,
                "value": alert.value,
                "message": alert.message,
                "state": alert.state.value,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            endpoint.target,
            data=payload,
            headers={"content-type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            return f"webhook:{response.status}"

    if endpoint.channel == NotificationChannel.EMAIL.value:
        if not settings.smtp_host or not settings.smtp_from_email:
            return "email:skipped-missing-smtp-config"
        message = EmailMessage()
        message["From"] = settings.smtp_from_email
        message["To"] = endpoint.target
        message["Subject"] = f"[Prometheus] {alert.severity.value.upper()} {alert.signal} on {alert.server_id}"
        message.set_content(
            f"Alert {alert.alert_id}\n"
            f"Server: {alert.server_id}\n"
            f"Severity: {alert.severity.value}\n"
            f"Signal: {alert.signal}\n"
            f"Value: {alert.value}\n"
            f"Message: {alert.message}\n"
        )
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=5) as client:
            client.starttls()
            if settings.smtp_username and settings.smtp_password:
                client.login(settings.smtp_username, settings.smtp_password)
            client.send_message(message)
        return "email:sent"

    return "unsupported-channel"
