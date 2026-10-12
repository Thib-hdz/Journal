"""Suggestions d'adresses OpenStreetMap via Photon et GeoPy."""

from __future__ import annotations

from typing import Any

import streamlit as st
from geopy.exc import GeopyError
from geopy.extra.rate_limiter import RateLimiter
from geopy.geocoders import Photon


@st.cache_resource
def _get_geocode_service() -> RateLimiter:
    """Construit un client Photon identifié et limité en fréquence."""
    geolocator = Photon(user_agent="journal-familial-streamlit", timeout=8)
    return RateLimiter(
        geolocator.geocode,
        min_delay_seconds=1,
        max_retries=1,
        error_wait_seconds=2,
        swallow_exceptions=False,
    )


@st.cache_data(ttl=86400, show_spinner=False)
def search_locations(searchterm: str) -> list[tuple[str, dict[str, Any]]]:
    """Retourne jusqu'à cinq suggestions avec libellé et coordonnées GPS."""
    query = searchterm.strip()
    if len(query) < 3:
        return []
    try:
        results = _get_geocode_service()(
            query,
            exactly_one=False,
            limit=5,
            language="fr",
            timeout=8,
        )
    except GeopyError as error:
        raise RuntimeError("La recherche d’adresses est temporairement indisponible.") from error
    if not results:
        return []
    return [
        (
            result.address,
            {
                "location": result.address,
                "latitude": float(result.latitude),
                "longitude": float(result.longitude),
            },
        )
        for result in results
    ]
