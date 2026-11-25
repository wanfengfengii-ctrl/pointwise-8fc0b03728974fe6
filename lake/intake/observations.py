from dataclasses import asdict, dataclass
from datetime import date

from lake.intake.provenance import Provenance, require_text
from lake.storage import validate_local_id


def validate_day(site, day):
    require_text(site, 'site')
    require_text(day, 'day')
    if date.fromisoformat(day).isoformat() != day:
        raise ValueError('day must use YYYY-MM-DD')


@dataclass(frozen=True)
class ObservationRef:
    site: str
    day: str
    batch: str
    position: int

    def __post_init__(self):
        validate_day(self.site, self.day)
        require_text(self.batch, 'batch')
        validate_local_id(self.position, 'observation position')

    def to_record(self):
        return asdict(self)


def parse_reference(data):
    if not isinstance(data, dict) or data.keys() != {'site', 'day', 'batch', 'position'}:
        raise ValueError('invalid observation reference')
    return ObservationRef(**data)


@dataclass(frozen=True)
class Observation:
    ref: ObservationRef
    reading: int | None
    temperature: int | None
    provenance: Provenance
