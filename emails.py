import smtplib
import threading
from email.message import EmailMessage

from jinja2 import Environment, FileSystemLoader, select_autoescape

from models import SmtpConfig

_env = Environment(
    loader=FileSystemLoader("templates"),
    autoescape=select_autoescape(("html",)),
)


def _build_email_message(subject, html_body, to_email):
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["To"] = to_email
    msg.set_content(html_body, subtype="html")
    return msg


def render_nc_opened_email(nc, user, sev, project_name, manager):
    template = _env.get_template("nc.html")
    body = template.render(
        nc=nc,
        user=user,
        sev=sev,
        project_name=project_name,
        qa_responsible_name=manager.name,
        escalation_count="0",
        escalation_history="Nenhum",
        superior_name="-",
        resolution_deadline="-",
    )
    return _build_email_message(
        f"[Auditoria] NC #{nc.id} {nc.checklist_item.question[:45]}... [{sev}]",
        body,
        user.email,
    )


def render_nc_escalated_email(nc, manager, project_name):
    template = _env.get_template("nc.html")
    body = template.render(
        nc=nc,
        project_name=project_name,
        qa_responsible_name=manager.name,
        escalation_count="1",
        escalation_history=(
            f"Escalado em {nc.escalated_at.strftime('%d/%m/%Y %H:%M')} por prazo vencido"
        ),
        superior_name=manager.name,
        resolution_deadline=nc.deadline.strftime("%d/%m/%Y %H:%M"),
    )
    return _build_email_message(
        f"[PEDIDO ESCALONAMENTO] NC #{nc.id}: {nc.checklist_item.question[:45]}...",
        body,
        manager.email,
    )


def _send_email(config, msg):
    try:
        msg["From"] = config.user
        with smtplib.SMTP(config.server, config.port) as server:
            server.starttls()
            server.login(config.user, config.password)
            server.send_message(msg)

    except Exception as e:
        print(f"Failed to send email to {msg['To']}: {e}")


def send_email(session, msg):
    config = session.get(SmtpConfig, 1)
    session.expunge(config)
    threading.Thread(
        target=_send_email,
        args=(config, msg),
        daemon=True,
    ).start()
