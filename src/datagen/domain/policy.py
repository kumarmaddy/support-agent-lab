"""Business-rule helpers shared by the generator, the label writer and (later) the policy engine."""
from datetime import datetime

from src.datagen import config


def days_since_delivery(delivered_at: datetime, as_of: datetime = config.AS_OF_DATETIME) -> int:
    """Whole calendar days between the delivery date and the reference date."""
    return (as_of.date() - delivered_at.date()).days


def within_return_window(delivered_at: datetime, as_of: datetime = config.AS_OF_DATETIME) -> bool:
    """Policy: returns are accepted up to 30 calendar days after delivery, inclusive."""
    return days_since_delivery(delivered_at, as_of) <= config.RETURN_WINDOW_DAYS