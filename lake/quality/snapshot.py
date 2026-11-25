from dataclasses import dataclass

from lake.intake.observations import Observation, validate_day
from lake.intake.store import read_day_observations
from lake.quality.amendments import Amendment, load_amendment
from lake.storage import validate_local_id


@dataclass(frozen=True)
class FrozenRow:
    observation: Observation
    amendment: Amendment | None

    @property
    def quality(self):
        return None if self.amendment is None else self.amendment.decision.status


def build_snapshot(db, site, day, amendment_ids):
    validate_day(site, day)
    if not isinstance(amendment_ids, (tuple, list)):
        raise ValueError('amendment_ids must be a list or tuple')
    ids = {validate_local_id(number, 'amendment_id') for number in amendment_ids}
    effective = {}
    for number in sorted(ids):
        amendment = load_amendment(db, number)
        if (amendment.ref.site, amendment.ref.day) != (site, day):
            raise ValueError('amendment belongs to a different station day')
        effective[amendment.ref] = amendment

    observations = read_day_observations(db, site, day)
    return tuple(FrozenRow(observation, effective.get(observation.ref))
                 for observation in observations)
