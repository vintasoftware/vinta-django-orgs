from typing import Any

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _


def validator_gt_2(value: Any) -> int:
    if int(value) <= 2:
        raise ValidationError(_('This field must be a valid integer'))

    return int(value)


def validator_lt_2(value: Any) -> int:
    if int(value) >= 2:
        raise ValidationError(_('This field must be a valid integer'))

    return int(value)
