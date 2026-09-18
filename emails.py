import smtplib
import threading
from email.message import EmailMessage

from models import SmtpConfig

_HEADER_BG = "#D9D9D9"
_BORDER = "1px solid #999999"
_FONT = "Calibri, Arial, sans-serif"


def _field_block(label, value, width=None):
    style_width = f"width:{width};" if width else ""
    return f"""<td style="{style_width}border:{_BORDER};padding:0;vertical-align:top;">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse;">
            <tr>
                <td style="background:{_HEADER_BG};padding:6px 10px;font-weight:bold;font-size:13px;">
                    {label}
                </td>
            </tr>
            <tr>
                <td style="padding:8px 10px;font-size:13px;">
                    {value or "&nbsp;"}
                </td>
            </tr>
        </table>
    </td>"""


def _row(*field_blocks):
    return f"""<tr>
        <td style="padding:0;">
            <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse;">
                <tr>{"".join(field_blocks)}</tr>
            </table>
        </td>
    </tr>"""


_SPACER = '<tr><td style="height:8px;line-height:8px;font-size:1px;">&nbsp;</td></tr>'


def _render_nc_html(title, fields):
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Type" content="text/html; charset=utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin:0;padding:0;background:#f2f2f2;">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f2f2f2;padding:20px 0;">
<tr><td align="center">
<table role="presentation" width="700" cellspacing="0" cellpadding="0"
       style="background:#ffffff;border:{_BORDER};font-family:{_FONT};border-collapse:collapse;">
    <tr>
        <td style="padding:16px 16px 8px 16px;text-align:center;border-bottom:{_BORDER};">
            <span style="font-size:18px;font-weight:bold;">{title}</span>
        </td>
    </tr>
    {_row(_field_block("Projeto:", fields["project"]))}
    {_row(_field_block("Responsável pela Resolução:", fields["responsible"]))}
    {_row(
        _field_block("Data da 1ª Solicitação:", fields["first_request_date"], width="50%"),
        _field_block("Prazo de Resolução:", fields["deadline"], width="50%"),
    )}
    {_row(_field_block("Nº de Escalonamento:", fields["escalation_count"]))}
    {_row(_field_block("Responsável por QA:", fields["qa_responsible"]))}
    {_SPACER}
    {_row(
        _field_block("Descrição", fields["description"], width="34%"),
        _field_block("Classificação", fields["classification"], width="33%"),
        _field_block("Ação Corretiva Indicada", fields["corrective_action"], width="33%"),
    )}
    {_SPACER}
    {_row(
        _field_block("Histórico de Escalonamento", fields["escalation_history"], width="34%"),
        _field_block("Superior Responsável", fields["superior"], width="33%"),
        _field_block("Prazo para Resolução", fields["resolution_deadline"], width="33%"),
    )}
    {_SPACER}
    <tr>
        <td style="border:{_BORDER};padding:0;">
            <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse;">
                <tr>
                    <td style="background:{_HEADER_BG};padding:6px 10px;font-weight:bold;font-size:13px;">
                        Observações:
                    </td>
                </tr>
                <tr>
                    <td style="padding:10px;font-size:13px;font-weight:bold;">
                        {fields["observations"] or "&nbsp;"}
                    </td>
                </tr>
            </table>
        </td>
    </tr>
    <tr>
        <td style="padding:10px 16px;text-align:right;font-size:10px;color:#666666;">
            Template de Solicitação de Resolução de Não Conformidade - Versão 2.0
        </td>
    </tr>
</table>
</td></tr>
</table>
</body>
</html>
"""


def _render_nc_text(title, fields):
    return f"""{title}

Projeto: {fields["project"]}
Responsável pela Resolução: {fields["responsible"]}
Data da 1ª Solicitação: {fields["first_request_date"]}
Prazo de Resolução: {fields["deadline"]}
Nº de Escalonamento: {fields["escalation_count"]}
Responsável por QA: {fields["qa_responsible"]}

Descrição: {fields["description"]}
Classificação: {fields["classification"]}
Ação Corretiva Indicada: {fields["corrective_action"]}

Histórico de Escalonamento: {fields["escalation_history"]}
Superior Responsável: {fields["superior"]}
Prazo para Resolução: {fields["resolution_deadline"]}

Observações:
{fields["observations"] or "-"}
"""


def generate_nc_email(
    nc_id,
    question,
    details,
    corrective_action,
    opened_at,
    deadline,
    user_name,
    severity_name,
    project_name,
    qa_responsible_name,
):
    subject = f"[Auditoria] NC #{nc_id} {question[:45]}... [{severity_name}]"

    fields = {
        "project": project_name or "-",
        "responsible": user_name,
        "first_request_date": opened_at.strftime("%d/%m/%Y %H:%M"),
        "deadline": deadline.strftime("%d/%m/%Y %H:%M"),
        "escalation_count": "0",
        "qa_responsible": qa_responsible_name or "-",
        "description": question,
        "classification": severity_name,
        "corrective_action": corrective_action or "Não informada.",
        "escalation_history": "Nenhum",
        "superior": "-",
        "resolution_deadline": "-",
        "observations": details,
    }

    title = f"Solicitação de Resolução de Não Conformidade #{nc_id}"
    return subject, _render_nc_text(title, fields), _render_nc_html(title, fields)


def generate_escalation_email(
    nc_id,
    question,
    severity_name,
    details,
    corrective_action,
    opened_at,
    deadline,
    escalated_at,
    user_name,
    manager_name,
    project_name,
):
    subject = f"[PEDIDO ESCALONAMENTO] NC #{nc_id}: {question[:45]}..."

    fields = {
        "project": project_name or "-",
        "responsible": user_name,
        "first_request_date": opened_at.strftime("%d/%m/%Y %H:%M"),
        "deadline": deadline.strftime("%d/%m/%Y %H:%M"),
        "escalation_count": "1",
        "qa_responsible": manager_name,
        "description": question,
        "classification": severity_name,
        "corrective_action": corrective_action or "Não informada.",
        "escalation_history": (
            f"Escalado em {escalated_at.strftime('%d/%m/%Y %H:%M')} "
            "por prazo vencido"
        ),
        "superior": manager_name,
        "resolution_deadline": deadline.strftime("%d/%m/%Y %H:%M"),
        "observations": details,
    }

    title = f"Solicitação de Resolução de Não Conformidade #{nc_id}"
    return subject, _render_nc_text(title, fields), _render_nc_html(title, fields)


def _send_email(config, subject, text_body, html_body, to_email):
    try:
        msg = EmailMessage()
        msg.set_content(text_body)
        msg.add_alternative(html_body, subtype="html")
        msg["Subject"] = subject
        msg["From"] = config.user
        msg["To"] = to_email

        with smtplib.SMTP(config.server, config.port) as server:
            server.starttls()
            server.login(config.user, config.password)
            server.send_message(msg)
    except Exception as e:
        print(f"Failed to send email to {to_email}: {e}")


def send_email(session, subject, text_body, html_body, to_email):
    config = session.get(SmtpConfig, 1)
    session.expunge(config)
    threading.Thread(
        target=_send_email,
        args=(config, subject, text_body, html_body, to_email),
        daemon=True,
    ).start()
