from sqlalchemy import delete, exists, insert, select, update

from emails import render_nc_escalated_email, render_nc_opened_email, send_email
from models import ChecklistItem, Nc, Severity, SmtpConfig, User
from utils import get_delta_in_business_hours


def _get_manager(session):
    return session.scalars(select(User).where(User.is_manager.is_(True))).first()


def _get_project_name(session):
    config = session.get(SmtpConfig, 1)
    return config.project_name


class DomainError(Exception):
    """Raised when a business constraint is violated."""


def apply_editor_changes(session, model, changes: dict, df_source):
    if added := changes.get("added_rows"):
        session.execute(insert(model), (row for row in added))

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
        .where(ChecklistItem.status == ChecklistItem.Status.NON_CONFORMANT)
        .where(~has_nc)
    )

    session.execute(insert(Nc).from_select(["checklist_item_id"], select_missing))

    stale_drafts = (
        select(Nc.id)
        .join(ChecklistItem, Nc.checklist_item_id == ChecklistItem.id)
        .where(Nc.status == Nc.Status.DRAFT)
        .where(ChecklistItem.status != ChecklistItem.Status.NON_CONFORMANT)
    )
    session.execute(delete(Nc).where(Nc.id.in_(stale_drafts)))


def save_draft(session, nc, details, corrective_action, user_id, sev_id):
    nc.details = details
    nc.corrective_action = corrective_action
    nc.responsible_id = user_id
    nc.severity_id = sev_id
    session.commit()


def open_nc(session, nc, details, corrective_action, user_id, sev_id, now):
    if nc.status != Nc.Status.DRAFT:
        raise DomainError("Apenas rascunhos podem ser abertos.")

    if not user_id or not sev_id:
        raise DomainError("Responsável e Gravidade são obrigatórios para abertura.")

    sev = session.get(Severity, sev_id)
    user = session.get(User, user_id)
    if not sev or not user:
        raise DomainError("Responsável ou Gravidade inválidos.")

    nc.details = details
    nc.corrective_action = corrective_action
    nc.responsible_id = user_id
    nc.severity_id = sev_id
    nc.opened_at = now
    nc.deadline = get_delta_in_business_hours(now, sev.days, sev.hours, sev.minutes)
    nc.status = Nc.Status.OPEN
    session.commit()

    manager = _get_manager(session)
    project_name = _get_project_name(session)

    msg = render_nc_opened_email(nc, user, sev, project_name, manager)
    send_email(session, msg)


def close_nc(session, nc, now, as_exception=False):
    if as_exception:
        nc.status = Nc.Status.CLOSED_EXCEPTION
    else:
        nc.status = Nc.Status.CLOSED

    nc.closed_at = now
    session.commit()


def escalate_nc(session, nc, now):
    if nc.status != Nc.Status.OPEN:
        raise DomainError("Apenas NCs abertas podem ser escaladas.")
    if not nc.is_overdue:
        raise DomainError("Prazo ainda vigente.")

    nc.status = Nc.Status.ESCALATED
    nc.escalated_at = now
    session.commit()

    manager = _get_manager(session)
    project_name = _get_project_name(session)
    msg = render_nc_escalated_email(nc, manager, project_name)
    send_email(session, msg)
