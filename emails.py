import smtplib
import threading
from email.message import EmailMessage


def generate_nc_email(
    nc_id, question, status, details, deadline, user_name, severity_name
):
    subject = f"[Auditoria] NC #{nc_id} {question[:45]}... [{severity_name}]"

    body = f"""Olá {user_name},

Uma Não Conformidade de Qualidade (QA) foi atribuída a você e requer ação corretiva.

RESUMO DA OCORRÊNCIA
--------------------
• ID: #{nc_id}
• Item Avaliado: {question}
• Severidade: {severity_name}
• Prazo Limite: {deadline.strftime("%d/%m/%Y %H:%M")}

DETALHES / EVIDÊNCIAS
---------------------
{details or "Nenhum detalhe adicional fornecido."}


Atenciosamente,
Equipe de QA"""
    return subject, body


def generate_escalation_email(
    nc_id, question, severity_name, details, deadline, user_name, manager_name
):
    subject = f"[URGENTE - ESCALONAMENTO] NC #{nc_id} Vencida: {question[:40]}..."

    body = f"""Olá {manager_name},

A Não Conformidade #{nc_id} ultrapassou o prazo de resolução sem conclusão e foi escalada.

DADOS DA NC
-----------
• ID: #{nc_id}
• Item: {question}
• Severidade: {severity_name}
• Responsável Atual: {user_name}
• Prazo Vencido em: {deadline.strftime("%d/%m/%Y %H:%M")}

DETALHES DA NÃO CONFORMIDADE
----------------------------
{details or "Sem detalhes informados."}

AÇÃO REQUERIDA DO GESTOR
------------------------
Por favor, alinhe com {user_name} a priorização deste item ou realize o fechamento por exceção diretamente no painel do sistema de auditoria caso o risco tenha sido aceito.

Atenciosamente,
Sistema de Monitoramento QA
"""
    return subject, body


def _send_email(config, subject, body, to_email):
    try:
        msg = EmailMessage()
        msg.set_content(body)
        msg["Subject"] = subject
        msg["From"] = config.user
        msg["To"] = to_email

        with smtplib.SMTP(config.server, config.port) as server:
            server.starttls()
            server.login(config.user, config.password)
            server.send_message(msg)
    except Exception as e:
        print(f"Failed to send email to {to_email}: {e}")


def send_email(config, subject, body, to_email):
    threading.Thread(
        target=_send_email, args=(config, subject, body, to_email), daemon=True
    ).start()
