import hashlib
import hmac

from lake.storage import dump_record

PROOF_DOMAIN = 'haijiao-scoped-shipment-v1'


def _proof_key(anchor_digest):
    return (PROOF_DOMAIN + ':' + anchor_digest).encode('ascii')


def _cargo(grant, rows):
    return {
        'revision_id': grant['revision_id'],
        'device': grant['device'],
        'log': grant['log'],
        'columns': list(grant['columns']),
        'rows': rows,
    }


def build_proof(anchor_digest, grant, rows):
    """Sign the exact scoped payload; no out-of-scope value is ever hashed here."""
    message = dump_record(_cargo(grant, rows)).encode('utf-8')
    return hmac.new(_proof_key(anchor_digest), message, hashlib.sha256).hexdigest()


def check_proof(anchor_digest, grant, rows, proof):
    if (not isinstance(proof, str) or len(proof) != 64
            or any(character not in '0123456789abcdef' for character in proof)):
        raise ValueError('invalid shipment proof')
    expected = build_proof(anchor_digest, grant, rows)
    if not hmac.compare_digest(expected, proof):
        raise ValueError('shipment proof does not match the anchor and grant')
