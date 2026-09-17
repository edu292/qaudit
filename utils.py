from datetime import datetime, time, timedelta

import pandas as pd
from holidays import country_holidays


def get_delta_in_business_hours(
    base: datetime,
    days: int = 0,
    hours: int = 0,
    minutes: int = 0,
    work_start: str = "09:00",
    work_end: str = "18:00",
    country: str = "BR",
    subdiv: str = "PR",
) -> datetime:
    t_start = time.fromisoformat(work_start)
    t_end = time.fromisoformat(work_end)
    shift_minutes = (t_end.hour * 60 + t_end.minute) - (
        t_start.hour * 60 + t_start.minute
    )

    cal = country_holidays(country, subdiv=subdiv)
    holiday_dates = list(cal.keys())

    bhour = pd.offsets.CustomBusinessHour(
        start=work_start,
        end=work_end,
        holidays=holiday_dates,
    )

    total_minutes = (days * shift_minutes) + (hours * 60) + minutes
    full_hours, rem_minutes = divmod(total_minutes, 60)

    current = bhour.rollforward(base)

    if full_hours:
        current = current + pd.offsets.CustomBusinessHour(
            n=full_hours,
            start=work_start,
            end=work_end,
            holidays=holiday_dates,
        )

    if rem_minutes:
        current += timedelta(minutes=rem_minutes)
        day_end = datetime.combine(current.date(), t_end)
        if current > day_end:
            overflow = current - day_end
            next_start = (day_end + bhour).replace(
                hour=t_start.hour, minute=t_start.minute
            )
            current = next_start + overflow

    return current
