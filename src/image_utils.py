"""Utilitaires de préparation des images avant leur envoi vers Supabase."""

from __future__ import annotations

import io
from typing import BinaryIO

from PIL import Image, ImageOps, UnidentifiedImageError


def compress_image(file: BinaryIO) -> io.BytesIO:
    """Redimensionne une image et la retourne au format WEBP en mémoire.

    La plus grande dimension est limitée à 1 200 pixels, sans déformation.
    Une ``ValueError`` est levée si le fichier ne peut pas être lu comme image.
    """
    try:
        file.seek(0)
        with Image.open(file) as source:
            # La conversion RGB évite les problèmes de transparence ou de palette
            # rencontrés avec certains formats lors de l'enregistrement en WEBP.
            image = ImageOps.exif_transpose(source).convert("RGB")
            image.thumbnail((1200, 1200), Image.Resampling.LANCZOS)

            buffer = io.BytesIO()
            image.save(buffer, format="WEBP", quality=80, method=6)
            buffer.seek(0)
            return buffer
    except (UnidentifiedImageError, OSError) as error:
        raise ValueError("Le fichier fourni n'est pas une image valide.") from error
