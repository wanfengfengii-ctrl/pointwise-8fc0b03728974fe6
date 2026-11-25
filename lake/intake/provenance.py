from dataclasses import asdict, dataclass


def require_text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{name} must be nonempty text')
    return value


@dataclass(frozen=True)
class Provenance:
    device: str
    log: str
    line: int
    unit: str

    def __post_init__(self):
        require_text(self.device, 'device')
        require_text(self.log, 'log')
        require_text(self.unit, 'unit')
        if type(self.line) is not int or self.line < 1:
            raise ValueError('log line must be a positive integer')


def parse_provenance(data):
    if not isinstance(data, dict) or data.keys() != {'device', 'log', 'line', 'unit'}:
        raise ValueError('invalid provenance fields')
    return Provenance(**data)


def serialize_provenance(provenance):
    return asdict(provenance)
