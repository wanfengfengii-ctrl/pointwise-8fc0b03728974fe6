from lake.reporting.store import load_report


def retrieve(db, report_id):
    return load_report(db, report_id)
