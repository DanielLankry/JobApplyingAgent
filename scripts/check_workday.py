#!/usr/bin/env python3
"""Prints RUN on Israeli working days, SKIP on weekends or holidays."""

import datetime
import sys

# Key Israeli public holidays (month, day) — update each year
ISRAELI_HOLIDAYS = {
    # 2026
    (3, 26), (3, 27), (3, 28), (3, 29), (3, 30), (3, 31),  # Pesach
    (4, 1),   # 7th day of Pesach
    (4, 22),  # Yom HaAtzmaut
    (5, 15),  # Shavuot
    (9, 20),  # Rosh Hashana 5787
    (9, 21),  # Rosh Hashana 5787 day 2
    (9, 29),  # Yom Kippur
    (10, 4),  # Sukkot
    (10, 11), # Shmini Atzeret / Simchat Torah
    # 2027 (approximate — update as needed)
    (4, 14), (4, 15), (4, 16), (4, 17), (4, 18), (4, 19), (4, 20),  # Pesach
    (5, 5),  # Yom HaAtzmaut
    (6, 1),  # Shavuot
    (9, 9), (9, 10),  # Rosh Hashana
    (9, 18), # Yom Kippur
    (9, 23), # Sukkot
    (9, 30), # Shmini Atzeret
}

# Israel timezone offset (UTC+3 during IDT, UTC+2 during IST)
# Use UTC+3 as a safe default for daytime runs
now_utc = datetime.datetime.utcnow()
now_il = now_utc + datetime.timedelta(hours=3)

weekday = now_il.weekday()  # 0=Mon ... 4=Fri, 5=Sat, 6=Sun
day_of_week = now_il.isoweekday()  # 1=Mon ... 7=Sun

# Israeli working days: Sunday (7) through Thursday (4 in isoweekday = 4)
# isoweekday: Mon=1, Tue=2, Wed=3, Thu=4, Fri=5, Sat=6, Sun=7
is_working_day = day_of_week in (1, 2, 3, 4, 7)  # Mon–Thu and Sun

is_holiday = (now_il.month, now_il.day) in ISRAELI_HOLIDAYS

if not is_working_day or is_holiday:
    reason = "Weekend (Friday/Saturday)" if not is_working_day else "Israeli public holiday"
    print(f"SKIP — {reason} — {now_il.strftime('%A %Y-%m-%d')}", file=sys.stderr)
    print("SKIP")
    sys.exit(0)

print(f"RUN — Working day — {now_il.strftime('%A %Y-%m-%d')}", file=sys.stderr)
print("RUN")
