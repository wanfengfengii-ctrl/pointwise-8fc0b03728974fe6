from lake.intake.observations import Observation, ObservationRef, validate_day
from lake.intake.provenance import parse_provenance, require_text


def validate_reading(value):
    if value is not None and type(value) is not int:
        raise ValueError('observation value must be an integer or null')
    return value


def validate_batch(site, day, batch, records):
    validate_day(site, day)
    require_text(batch, 'batch')
    if not isinstance(records, (list, tuple)) or not records:
        raise ValueError('batch must contain ordered observations')

    observations = []
    for position, record in enumerate(records, start=1):
        if (not isinstance(record, dict)
                or not {'reading', 'provenance'} <= record.keys()
                or record.keys() - {'reading', 'provenance', 'temperature'}):
            raise ValueError(f'invalid observation fields at position {position}')
        observations.append(Observation(
            ObservationRef(site, day, batch, position),
            validate_reading(record['reading']),
            validate_reading(record.get('temperature')),
            parse_provenance(record['provenance']),
        ))
    return tuple(observations)
