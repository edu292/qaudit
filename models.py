import contextlib
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    event,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    class Role(StrEnum):
        STAFF = "STAFF"
        QA = "QA"
        MANAGER = "MANAGER"

        @property
        def label(self) -> str:
            labels = {
                self.STAFF: "Colaborador",
                self.QA: "QA",
                self.MANAGER: "Gerente",
            }
            return labels[self]

    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(unique=True)
    email: Mapped[str] = mapped_column()
    role: Mapped[Role] = mapped_column(default=Role.STAFF)

    ncs: Mapped[list[Nc]] = relationship(back_populates="responsible")


class SmtpConfig(Base):
    __tablename__ = "smtp_config"
    __table_args__ = (CheckConstraint("id = 1", name="single_row_check"),)

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    server: Mapped[str | None] = mapped_column()
    port: Mapped[int | None] = mapped_column()
    user: Mapped[str | None] = mapped_column()
    password: Mapped[str | None] = mapped_column()
    project_name: Mapped[str | None] = mapped_column()


class ChecklistItem(Base):
    class Status(StrEnum):
        PENDING = "PENDING"
        NON_CONFORMANT = "NON_CONFORMANT"
        CONFORMANT = "CONFORMANT"
        NA = "NA"

        @property
        def label(self) -> str:
            labels = {
                self.PENDING: "Pendente",
                self.CONFORMANT: "Conforme",
                self.NON_CONFORMANT: "Não Conforme",
                self.NA: "Não Aplicável",
            }
            return labels[self]

    __tablename__ = "checklist_items"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    question: Mapped[str] = mapped_column()
    status: Mapped[Status] = mapped_column(default=Status.PENDING.value)
    nc: Mapped[Nc | None] = relationship(
        back_populates="checklist_item", cascade="all, delete-orphan", uselist=False
    )


class Nc(Base):
    class Status(StrEnum):
        DRAFT = "DRAFT"
        OPEN = "OPEN"
        CLOSED = "CLOSED"
        ESCALATED = "ESCALATED"
        CLOSED_EXCEPTION = "CLOSED_EXCEPTION"

        @property
        def label(self) -> str:
            labels = {
                self.DRAFT: "Rascunho",
                self.OPEN: "Aberta",
                self.CLOSED: "Encerrada",
                self.ESCALATED: "Escalada",
                self.CLOSED_EXCEPTION: "Fechada por Exceção",
            }
            return labels[self]

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
    escalated_at: Mapped[datetime | None] = mapped_column()
    deadline: Mapped[datetime | None] = mapped_column()

    details: Mapped[str | None] = mapped_column()
    corrective_action: Mapped[str | None] = mapped_column()
    status: Mapped[Status] = mapped_column(default=Status.DRAFT)

    checklist_item: Mapped[ChecklistItem] = relationship(back_populates="nc")
    responsible: Mapped[User | None] = relationship(back_populates="ncs")
    severity: Mapped[Severity | None] = relationship(back_populates="ncs")

    TERMINAL_STATUSES = (Status.CLOSED, Status.CLOSED_EXCEPTION)
    CLOSABLE_STATUSES = (Status.OPEN, Status.ESCALATED)

    @property
    def is_terminal(self):
        return self.status in self.TERMINAL_STATUSES

    @property
    def is_closable(self):
        return self.status in self.CLOSABLE_STATUSES

    @property
    def is_overdue(self):
        if not self.deadline or self.is_terminal:
            return False

        return datetime.now() > self.deadline


class Severity(Base):
    __tablename__ = "severities"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(unique=True, nullable=False)
    days: Mapped[int] = mapped_column(default=0)
    hours: Mapped[int] = mapped_column(default=0)
    minutes: Mapped[int] = mapped_column(default=0)

    ncs: Mapped[list[Nc]] = relationship(back_populates="severity")

    def __str__(self) -> str:
        parts = []
        if self.days:
            parts.append(f"{self.days} dia{'s' if self.days != 1 else ''}")
        if self.hours:
            parts.append(f"{self.hours}h")
        if self.minutes:
            parts.append(f"{self.minutes}min")

        return f"{self.name}  |" + " ".join(parts)


def init_db(conn):
    @event.listens_for(conn.engine, "connect")
    def _enable_sqlite_fk(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(conn.engine)
    with contextlib.suppress(IntegrityError), conn.session as s:
        s.add(SmtpConfig(id=1, port=587))
        s.commit()
