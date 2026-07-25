"""Policy-only proximity decisions; no Bluetooth access exists here."""

from __future__ import annotations

from enum import StrEnum


class ProximityDisclosure(StrEnum):
    OFF = "off"
    PROMPT_BEFORE_SHARING = "prompt_before_sharing"
    AUTO_SHARE_COMPATIBLE = "auto_share_compatible"


class ProximityDecision(StrEnum):
    SUPPRESS = "suppress"
    BUZZ_ONLY = "buzz_only"
    BUZZ_AND_PROMPT = "buzz_and_prompt"
    BUZZ_AND_SHARE_SCOPED_CAPABILITY = "buzz_and_share_scoped_capability"


def decide_proximity_event(
    *,
    adult_credential_valid: bool,
    disclosure: ProximityDisclosure = ProximityDisclosure.OFF,
    emergency_privacy: bool = False,
    blocked: bool = False,
    within_haptic_cooldown: bool = False,
    independently_compatible: bool = False,
) -> ProximityDecision:
    if (
        not adult_credential_valid
        or disclosure is ProximityDisclosure.OFF
        or emergency_privacy
        or blocked
        or within_haptic_cooldown
    ):
        return ProximityDecision.SUPPRESS
    if not independently_compatible:
        return ProximityDecision.BUZZ_ONLY
    if disclosure is ProximityDisclosure.PROMPT_BEFORE_SHARING:
        return ProximityDecision.BUZZ_AND_PROMPT
    return ProximityDecision.BUZZ_AND_SHARE_SCOPED_CAPABILITY
