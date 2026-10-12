"""Accès à Supabase : table des photos et stockage des fichiers."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import unquote, urlparse
from uuid import uuid4

import streamlit as st
from supabase import Client, create_client

BUCKET_NAME = "album-photos"


@st.cache_resource
def get_supabase_client() -> Client:
    """Construit et met en cache le client Supabase de l'application."""
    try:
        return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
    except KeyError as error:
        raise RuntimeError(
            "Les secrets SUPABASE_URL et SUPABASE_KEY doivent être configurés."
        ) from error


@st.cache_data(ttl=300, show_spinner="Chargement des souvenirs...")
def get_photos(profile: str, sort_by: str = "date_start") -> list[dict[str, Any]]:
    """Retourne les photos d'un profil triées par date de début ou de publication."""
    if sort_by not in {"date_start", "created_at"}:
        raise ValueError("Critère de tri des photos invalide.")
    try:
        query = (
            get_supabase_client()
            .table("photos")
            .select(
                "id, created_at, title, category, image_url, location, profile, "
                "date_start, date_end, preview_img, content, emoji, latitude, longitude"
            )
            .eq("profile", profile)
        )
        query = query.order(sort_by, desc=True, nullsfirst=False)
        if sort_by != "created_at":
            query = query.order("created_at", desc=True)
        response = query.execute()
        return list(response.data or [])
    except Exception as error:
        raise RuntimeError("Impossible de récupérer les photos depuis Supabase.") from error


@st.cache_data(ttl=300, show_spinner="Chargement des lieux...")
def get_map_photos() -> list[dict[str, Any]]:
    """Retourne les souvenirs de tous les profils pour la carte."""
    try:
        response = (
            get_supabase_client()
            .table("photos")
            .select(
                "id, title, location, date_start, created_at, latitude, longitude"
            )
            .order("created_at", desc=True)
            .execute()
        )
        return list(response.data or [])
    except Exception as error:
        raise RuntimeError("Impossible de récupérer les lieux depuis Supabase.") from error


def insert_photo(
    *,
    title: str,
    category: str,
    image_url: str,
    location: str | None,
    profile: str,
    date_start: str | None,
    date_end: str | None,
    preview_img: str | None,
    content: str | None,
    emoji: str | None,
    latitude: float | None,
    longitude: float | None,
) -> None:
    """Ajoute les métadonnées d'une photo dans la table ``photos``."""
    try:
        get_supabase_client().table("photos").insert(
            {
                "title": title,
                "category": category,
                "image_url": image_url,
                "location": location,
                "profile": profile,
                "date_start": date_start,
                "date_end": date_end,
                "preview_img": preview_img,
                "content": content,
                "emoji": emoji,
                "latitude": latitude,
                "longitude": longitude,
            }
        ).execute()
    except Exception as error:
        raise RuntimeError("Impossible d'enregistrer l'entrée dans la base.") from error


def _storage_object_path(image_url: str | None) -> str | None:
    """Extrait le chemin d'un objet public de notre bucket, sinon renvoie None."""
    if not image_url:
        return None
    parsed_url = urlparse(image_url)
    supabase_host = urlparse(st.secrets["SUPABASE_URL"]).netloc
    if parsed_url.netloc != supabase_host:
        return None
    path = unquote(parsed_url.path)
    bucket_prefix = f"/storage/v1/object/public/{BUCKET_NAME}/"
    if not path.startswith(bucket_prefix):
        return None
    object_path = path[len(bucket_prefix):]
    if any(part in {".", ".."} for part in object_path.split("/")):
        return None
    return object_path or None


def delete_photo(*, photo_id: int, image_url: str, preview_img: str | None) -> None:
    """Supprime les images de notre bucket puis la ligne de la table photos."""
    try:
        storage = get_supabase_client().storage.from_(BUCKET_NAME)
        try:
            image_urls = json.loads(image_url)
        except (TypeError, json.JSONDecodeError):
            image_urls = image_url
        if not isinstance(image_urls, list):
            image_urls = [image_urls]
        paths = {
            path
            for url in [*image_urls, preview_img]
            if isinstance(url, str)
            if (path := _storage_object_path(url))
        }
        if paths:
            storage.remove(sorted(paths))

        get_supabase_client().table("photos").delete().eq("id", photo_id).execute()
    except Exception as error:
        raise RuntimeError(
            "Impossible de supprimer le souvenir et ses images du stockage."
        ) from error


def upload_image(image_data: bytes, *, label: str = "image") -> str:
    """Envoie une image WEBP dans Storage et retourne son URL publique."""
    object_path = f"{uuid4().hex}.webp"
    try:
        storage = get_supabase_client().storage.from_(BUCKET_NAME)
        storage.upload(
            path=object_path,
            file=image_data,
            file_options={"content-type": "image/webp", "upsert": "false"},
        )
        return storage.get_public_url(object_path)
    except Exception as error:
        raise RuntimeError(
            f"Échec de l'envoi de {label} vers Supabase Storage : "
            f"{type(error).__name__} — {error}"
        ) from error
