"""Парсер маски ИРВИС-Ультра-Пп (п. 3.1 РЭ)."""



from __future__ import annotations



import re

from typing import Any



from .common import parse_fields_from_tokens, split_mask_tokens



_PP_MARKER = re.compile(r"^(ПП|PP)$", re.IGNORECASE)

_POWER = re.compile(r"^(ВП|АП|VP|AP)$", re.IGNORECASE)





def _data_tokens_after_prefix(text: str) -> list[str]:

    """Вернуть сегменты маски после «…-Пп-» в порядке следования."""

    tokens = split_mask_tokens(text)

    for index, token in enumerate(tokens):

        if _PP_MARKER.match(token):

            return tokens[index + 1 :]

    return []





def _map_positional_tokens(data: list[str]) -> dict[str, str]:

    """

    Позиционная структура после префикса:

    [давление, DN, Qmax, (питание)?, точность].

    """

    found: dict[str, str] = {}

    if len(data) >= 1:

        found["pressure"] = data[0]

    if len(data) >= 2:

        dn_token = data[1]

        if dn_token.upper().startswith("DN"):

            found["dn"] = f"DN{dn_token[2:]}" if dn_token[2:].isdigit() else dn_token.upper()

        elif dn_token.isdigit():

            found["dn"] = f"DN{dn_token}"

        else:

            found["dn"] = dn_token

    if len(data) >= 3:

        found["qmax"] = data[2]

    if len(data) == 4:

        tail = data[3]

        if _POWER.match(tail):

            found["power"] = tail

        else:

            found["accuracy"] = tail

    elif len(data) >= 5:

        found["power"] = data[3]

        found["accuracy"] = data[4]

    return found





def parse_irvis_ultra_mask(text: str, catalog: dict[str, Any]):

    data = _data_tokens_after_prefix(text)

    tokens = _map_positional_tokens(data)

    return parse_fields_from_tokens(

        text,

        catalog,

        tokens,

        ("pressure", "dn", "qmax", "power", "accuracy"),

    )


