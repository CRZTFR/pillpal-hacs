# Copied from bindicator services/device-api/device_api/posix_tz.py (8ce64bf). The lamp's
# contract fixture recurrence_windows.json keeps the copies in step.
"""POSIX TZ rule strings, parsed and evaluated without a timezone database.

The contract requires the lamp to evaluate its own daylight-saving
transitions offline from a rule string such as ``AEST-10AEDT,M10.1.0,M4.1.0/3``.
`zoneinfo` can *apply* an IANA zone's compiled rules, but it has no public way
to parse an arbitrary ``Mm.w.d`` POSIX rule the lamp was just handed, so this
module implements the parse and the two-transitions-per-year evaluation
directly.

Constraints enforced (from contracts/device-v2/README.md):

- Transition rules must use the ``Mm.w.d`` form; Julian-day (``Jn`` or bare
  ``n``) forms are rejected.
- A daylight abbreviation with no transition rules is rejected, because it
  cannot be evaluated offline.
- At most 63 characters.

Judgement call: only zones with at most one spring-forward and one fall-back
per year, expressed relative to that same year, are supported. A southern-
hemisphere zone whose DST season wraps across 1 January (the real-world
``AEST-10AEDT,...`` example in the contract) parses and validates correctly,
but a local time that falls in a gap is resolved using that calendar year's
own spring rule; this is exact for the fixtures' synthetic zone (whose DST
season does not wrap) and is documented here rather than silently assumed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

MAX_TZ_LENGTH = 63

_NAME = r"(?:<[A-Za-z0-9+\-]+>|[A-Za-z]+)"
_OFFSET = r"[+-]?\d{1,3}(?::\d{2}(?::\d{2})?)?"

_TZ_RE = re.compile(
    rf"^(?P<std_name>{_NAME})(?P<std_offset>{_OFFSET})"
    rf"(?:(?P<dst_name>{_NAME})(?P<dst_offset>{_OFFSET})?"
    rf"(?:,(?P<rules>.+))?)?$"
)

_MWD_RULE_RE = re.compile(
    r"^M(?P<month>\d{1,2})\.(?P<week>\d)\.(?P<day>\d)(?:/(?P<time>[+-]?\d{1,3}(?::\d{2}(?::\d{2})?)?))?$"
)


class PosixTzError(ValueError):
    """A POSIX TZ string violates a contract constraint."""


@dataclass(frozen=True)
class TransitionRule:
    month: int  # 1-12
    week: int  # 1-5 (5 means "last")
    dow: int  # 0=Sunday .. 6=Saturday, POSIX convention
    time_seconds: int  # offset from local midnight on the rule's date


@dataclass(frozen=True)
class PosixTz:
    std_abbr: str
    std_offset_minutes: int  # minutes EAST of UTC: local = utc + offset
    dst_abbr: Optional[str]
    dst_offset_minutes: Optional[int]
    start_rule: Optional[TransitionRule]  # std -> dst, expressed in std time
    end_rule: Optional[TransitionRule]  # dst -> std, expressed in dst time

    @property
    def has_dst(self) -> bool:
        return self.dst_abbr is not None


def _parse_offset_field(text: str, *, negate: bool) -> int:
    """Parse a POSIX `[+-]hh[:mm[:ss]]` field into minutes.

    `negate` applies the POSIX convention that the std/dst offset field is
    signed as "hours west of UTC", i.e. the actual UTC-east offset is its
    negation. Transition-rule times are not negated.
    """
    sign = 1
    body = text
    if body and body[0] in "+-":
        if body[0] == "-":
            sign = -1
        body = body[1:]
    parts = body.split(":")
    hours = int(parts[0]) if parts[0] else 0
    minutes = int(parts[1]) if len(parts) > 1 else 0
    seconds = int(parts[2]) if len(parts) > 2 else 0
    total_minutes = sign * (hours * 60 + minutes + (1 if seconds >= 30 else 0))
    return -total_minutes if negate else total_minutes


def _parse_rule(text: str) -> TransitionRule:
    match = _MWD_RULE_RE.fullmatch(text)
    if not match:
        raise PosixTzError(
            f"transition rule {text!r} is not in Mm.w.d form; "
            "Julian-day transition rules are rejected"
        )
    month = int(match.group("month"))
    week = int(match.group("week"))
    dow = int(match.group("day"))
    if not (1 <= month <= 12 and 1 <= week <= 5 and 0 <= dow <= 6):
        raise PosixTzError(f"transition rule {text!r} has an out-of-range field")
    time_text = match.group("time")
    time_seconds = _parse_offset_field(time_text, negate=False) * 60 if time_text else 2 * 3600
    return TransitionRule(month=month, week=week, dow=dow, time_seconds=time_seconds)


def parse_posix_tz(tz_string: str) -> PosixTz:
    """Parse and validate a POSIX TZ rule string per the device-v2 contract."""
    if len(tz_string) > MAX_TZ_LENGTH:
        raise PosixTzError(
            f"TZ string is {len(tz_string)} characters, over the {MAX_TZ_LENGTH} limit"
        )
    match = _TZ_RE.fullmatch(tz_string)
    if not match:
        raise PosixTzError(f"{tz_string!r} is not a recognisable POSIX TZ string")

    std_abbr = match.group("std_name").strip("<>")
    std_offset_minutes = _parse_offset_field(match.group("std_offset"), negate=True)

    dst_name = match.group("dst_name")
    if dst_name is None:
        return PosixTz(std_abbr, std_offset_minutes, None, None, None, None)

    dst_abbr = dst_name.strip("<>")
    rules_text = match.group("rules")
    if rules_text is None:
        raise PosixTzError(
            f"{tz_string!r} names a daylight abbreviation ({dst_abbr!r}) but has no "
            "transition rules, so it cannot be evaluated offline"
        )

    dst_offset_field = match.group("dst_offset")
    if dst_offset_field:
        dst_offset_minutes = _parse_offset_field(dst_offset_field, negate=True)
    else:
        dst_offset_minutes = std_offset_minutes + 60

    rule_parts = rules_text.split(",")
    if len(rule_parts) != 2:
        raise PosixTzError(f"{tz_string!r} must have exactly two transition rules")
    start_rule = _parse_rule(rule_parts[0])
    end_rule = _parse_rule(rule_parts[1])

    return PosixTz(
        std_abbr, std_offset_minutes, dst_abbr, dst_offset_minutes, start_rule, end_rule
    )


def _nth_weekday(year: int, month: int, week: int, dow: int) -> date:
    """The date of the `week`-th `dow` (0=Sunday) in `month`, `week`=5 meaning last."""
    first = date(year, month, 1)
    first_dow = (first.weekday() + 1) % 7  # Python: Mon=0..Sun=6 -> POSIX: Sun=0..Sat=6
    delta = (dow - first_dow) % 7
    day = 1 + delta + (week - 1) * 7
    days_in_month = (date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)).day
    if day > days_in_month:
        day -= 7
    return date(year, month, day)


def _rule_naive_datetime(rule: TransitionRule, year: int) -> datetime:
    d = _nth_weekday(year, rule.month, rule.week, rule.dow)
    return datetime(d.year, d.month, d.day) + timedelta(seconds=rule.time_seconds)


def spring_transition_utc(tz: PosixTz, year: int) -> datetime:
    """UTC instant clocks jump from standard to daylight time in `year`."""
    naive = _rule_naive_datetime(tz.start_rule, year)
    return naive - timedelta(minutes=tz.std_offset_minutes)


def fall_transition_utc(tz: PosixTz, year: int) -> datetime:
    """UTC instant clocks fall back from daylight to standard time in `year`."""
    naive = _rule_naive_datetime(tz.end_rule, year)
    return naive - timedelta(minutes=tz.dst_offset_minutes)


def dst_transition_date(tz: PosixTz, year: int, which: str) -> date:
    rule = tz.start_rule if which == "start" else tz.end_rule
    return _nth_weekday(year, rule.month, rule.week, rule.dow)


def dst_transition_dates(tz: PosixTz, start: date, end: date) -> list:
    """Calendar dates of every DST transition between `start` and `end`, inclusive."""
    if not tz.has_dst:
        return []
    dates = set()
    for year in range(start.year - 1, end.year + 2):
        dates.add(dst_transition_date(tz, year, "start"))
        dates.add(dst_transition_date(tz, year, "end"))
    return sorted(d for d in dates if start <= d <= end)


def _is_dst_season(tz: PosixTz, utc_dt: datetime) -> bool:
    transitions = []
    for year in (utc_dt.year - 1, utc_dt.year, utc_dt.year + 1):
        transitions.append((spring_transition_utc(tz, year), True))
        transitions.append((fall_transition_utc(tz, year), False))
    transitions.sort(key=lambda pair: pair[0])
    state = False
    for instant, to_dst in transitions:
        if instant <= utc_dt:
            state = to_dst
        else:
            break
    return state


def offset_at_utc(tz: PosixTz, utc_dt: datetime) -> int:
    """The UTC-east offset, in minutes, in effect at a known UTC instant."""
    if not tz.has_dst:
        return tz.std_offset_minutes
    return tz.dst_offset_minutes if _is_dst_season(tz, utc_dt) else tz.std_offset_minutes


def resolve_local(tz: PosixTz, naive_local: datetime):
    """Resolve a local wall-clock reading to `(utc_datetime, offset_minutes, resolution)`.

    `resolution` is one of ``"exact"``, ``"shifted_out_of_gap"`` (spring-forward
    gap, resolved to the first valid instant after it) or ``"first_of_repeated"``
    (fall-back ambiguity, resolved to the earlier of the two instants).
    """
    if not tz.has_dst:
        return naive_local - timedelta(minutes=tz.std_offset_minutes), tz.std_offset_minutes, "exact"

    utc_if_std = naive_local - timedelta(minutes=tz.std_offset_minutes)
    utc_if_dst = naive_local - timedelta(minutes=tz.dst_offset_minutes)
    std_valid = not _is_dst_season(tz, utc_if_std)
    dst_valid = _is_dst_season(tz, utc_if_dst)

    if std_valid and not dst_valid:
        return utc_if_std, tz.std_offset_minutes, "exact"
    if dst_valid and not std_valid:
        return utc_if_dst, tz.dst_offset_minutes, "exact"
    if std_valid and dst_valid:
        # Ambiguous: the local time occurs twice. The earlier instant is the
        # daylight-time one, since the fall-back moves the clock backwards.
        return utc_if_dst, tz.dst_offset_minutes, "first_of_repeated"

    # Neither is valid: the local time falls in the spring-forward gap.
    spring = spring_transition_utc(tz, naive_local.year)
    return spring, tz.dst_offset_minutes, "shifted_out_of_gap"
