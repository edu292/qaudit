from datetime import datetime, timedelta
from enum import StrEnum

from sqlalchemy import CheckConstraint, ForeignKey
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
    __tablename__ = "user"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(unique=True, nullable=False)
    email: Mapped[str] = mapped_column(nullable=False)
    is_manager: Mapped[bool] = mapped_column(default=False)


class SmtpConfig(Base):
    __tablename__ = "smtp_config"
    __table_args__ = (CheckConstraint("id = 1", name="single_row_check"),)

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
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
    severity_id: Mapped[int] = mapped_column(ForeignKey("severity.id"), nullable=True)

    timestamp: Mapped[datetime] = mapped_column(default=datetime.now)
    closed_time: Mapped[datetime] = mapped_column(nullable=True)
    escalation_time: Mapped[datetime] = mapped_column(nullable=True)
    deadline: Mapped[datetime] = mapped_column(nullable=True)

    details: Mapped[str] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(default=NCStatus.DRAFT.value)

    checklist: Mapped[Checklist] = relationship(back_populates="ncs")
    severity: Mapped[Severity] = relationship(back_populates="ncs")


class Severity(Base):
    __tablename__ = "severity"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(unique=True, nullable=False)
    days: Mapped[int] = mapped_column(default=0)
    hours: Mapped[int] = mapped_column(default=0)
    minutes: Mapped[int] = mapped_column(default=0)

    ncs: Mapped[list[Ncs]] = relationship(back_populates="severity")


def init_db(conn):
    Base.metadata.create_all(conn.engine)
    with conn.session as s:
        if not s.get(SmtpConfig, 1):
            s.add(SmtpConfig(id=1, port=587))
            s.commit()


def process_nc_update(
    conn, nc_id, details, user_id, sev_id, status, severity_obj, old_status
):
    with conn.session as s:
        nc = s.get(Ncs, nc_id)
        nc.details = details
        nc.responsible_id = user_id

        # Deadline Calculation
        if sev_id and severity_obj:
            nc.severity_id = sev_id
            nc.deadline = nc.timestamp + timedelta(
                days=severity_obj.days,
                hours=severity_obj.hours,
                minutes=severity_obj.minutes,
            )
        else:
            nc.severity_id = None
            nc.deadline = None

        closed_statuses = (NCStatus.CLOSED.value, NCStatus.CLOSED_EXCEPTION.value)
        if status in closed_statuses and nc.status not in closed_statuses:
            nc.closed_time = datetime.now()
        elif status not in closed_statuses:
            nc.closed_time = None

        if status == NCStatus.ESCALATED.value and nc.status != NCStatus.ESCALATED.value:
            nc.escalation_time = datetime.now()
        elif status != NCStatus.ESCALATED.value:
            nc.escalation_time = None

        nc.status = status
        s.commit()

        if user_id and status != old_status:
            user = s.get(User, user_id)
            checklist_item = s.get(Checklist, nc.item_id)

            """
            subject, body = generate_nc_email(
                nc_id=nc.id,
                question=checklist_item.question,
                status=nc.status,
                details=nc.details,
                deadline=nc.deadline,
                user_name=user.name,
            )
            send_async_email(subject, body, user.email)
            """
