"""Reproduce an Light state."""
from __future__ import annotations

import asyncio
from collections.abc import Iterable
import logging
from types import MappingProxyType
from typing import Any, cast

from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_OFF,
    STATE_ON,
)
from homeassistant.core import Context, HomeAssistant, State

from . import (
    ATTR_BRIGHTNESS,
    ATTR_BRIGHTNESS_PCT,
    ATTR_COLOR_MODE,
    ATTR_COLOR_NAME,
    ATTR_COLOR_TEMP,
    ATTR_EFFECT,
    ATTR_FLASH,
    ATTR_HS_COLOR,
    ATTR_KELVIN,
    ATTR_PROFILE,
    ATTR_RGB_COLOR,
    ATTR_RGBW_COLOR,
    ATTR_RGBWW_COLOR,
    ATTR_TRANSITION,
    ATTR_WHITE,
    ATTR_WHITE_VALUE,
    ATTR_XY_COLOR,
    COLOR_MODE_COLOR_TEMP,
    COLOR_MODE_HS,
    COLOR_MODE_RGB,
    COLOR_MODE_RGBW,
    COLOR_MODE_RGBWW,
    COLOR_MODE_UNKNOWN,
    COLOR_MODE_WHITE,
    COLOR_MODE_XY,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

VALID_STATES = {STATE_ON, STATE_OFF}

ATTR_GROUP = [
    ATTR_BRIGHTNESS,
    ATTR_BRIGHTNESS_PCT,
    ATTR_EFFECT,
    ATTR_FLASH,
    ATTR_WHITE_VALUE,
    ATTR_TRANSITION,
]

COLOR_GROUP = [
    ATTR_HS_COLOR,
    ATTR_COLOR_TEMP,
    ATTR_RGB_COLOR,
    ATTR_RGBW_COLOR,
    ATTR_RGBWW_COLOR,
    ATTR_XY_COLOR,
    # The following color attributes are deprecated
    ATTR_PROFILE,
    ATTR_COLOR_NAME,
    ATTR_KELVIN,
]

COLOR_MODE_TO_ATTRIBUTE = {
    COLOR_MODE_COLOR_TEMP: (ATTR_COLOR_TEMP, ATTR_COLOR_TEMP),
    COLOR_MODE_HS: (ATTR_HS_COLOR, ATTR_HS_COLOR),
    COLOR_MODE_RGB: (ATTR_RGB_COLOR, ATTR_RGB_COLOR),
    COLOR_MODE_RGBW: (ATTR_RGBW_COLOR, ATTR_RGBW_COLOR),
    COLOR_MODE_RGBWW: (ATTR_RGBWW_COLOR, ATTR_RGBWW_COLOR),
    COLOR_MODE_WHITE: (ATTR_WHITE, ATTR_BRIGHTNESS),
    COLOR_MODE_XY: (ATTR_XY_COLOR, ATTR_XY_COLOR),
}

DEPRECATED_GROUP = [
    ATTR_BRIGHTNESS_PCT,
    ATTR_COLOR_NAME,
    ATTR_FLASH,
    ATTR_KELVIN,
    ATTR_PROFILE,
    ATTR_TRANSITION,
]

DEPRECATION_WARNING = (
    "The use of other attributes than device state attributes is deprecated and will be removed in a future release. "
    "Invalid attributes are %s. Read the logs for further details: https://www.home-assistant.io/integrations/scene/"
)


def _color_mode_same(cur_state: State, state: State) -> bool:
    """Test if color_mode is same."""
    cur_color_mode = cur_state.attributes.get(ATTR_COLOR_MODE, COLOR_MODE_UNKNOWN)
    saved_color_mode = state.attributes.get(ATTR_COLOR_MODE, COLOR_MODE_UNKNOWN)

    # Guard for scenes etc. which where created before color modes were introduced
    if saved_color_mode == COLOR_MODE_UNKNOWN:
        return True
    return cast(bool, cur_color_mode == saved_color_mode)


async def _async_reproduce_state(
    hass: HomeAssistant,
    state: State,
    *,
    context: Context | None = None,
    reproduce_options: dict[str, Any] | None = None,
) -> None:
    """Reproduce a single state."""
    cur_state = hass.states.get(state.entity_id)

    if cur_state is None:
        _LOGGER.warning("Unable to find entity %s", state.entity_id)
        return

    if state.state not in VALID_STATES:
        _LOGGER.warning(
            "Invalid state specified for %s: %s", state.entity_id, state.state
        )
        return

    # Warn if deprecated attributes are used
    deprecated_attrs = [attr for attr in state.attributes if attr in DEPRECATED_GROUP]
    if deprecated_attrs:
        _LOGGER.warning(DEPRECATION_WARNING, deprecated_attrs)

    if ATTR_WHITE in state.attributes and ATTR_COLOR_MODE not in state.attributes:
        state_dict = state.as_dict()
        state_dict["attributes"][ATTR_BRIGHTNESS] = state.attributes[ATTR_WHITE]
        state_dict["attributes"][ATTR_COLOR_MODE] = COLOR_MODE_WHITE
        state = State.from_dict(state_dict)

    # Return if we are already at the right state.
    if (
        cur_state.state == state.state
        and _color_mode_same(cur_state, state)
        and all(
            check_attr_equal(cur_state.attributes, state.attributes, attr)
            for attr in ATTR_GROUP + COLOR_GROUP
        )
    ):
        return

    service_data: dict[str, Any] = {ATTR_ENTITY_ID: state.entity_id}

    if reproduce_options is not None and ATTR_TRANSITION in reproduce_options:
        service_data[ATTR_TRANSITION] = reproduce_options[ATTR_TRANSITION]

    if state.state == STATE_ON:
        service = SERVICE_TURN_ON
        for attr in ATTR_GROUP:
            # All attributes that are not colors
            if attr in state.attributes:
                service_data[attr] = state.attributes[attr]

        if (
            state.attributes.get(ATTR_COLOR_MODE, COLOR_MODE_UNKNOWN)
            != COLOR_MODE_UNKNOWN
        ):
            # Remove deprecated white value if we got a valid color mode
            service_data.pop(ATTR_WHITE_VALUE, None)
            color_mode = state.attributes[ATTR_COLOR_MODE]
            if parameter_state := COLOR_MODE_TO_ATTRIBUTE.get(color_mode):
                parameter, state_attr = parameter_state
                if state_attr not in state.attributes:
                    _LOGGER.warning(
                        "Color mode %s specified but attribute %s missing for: %s",
                        color_mode,
                        state_attr,
                        state.entity_id,
                    )
                    return
                service_data[parameter] = state.attributes[state_attr]
        else:
            # Fall back to Choosing the first color that is specified
            for color_attr in COLOR_GROUP:
                if color_attr in state.attributes:
                    service_data[color_attr] = state.attributes[color_attr]
                    break

    elif state.state == STATE_OFF:
        service = SERVICE_TURN_OFF

    await hass.services.async_call(
        DOMAIN, service, service_data, context=context, blocking=True
    )


async def async_reproduce_states(
    hass: HomeAssistant,
    states: Iterable[State],
    *,
    context: Context | None = None,
    reproduce_options: dict[str, Any] | None = None,
) -> None:
    """Reproduce Light states."""
    await asyncio.gather(
        *(
            _async_reproduce_state(
                hass, state, context=context, reproduce_options=reproduce_options
            )
            for state in states
        )
    )


def check_attr_equal(
    attr1: MappingProxyType, attr2: MappingProxyType, attr_str: str
) -> bool:
    """Return true if the given attributes are equal."""
    return attr1.get(attr_str) == attr2.get(attr_str)
