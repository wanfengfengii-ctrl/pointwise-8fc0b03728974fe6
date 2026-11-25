from dataclasses import dataclass

from lake.edition.column_codec import select_columns
from lake.quality.decisions import DECISION_ORDER


_PAGE_SIZE = {'reading': 1, 'quality': 2, 'temperature': 2}


@dataclass(frozen=True)
class ColumnPlan:
    column: str
    pages: tuple[tuple[tuple[int, int | str], ...], ...]
    null_rows: tuple[int, ...]


def plan_columns(revision, columns):
    plans = []
    for column in select_columns(columns):
        members = []
        null_rows = []
        for ordinal, row in enumerate(revision.rows, start=1):
            value = row.quality if column == 'quality' else getattr(row.observation, column)
            if value is None:
                null_rows.append(ordinal)
            else:
                members.append((ordinal, value))
        if column == 'quality':
            members.sort(key=lambda member: (DECISION_ORDER.index(member[1]), member[0]))
        else:
            members.sort(key=lambda member: (member[1], member[0]))
        size = _PAGE_SIZE[column]
        pages = tuple(tuple(members[start:start + size])
                      for start in range(0, len(members), size))
        plans.append(ColumnPlan(column, pages, tuple(null_rows)))
    return tuple(plans)
