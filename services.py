from datetime import timedelta

from sqlalchemy import delete, exists, insert, select, update

from emails import generate_escalation_email, generate_nc_email, send_email
from models import ChecklistItem, ItemStatus, Nc, NCStatus, Severity, SmtpConfig, User


class DomainError(Exception):
    """Raised when a business constraint is violated."""


def apply_editor_changes(session, model, changes: dict, df_source):
    if added := changes.get("added_rows"):
        session.execute(insert(model), added)

    if edited := changes.get("edited_rows"):
        updates = [
            {"id": int(df_source.iloc[idx]["id"]), **vals}
            for idx, vals in edited.items()
        ]
        session.execute(update(model), updates)

    if deleted := changes.get("deleted_rows"):
        ids = df_source.iloc[deleted]["id"].astype(int).tolist()
        session.execute(delete(model).where(model.id.in_(ids)))


def sync_checklist_ncs(session):
    has_nc = exists().where(Nc.checklist_item_id == ChecklistItem.id)

    select_missing = (
        select(ChecklistItem.id.label("checklist_item_id"))
        .where(ChecklistItem.status == ItemStatus.NON_CONFORMANT)
        .where(~has_nc)
    )

    session.execute(insert(Nc).from_select(["checklist_item_id"], select_missing))


def open_nc(session, nc, details, user_id, sev_id, now):
    if not user_id or not sev_id:
        raise DomainError("Responsável e Gravidade são obrigatórios para abertura.")

    sev = session.get(Severity, sev_id)
    user = session.get(User, user_id)

    nc.details = details
    nc.responsible_id = user_id
    nc.severity_id = sev_id
    nc.opened_at = now
    nc.deadline = now + timedelta(days=sev.days, hours=sev.hours, minutes=sev.minutes)
    nc.status = NCStatus.OPEN.value
    session.commit()

    subject, body = generate_nc_email(
        nc.id,
        nc.checklist_item.question,
        nc.status,
        nc.details,
        nc.deadline,
        user.name,
        sev.name,
    )

    config = session.get(SmtpConfig, 1)
    send_email(config, subject, body, user.email)


def save_draft(session, nc, details, user_id, sev_id):
    nc.details = details
    nc.responsible_id = user_id
    nc.severity_id = sev_id
    session.commit()


def close_nc(session, nc, now, as_exception=False):
    if as_exception:
        nc.status = NCStatus.CLOSED_EXCEPTION.value
    else:
        nc.status = NCStatus.CLOSED.value

    nc.closed_at = now
    session.commit()


def escalate_nc(session, nc, now):
    nc.status = NCStatus.ESCALATED.value
    nc.escalated_at = now
    session.commit()

    config = session.get(SmtpConfig, 1)
    manager = session.scalars(select(User).where(User.is_manager.is_(True))).first()

    subject, body = generate_escalation_email(
        nc.id,
        nc.checklist_item.question,
        nc.severity.name,
        nc.details,
        nc.deadline,
        nc.responsible.name,
        manager.name,
    )

    send_email(config, subject, body, manager.email)
