from lake.receiving.ledger import store_receipt
from lake.receiving.verify import verify_material
from lake.storage import transaction


def receive(db, raw):
    material = verify_material(raw)
    with transaction(db):
        return store_receipt(db, material, raw)
