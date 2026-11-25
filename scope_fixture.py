import json
from contextlib import closing
from copy import deepcopy
from pathlib import Path

from lake.edition.publish import issue
from lake.intake.batches import ingest
from lake.quality.amendments import amend
from lake.quality.freeze import freeze_day
from lake.receiving.accept import receive
from lake.receiving.verify import verify_material
from lake.reporting.sign import reconcile_columns
from lake.storage import open_remote, open_source


def load_case():
    path = Path(__file__).resolve().parent / "samples" / "scoped_kiln.json"
    return json.loads(path.read_text(encoding="utf-8"))


def populate(source, case):
    refs = ingest(source, case["site"], case["day"], case["batch"], case["records"])
    amendments = tuple(amend(source, ref, status, case["author"]).amendment_id
                       for ref, status in zip(refs, case["quality"], strict=True))
    return freeze_day(source, case["site"], case["day"], amendments)


def trusted_inputs(anchor, grant):
    return bytes(anchor), deepcopy(grant)


def probe_v1():
    case = load_case()
    with closing(open_source(":memory:")) as source:
        revision = populate(source, case)
        shipment = issue(source, revision.revision_id, ("reading",))
    with closing(open_remote(":memory:")) as remote:
        receipts = tuple(receive(remote, raw) for raw in reversed(shipment.materials))
        report = reconcile_columns(remote, revision.revision_id, receipts, ("reading",))
    positions = [row["reference"]["position"] for row in report.rows]
    readings = [row["values"]["reading"] for row in report.rows]
    register = verify_material(shipment.materials[0]).body
    logs = [entry["provenance"]["log"] for entry in register["rows"]]
    assert positions == [1, 2, 3, 4] and readings == [7, 7, None, 7]
    assert report.non_null == {"reading": 3}
    assert logs == ["out.log", "internal.log", "out.log", "out.log"]
    print(json.dumps({"positions": positions, "readings": readings,
                      "non_null": report.non_null, "register_logs": logs}))


if __name__ == "__main__":
    probe_v1()
