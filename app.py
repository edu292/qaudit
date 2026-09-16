from datetime import datetime

import streamlit as st
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from models import (
    ChecklistItem,
    ItemStatus,
    Nc,
    NCStatus,
    Severity,
    SmtpConfig,
    User,
    init_db,
)
from services import (
    DomainError,
    apply_editor_changes,
    close_nc,
    escalate_nc,
    open_nc,
    save_draft,
    sync_checklist_ncs,
)

conn = st.connection("db", type="sql", url="sqlite:///db.sqlite3")


init_db(conn)


def handle_editor_save(model, editor_key, df, success_msg, error_msg, post_sync=None):
    changes = st.session_state[editor_key]

    try:
        with conn.session as s:
            apply_editor_changes(s, model, changes, df)
            if post_sync:
                post_sync(s)

            s.commit()

        st.toast(success_msg, icon="✅")

    except IntegrityError:
        st.error(error_msg)


@st.fragment(parallel=True)
def render_main_tab():
    st.title("Checklist e Auditoria")

    df_check = conn.query("SELECT * FROM checklist_items", ttl=0)

    valid_items = df_check[df_check["status"] != ItemStatus.PENDING]
    conformant_items = valid_items[valid_items["status"] == ItemStatus.CONFORMANT]
    adherence = (
        (len(conformant_items) / len(valid_items) * 100) if not valid_items.empty else 0
    )
    st.metric("% de Aderência", f"{adherence:.1f}%")

    st.data_editor(
        df_check,
        key="checklist_editor",
        num_rows="dynamic",
        hide_index=True,
        width="stretch",
        on_change=handle_editor_save,
        kwargs={
            "model": ChecklistItem,
            "editor_key": "checklist_editor",
            "df": df_check,
            "success_msg": "Checklist salvo com sucesso!",
            "error_msg": "Erro ao salvar o checklist.",
            "post_sync": sync_checklist_ncs,
        },
        column_config={
            "id": st.column_config.NumberColumn("ID", disabled=True),
            "question": st.column_config.TextColumn("Pergunta", required=True),
            "status": st.column_config.SelectboxColumn(
                "Status",
                options=[e.value for e in ItemStatus],
                default=ItemStatus.PENDING,
                required=True,
            ),
        },
    )

    st.divider()

    st.subheader("Gestão de Não Conformidades (NCs)")

    with conn.session as s:
        ncs = (
            s.query(Nc)
            .options(
                joinedload(Nc.checklist_item),
                joinedload(Nc.responsible),
                joinedload(Nc.severity),
            )
            .all()
        )
        users = s.query(User).all()
        severities = s.query(Severity).all()

        user_opts = {u.id: u.name for u in users}
        sev_opts = {
            sv.id: f"{sv.name} ({sv.days}d {sv.hours}h {sv.minutes}m)"
            for sv in severities
        }

        if not ncs:
            st.info("Nenhuma Não Conformidade registrada.")

        for nc in ncs:
            render_nc_card(nc, user_opts, sev_opts)


@st.fragment(parallel=True)
def render_nc_card(nc: Nc, user_opts: dict, sev_opts: dict):
    now = datetime.now()

    is_draft = nc.status == NCStatus.DRAFT.value
    is_open = nc.status == NCStatus.OPEN.value
    is_escalated = nc.status == NCStatus.ESCALATED.value
    is_terminal = nc.status in (
        NCStatus.CLOSED.value,
        NCStatus.CLOSED_EXCEPTION.value,
    )

    with st.expander(
        f"NC #{nc.id} | Item: {nc.checklist_item.question} [{nc.status}]",
        expanded=is_draft,
    ):
        details = st.text_area(
            "Detalhamento",
            value=nc.details or "",
            height=100,
            disabled=is_terminal,
            key=f"details_{nc.id}",
        )

        col1, col2 = st.columns(2)
        with col1:
            sel_user_id = st.selectbox(
                "Responsável",
                placeholder="Selecione...",
                format_func=lambda uid: user_opts[uid],
                options=list(user_opts.keys()),
                index=None
                if not nc.responsible_id
                else list(user_opts.keys()).index(nc.responsible_id),
                disabled=not is_draft,
                key=f"user_{nc.id}",
            )
        with col2:
            sel_sev_id = st.selectbox(
                "Categoria",
                placeholder="Selecione...",
                options=list(sev_opts.keys()),
                format_func=lambda sid: sev_opts[sid],
                index=None
                if not nc.severity_id
                else list(sev_opts.keys()).index(nc.severity_id),
                disabled=not is_draft,
                key=f"sev_{nc.id}",
            )

        if not is_terminal and nc.deadline:
            is_overdue = now > nc.deadline and is_open
            color = "red" if is_overdue else "gray"
            st.markdown(
                f":{color}[**Prazo:** {nc.deadline.strftime('%d/%m/%Y %H:%M')}]"
            )

        st.markdown("<hr style='margin: 0.5rem 0 1rem 0;'>", unsafe_allow_html=True)
        act_col1, act_col2, _ = st.columns([0.30, 0.15, 0.55], gap="small")

        def run_action(action_fn, *args, **kwargs):
            nonlocal nc
            with conn.session as s:
                s.expire_on_commit = False
                managed_nc = s.get(Nc, nc.id)
                action_fn(s, managed_nc, *args, **kwargs)

            nc = managed_nc

        try:
            match nc.status:
                case NCStatus.DRAFT:
                    if act_col1.button(
                        "Salvar Rascunho", key=f"draft_{nc.id}", width="stretch"
                    ):
                        run_action(save_draft, details, sel_user_id, sel_sev_id)
                        st.toast("Rascunho atualizado.")

                    if act_col2.button(
                        "Abrir NC", type="primary", key=f"open_{nc.id}", width="stretch"
                    ):
                        run_action(open_nc, details, sel_user_id, sel_sev_id, now)
                        st.toast(
                            "NC Aberta! Notificação enviada ao responsável.",
                            icon="🚀",
                        )
                        st.rerun()

                case NCStatus.OPEN:
                    if act_col1.button(
                        "✅ Concluir", key=f"close_{nc.id}", width="stretch"
                    ):
                        run_action(close_nc, now, as_exception=False)
                        st.toast("NC finalizada com sucesso.", icon="✅")
                        st.rerun()

                    can_escalate = now > nc.deadline
                    help_text = (
                        None
                        if can_escalate
                        else "Escalação disponível apenas após o vencimento do prazo."
                    )
                    if act_col2.button(
                        "⚠️ Escalar",
                        key=f"escalate_{nc.id}",
                        width="stretch",
                        disabled=not can_escalate,
                        help=help_text,
                    ):
                        run_action(escalate_nc, now)
                        st.toast("NC escalada ao gestor.", icon="⚠️")
                        st.rerun()

                case NCStatus.ESCALATED:
                    if act_col1.button(
                        "Fechamento p/ Exceção",
                        type="primary",
                        key=f"exception_{nc.id}",
                        width="stretch",
                    ):
                        run_action(close_nc, now, as_exception=True)
                        st.toast("NC encerrada com exceção.", icon="⚠️")
                        st.rerun()

                case NCStatus.CLOSED | NCStatus.CLOSED_EXCEPTION:
                    col1, col2, col3, col4 = st.columns(4)
                    with col1:
                        st.caption("Aberta em")
                        st.text(nc.opened_at.strftime("%d/%m/%Y %H:%M"))
                    with col2:
                        st.caption("Prazo Original")
                        st.text(nc.deadline.strftime("%d/%m/%Y %H:%M"))
                    with col3:
                        st.caption("Finalizada em")
                        st.text(nc.closed_at.strftime("%d/%m/%Y %H:%M"))
                    if nc.status == NCStatus.CLOSED_EXCEPTION:
                        with col4:
                            st.caption("Escalada em")
                            st.text(nc.escalated_at.strftime("%d/%m/%Y %H:%M"))

        except DomainError as err:
            st.error(str(err))


@st.fragment(parallel=True)
def render_severities_tab():
    st.title("Categorias de Não Conformidade")
    df_severities = conn.query("SELECT * FROM severities", ttl=0)

    st.data_editor(
        df_severities,
        key="severity_editor",
        num_rows="dynamic",
        width="stretch",
        on_change=handle_editor_save,
        kwargs={
            "model": Severity,
            "editor_key": "severity_editor",
            "df": df_severities,
            "success_msg": "Categorias salvas com sucesso!",
            "error_msg": "O nome da categoria deve ser único.",
        },
        column_order=("name", "days", "hours", "minutes"),
        column_config={
            "name": st.column_config.TextColumn("Nome", required=True),
            "days": st.column_config.NumberColumn("Dias", min_value=0, default=0),
            "hours": st.column_config.NumberColumn(
                "Horas", min_value=0, max_value=23, default=0
            ),
            "minutes": st.column_config.NumberColumn(
                "Minutos", min_value=0, max_value=59, default=0
            ),
        },
    )


@st.fragment(parallel=True)
def render_users_tab():
    st.title("Gestão de Usuários")

    df_users = conn.query("SELECT * FROM users", ttl=0)
    df_users["is_manager"] = df_users["is_manager"].astype(bool)

    st.data_editor(
        df_users,
        key="user_editor",
        num_rows="dynamic",
        width="stretch",
        on_change=handle_editor_save,
        kwargs={
            "model": User,
            "editor_key": "user_editor",
            "df": df_users,
            "success_msg": "Usuários salvos com sucesso!",
            "error_msg": "Erro ao salvar: O nome de usuário já existe.",
        },
        column_order=("name", "email", "is_manager"),
        column_config={
            "name": st.column_config.TextColumn("Nome", required=True),
            "email": st.column_config.TextColumn("E-mail", required=True),
            "is_manager": st.column_config.CheckboxColumn("É Gerente?", default=False),
        },
    )


@st.fragment(parallel=True)
def render_config_tab():
    st.title("Configuração SMTP")
    st.markdown("Defina os dados para envio automático de e-mails.")

    with conn.session as s:
        smtp_conf = s.get(SmtpConfig, 1)
        assert smtp_conf is not None

        with st.form("smtp_form"):
            col1, col2 = st.columns([3, 1])
            with col1:
                server_input = st.text_input(
                    "Servidor SMTP", value=smtp_conf.server or ""
                )
            with col2:
                port_input = st.number_input(
                    "Porta", value=smtp_conf.port or 587, step=1
                )

            col3, col4 = st.columns(2)
            with col3:
                user_input = st.text_input("Usuário", value=smtp_conf.user or "")
            with col4:
                pass_input = st.text_input(
                    "Senha", value=smtp_conf.password or "", type="password"
                )

            if st.form_submit_button("Salvar Configurações SMTP"):
                smtp_conf.server = server_input
                smtp_conf.port = port_input
                smtp_conf.user = user_input
                smtp_conf.password = pass_input
                s.commit()

                st.toast("Configurações SMTP salvas!", icon="✅")


tab_main, tab_severities, tab_users, tab_config = st.tabs(
    ("Checklist", "Categorias", "Usuários", "Configuração")
)

with tab_main:
    render_main_tab()

with tab_users:
    render_users_tab()

with tab_severities:
    render_severities_tab()

with tab_config:
    render_config_tab()
