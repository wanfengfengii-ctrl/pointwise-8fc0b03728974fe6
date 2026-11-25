def count_non_null(rows, columns):
    counts = dict.fromkeys(columns, 0)
    for row in rows:
        for column in columns:
            if row['values'][column] is not None:
                counts[column] += 1
    return counts
