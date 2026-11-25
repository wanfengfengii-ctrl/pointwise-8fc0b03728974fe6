from dataclasses import dataclass

from lake.intake.provenance import require_text


DECISION_ORDER = ('剔除', '通过', '复核')


@dataclass(frozen=True)
class QualityDecision:
    status: str
    author: str

    def __post_init__(self):
        require_text(self.author, 'quality author')
        if self.status not in DECISION_ORDER:
            raise ValueError('quality status must be 通过, 复核 or 剔除')


def validate_decision(status, author):
    return QualityDecision(status, author)
