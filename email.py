import smtplib
import threading
from email.message import EmailMessage

from models import SmtpConfig


def generate_nc_email(nc_id, question, status, details, deadline, user_name):
    subject = f"[Auditoria] Atualização - NC #{nc_id}"
    dl_str = deadline.strftime("%d/%m/%Y %H:%M")

    body = f"""Olá {user_name},

Uma Não Conformidade sob sua responsabilidade foi atualizada no sistema.

Item: {question}
Status: {status}
Detalhes: {details or "Nenhum detalhe adicional."}
Prazo: {dl_str}

Atenciosamente,
Sistema de Auditoria
"""
    return subject, body


def _send_email_worker(conn, subject, body, to_email):
    with conn.session as s:
        config = s.query(SmtpConfig).first()
        if not config or not config.server:
            return

        try:
            msg = EmailMessage()
            msg.set_content(body)
            msg["Subject"] = subject
            msg["From"] = config.user
            msg["To"] = to_email

            with smtplib.SMTP(config.server, config.port) as server:
                server.starttls()
                if config.user and config.password:
                    server.login(config.user, config.password)
                server.send_message(msg)
        except Exception as e:
            # In a production app, log this to a file instead of print
            print(f"Failed to send email to {to_email}: {e}")


def send_async_email(subject, body, to_email):
    """Spawns a daemon thread to send the email without blocking UI."""
    if to_email:
        threading.Thread(
            target=_send_email_worker, args=(subject, body, to_email), daemon=True
        ).start()
