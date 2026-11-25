def reconstruct_rows(register, coverage):
    """Project the verified columns in the register's frozen row order."""
    return tuple({
        'reference': entry['reference'],
        'provenance': entry['provenance'],
        'values': {column.column: column.values[ordinal] for column in coverage},
    } for ordinal, entry in enumerate(register, start=1))
