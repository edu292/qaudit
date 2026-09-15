from datetime import datetime, timedelta

import streamlit as st
from sqlalchemy.exc import IntegrityError

from models import (
    Checklist,
    ItemStatus,
    Ncs,
    NCStatus,
    Severity,
    SmtpConfig,
    User,
    init_db,
)

tab_main, tab_severities, tab_users, tab_config = st.tabs(
    ("Checklist", "Categorias", "Usuários", "Configuração")
)
conn = st.connection("db", type="sql", url="sqlite:///audit.db")


init_db(conn)


def save_checklist():
    changes = st.session_state.checklist_editor

    with conn.session as s:
        for added in changes["added_rows"]:
            new_item = Checklist(
                question=added["question"],
                status=added["status"],
            )
            s.add(new_item)
            s.flush()

            if new_item.status == ItemStatus.NON_CONFORMANT:
                s.add(Ncs(item_id=new_item.id))

        for row_idx, edits in changes["edited_rows"].items():
            row_id = int(df_check.iloc[row_idx]["id"])
            item = s.get(Checklist, row_id)

            if item:
                if "question" in edits:
                    item.question = edits["question"]

                if "status" in edits:
                    item.status = edits["status"]

                    if item.status == ItemStatus.NON_CONFORMANT:
                        exists = s.query(Ncs).filter_by(item_id=row_id).first()
                        if not exists:
                            s.add(Ncs(item_id=row_id))

        for row_idx in changes["deleted_rows"]:
            row_id = int(df_check.iloc[row_idx]["id"])
            item = s.get(Checklist, row_id)
            if item:
                s.delete(item)

        s.commit()

    st.rerun()


def save_users():
    changes = st.session_state.user_editor

    try:
        with conn.session as s:
            for added in changes["added_rows"]:
                new_user = User(
                    name=added["name"],
                    email=added["email"],
                    is_manager=added["is_manager"],
                )
                s.add(new_user)

            for row_idx, edits in changes["edited_rows"].items():
                row_id = int(df_users.iloc[row_idx]["id"])
                user = s.get(User, row_id)

                if user:
                    if "name" in edits:
                        user.name = edits["name"]
                    if "email" in edits:
                        user.email = edits["email"]
                    if "is_manager" in edits:
                        user.is_manager = edits["is_manager"]

            for row_idx in changes["deleted_rows"]:
                row_id = int(df_users.iloc[row_idx]["id"])
                user = s.get(User, row_id)
                if user:
                    s.delete(user)

            s.commit()

        st.toast("Usuários salvos com sucesso!", icon="✅")
        st.rerun()

    except IntegrityError:
        st.error(
            "Erro ao salvar: O nome de usuário já existe. Os nomes devem ser únicos."
        )


def save_severities():
    changes = st.session_state.severity_editor
    try:
        with conn.session as s:
            for added in changes["added_rows"]:
                s.add(
                    Severity(
                        name=added["name"],
                        days=added["days"],
                        hours=added["hours"],
                        minutes=added["minutes"],
                    )
                )
            for row_idx, edits in changes["edited_rows"].items():
                row_id = int(df_severities.iloc[row_idx]["id"])
                sev = s.get(Severity, row_id)
                if sev:
                    for k, v in edits.items():
                        setattr(sev, k, v)
            for row_idx in changes["deleted_rows"]:
                row_id = int(df_severities.iloc[row_idx]["id"])
                sev = s.get(Severity, row_id)
                if sev:
                    s.delete(sev)
            s.commit()
        st.toast("Gravidades salvas com sucesso!", icon="✅")
    except IntegrityError:
        st.error("O nome da gravidade deve ser único.")


with tab_main:
    st.title("Checklist e Auditoria")

    df_users = conn.query("SELECT * FROM user", ttl=0)
    df_check = conn.query("SELECT * FROM checklist", ttl=0)

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
        on_change=save_checklist,
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
        ncs = s.query(Ncs).all()
        users = s.query(User).all()
        severities = s.query(Severity).all()

        user_map = {u.name: u.id for u in users}
        sev_map = {sev.name: sev for sev in severities}

        user_names = ["Selecione..."] + list(user_map.keys())
        sev_names = ["Selecione..."] + list(sev_map.keys())

        if not ncs:
            st.info("Nenhuma Não Conformidade registrada.")
        else:
            for nc in ncs:
                checklist_item = s.get(Checklist, nc.item_id)
                is_draft = nc.status == NCStatus.DRAFT.value
                expander_title = f"NC #{nc.id} | Item {nc.item_id}: {checklist_item.question} [{nc.status}]"

                with st.expander(expander_title, expanded=is_draft):
                    with st.form(key=f"form_nc_{nc.id}"):
                        details = st.text_area(
                            "Detalhes da Ocorrência", value=nc.details or "", height=120
                        )

                        col1, col2, col3 = st.columns(3)

                        with col1:
                            curr_user = next(
                                (u.name for u in users if u.id == nc.responsible_id),
                                "Selecione...",
                            )
                            sel_user = st.selectbox(
                                "Responsável",
                                options=user_names,
                                index=user_names.index(curr_user),
                            )

                        with col2:
                            curr_sev = next(
                                (
                                    sv.name
                                    for sv in severities
                                    if sv.id == nc.severity_id
                                ),
                                "Selecione...",
                            )
                            sel_sev = st.selectbox(
                                "Gravidade (Calcula Prazo)",
                                options=sev_names,
                                index=sev_names.index(curr_sev),
                            )

                        with col3:
                            status_options = [e.value for e in NCStatus]
                            sel_status = st.selectbox(
                                "Status",
                                options=status_options,
                                index=status_options.index(nc.status),
                            )

                        if nc.deadline:
                            st.caption(
                                f"**Prazo Calculado:** {nc.deadline.strftime('%d/%m/%Y %H:%M')} (Abertura: {nc.timestamp.strftime('%d/%m/%Y %H:%M')})"
                            )

                        if st.form_submit_button("Salvar NC"):
                            nc_to_update = s.get(Ncs, nc.id)
                            nc_to_update.details = details
                            nc_to_update.responsible_id = (
                                user_map.get(sel_user)
                                if sel_user != "Selecione..."
                                else None
                            )

                            # Deadline Calculation
                            if sel_sev != "Selecione...":
                                chosen_sev = sev_map[sel_sev]
                                nc_to_update.severity_id = chosen_sev.id
                                nc_to_update.deadline = (
                                    nc_to_update.timestamp
                                    + timedelta(
                                        days=chosen_sev.days,
                                        hours=chosen_sev.hours,
                                        minutes=chosen_sev.minutes,
                                    )
                                )
                            else:
                                nc_to_update.severity_id = None
                                nc_to_update.deadline = None

                            if sel_status in (
                                NCStatus.CLOSED.value,
                                NCStatus.CLOSED_EXCEPTION.value,
                            ) and nc_to_update.status not in (
                                NCStatus.CLOSED.value,
                                NCStatus.CLOSED_EXCEPTION.value,
                            ):
                                nc_to_update.closed_time = datetime.now()
                            elif sel_status not in (
                                NCStatus.CLOSED.value,
                                NCStatus.CLOSED_EXCEPTION.value,
                            ):
                                nc_to_update.closed_time = None

                            if (
                                sel_status == NCStatus.ESCALATED.value
                                and nc_to_update.status != NCStatus.ESCALATED.value
                            ):
                                nc_to_update.escalation_time = datetime.now()
                            elif sel_status != NCStatus.ESCALATED.value:
                                nc_to_update.escalation_time = (
                                    None  # Reset if de-escalated
                                )

                            nc_to_update.status = sel_status
                            s.commit()

                            st.toast(f"NC #{nc.id} atualizada com sucesso!", icon="✅")
                            st.rerun()

with tab_users:
    st.title("Gestão de Usuários")

    df_users = conn.query("SELECT * FROM user", ttl=0)
    df_users["is_manager"] = df_users["is_manager"].astype(bool)

    st.data_editor(
        df_users,
        key="user_editor",
        num_rows="dynamic",
        width="stretch",
        on_change=save_users,
        column_order=("name", "email", "is_manager"),
        column_config={
            "name": st.column_config.TextColumn("Nome", required=True),
            "email": st.column_config.TextColumn("E-mail", required=True),
            "is_manager": st.column_config.CheckboxColumn("É Gerente?", default=False),
        },
    )


with tab_severities:
    st.title("Níveis de Gravidade / Prazos")
    df_severities = conn.query("SELECT * FROM severity", ttl=0)

    st.data_editor(
        df_severities,
        key="severity_editor",
        num_rows="dynamic",
        width="stretch",
        on_change=save_severities,
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


with tab_config:
    st.title("Configuração SMTP")
    st.markdown("Defina os dados para envio automático de e-mails.")

    with conn.session as s:
        smtp_conf = s.get(SmtpConfig, 1)

    with st.form("smtp_form"):
        col1, col2 = st.columns([3, 1])
        with col1:
            server_input = st.text_input("Servidor SMTP", value=smtp_conf.server or "")
        with col2:
            port_input = st.number_input("Porta", value=smtp_conf.port or 587, step=1)

        col3, col4 = st.columns(2)
        with col3:
            user_input = st.text_input("Usuário", value=smtp_conf.user or "")
        with col4:
            pass_input = st.text_input(
                "Senha", value=smtp_conf.password or "", type="password"
            )

        if st.form_submit_button("Salvar Configurações SMTP"):
            with conn.session as s:
                conf = s.get(SmtpConfig, 1)
                conf.server = server_input
                conf.port = port_input
                conf.user = user_input
                conf.password = pass_input
                s.commit()

            st.toast("Configurações SMTP salvas!", icon="✅")
            st.rerun()
