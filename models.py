from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class ItemStatus(StrEnum):
    PENDING = "Pendente"
    NON_CONFORMANT = "Não Conforme"
    CONFORMANT = "Conforme"
    NA = "Não Avaliado"


class NCStatus(StrEnum):
    DRAFT = "Rascunho"
    OPEN = "Aberta"
    CLOSED = "Fechada"
    ESCALATED = "Escalada"
    CLOSED_EXCEPTION = "Fechada por Exceção"


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(unique=True)
    email: Mapped[str] = mapped_column()
    is_manager: Mapped[bool] = mapped_column(default=False)

    ncs: Mapped[list[Nc]] = relationship(back_populates="responsible")


class SmtpConfig(Base):
    __tablename__ = "smtp_config"
    __table_args__ = (CheckConstraint("id = 1", name="single_row_check"),)

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    server: Mapped[str | None] = mapped_column()
    port: Mapped[int | None] = mapped_column()
    user: Mapped[str | None] = mapped_column()
    password: Mapped[str | None] = mapped_column()


class ChecklistItem(Base):
    __tablename__ = "checklist_items"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    question: Mapped[str] = mapped_column()
    status: Mapped[str] = mapped_column(default=ItemStatus.PENDING.value)

    nc: Mapped[Nc | None] = relationship(
        back_populates="checklist_item", cascade="all, delete-orphan", uselist=False
    )


class Nc(Base):
    __tablename__ = "ncs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    checklist_item_id: Mapped[int] = mapped_column(
        ForeignKey("checklist_items.id", ondelete="CASCADE"),
        unique=True,
    )
    responsible_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    severity_id: Mapped[int | None] = mapped_column(
        ForeignKey("severities.id", ondelete="RESTRICT")
    )

    opened_at: Mapped[datetime | None] = mapped_column()
    closed_at: Mapped[datetime | None] = mapped_column()
    escalatied_at: Mapped[datetime | None] = mapped_column()
    deadline: Mapped[datetime | None] = mapped_column()

    details: Mapped[str | None] = mapped_column()
    status: Mapped[str] = mapped_column(default=NCStatus.DRAFT.value)

    checklist_item: Mapped[ChecklistItem] = relationship(back_populates="nc")
    responsible: Mapped[User | None] = relationship(back_populates="ncs")
    severity: Mapped[Severity | None] = relationship(back_populates="ncs")


class Severity(Base):
    __tablename__ = "severities"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(unique=True, nullable=False)
    days: Mapped[int] = mapped_column(default=0)
    hours: Mapped[int] = mapped_column(default=0)
    minutes: Mapped[int] = mapped_column(default=0)

    ncs: Mapped[list[Nc]] = relationship(back_populates="severity")


def init_db(conn):
    Base.metadata.create_all(conn.engine)
    with conn.session as s:
        if not s.get(SmtpConfig, 1):
            s.add(SmtpConfig(id=1, port=587))
            s.commit()
