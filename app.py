from datetime import datetime
from enum import StrEnum

import streamlit as st
from sqlalchemy import ForeignKey
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class ItemStatus(StrEnum):
    PENDING = "Pendente"
    NON_CONFORMANT = "Não Conforme"
    CONFORMANT = "Conforme"


class NCStatus(StrEnum):
    DRAFT = "Rascunho"
    OPEN = "Aberta"
    CLOSED = "Fechada"
    ESCALATED = "Escalada"
    CLOSED_EXCEPTION = "Fechada por Exceção"


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "user"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(unique=True, nullable=False)
    email: Mapped[str] = mapped_column(nullable=False)
    is_manager: Mapped[bool] = mapped_column(default=False)


class SmtpConfig(Base):
    __tablename__ = "smtp_config"
    id: Mapped[int] = mapped_column(primary_key=True)
    server: Mapped[str] = mapped_column(nullable=True)
    port: Mapped[int] = mapped_column(nullable=True)
    user: Mapped[str] = mapped_column(nullable=True)
    password: Mapped[str] = mapped_column(nullable=True)


class Checklist(Base):
    __tablename__ = "checklist"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    question: Mapped[str] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(default=ItemStatus.PENDING.value)

    ncs: Mapped[list[Ncs]] = relationship(
        back_populates="checklist", cascade="all, delete-orphan"
    )


class Ncs(Base):
    __tablename__ = "ncs"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("checklist.id"), nullable=False)
    responsible_id: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=True)
    details: Mapped[str] = mapped_column(nullable=True)
    deadline: Mapped[datetime] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(default=NCStatus.DRAFT.value)

    checklist: Mapped[Checklist] = relationship(back_populates="ncs")


tab_main, tab_users, tab_config = st.tabs(("Checklist", "Usuários", "Configuração"))
conn = st.connection("db", type="sql", url="sqlite:///audit.db")


def init_db():
    Base.metadata.create_all(conn.engine)


init_db()

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

    if st.button("Salvar Alterações"):
        changes = st.session_state.checklist_editor

        with conn.session as s:
            for added in changes["added_rows"]:
                new_item = Checklist(
                    question=added.get("question"),
                    status=added.get("status", ItemStatus.PENDING),
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

        st.toast("Alterações salvas com sucesso!", icon="✅")
        st.rerun()

    st.divider()

    st.subheader("Gestão de Não Conformidades (NCs)")

    with conn.session as s:
        all_ncs = s.query(Ncs).all()
        users = s.query(User).all()
        user_map = {u.name: u.id for u in users}
        user_names = ["Selecione..."] + list(user_map.keys())

        if not all_ncs:
            st.info("Nenhuma Não Conformidade registrada.")
        else:
            for nc in all_ncs:
                checklist_item = s.get(Checklist, nc.item_id)

                is_draft = nc.status == NCStatus.DRAFT.value
                expander_title = f"NC #{nc.id} | Item {nc.item_id}: {checklist_item.question} [{nc.status}]"

                with st.expander(expander_title, expanded=is_draft):
                    with st.form(key=f"form_nc_{nc.id}"):
                        details = st.text_area(
                            "Detalhes da Ocorrência", value=nc.details or "", height=120
                        )

                        col1, col2, col3, col4 = st.columns(4)

                        with col1:
                            current_user_name = next(
                                (u.name for u in users if u.id == nc.responsible_id),
                                "Selecione...",
                            )
                            sel_user = st.selectbox(
                                "Responsável",
                                options=user_names,
                                index=user_names.index(current_user_name),
                            )

                        with col2:
                            dt_val = nc.deadline or datetime.now()
                            d = st.date_input(
                                "Data Limite", value=dt_val.date(), key=f"d_{nc.id}"
                            )

                        with col3:
                            dt_val = nc.deadline or datetime.now()
                            t = st.time_input(
                                "Hora Limite", value=dt_val.time(), key=f"t_{nc.id}"
                            )

                        with col4:
                            status_options = [e.value for e in NCStatus]
                            sel_status = st.selectbox(
                                "Status",
                                options=status_options,
                                index=status_options.index(nc.status),
                            )

                        if st.form_submit_button("Salvar NC"):
                            nc_to_update = s.get(Ncs, nc.id)
                            nc_to_update.details = details
                            nc_to_update.responsible_id = (
                                user_map.get(sel_user)
                                if sel_user != "Selecione..."
                                else None
                            )
                            nc_to_update.deadline = datetime.combine(d, t)
                            nc_to_update.status = sel_status
                            s.commit()

                            st.toast(f"NC #{nc.id} atualizada com sucesso!", icon="✅")
                            st.rerun()


with tab_users:
    st.title("Gestão de Usuários")

    df_users = conn.query("SELECT * FROM user", ttl=0)

    if not df_users.empty and "is_manager" in df_users.columns:
        df_users["is_manager"] = df_users["is_manager"].astype(bool)

    st.data_editor(
        df_users,
        key="user_editor",
        num_rows="dynamic",
        hide_index=True,
        use_container_width=True,
        column_config={
            "name": st.column_config.TextColumn("Nome", required=True),
            "email": st.column_config.TextColumn("E-mail", required=True),
            "is_manager": st.column_config.CheckboxColumn("É Gerente?", default=False),
        },
    )

    if st.button("Salvar Usuários"):
        changes = st.session_state.user_editor

        try:
            with conn.session as s:
                for added in changes["added_rows"]:
                    new_user = User(
                        name=added["name"],
                        email=added["email"],
                        is_manager=added.get("is_manager", False),
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
