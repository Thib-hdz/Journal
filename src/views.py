"""Composants d'interface Streamlit du journal et de son administration."""

from __future__ import annotations

import hmac
import html
import json
from datetime import date, datetime, time, timezone
from typing import Any

import streamlit as st
import folium
from streamlit_searchbox import st_searchbox
from streamlit_folium import st_folium

from src.database import (
    delete_photo,
    get_map_photos,
    get_photos,
    insert_photo,
    upload_image,
)
from src.geocoding import search_locations
from src.image_utils import compress_image

PROFILES = {"thibaut": "Thibaut", "clara": "Clara"}


def _date_as_utc_timestamp(value: date | None) -> str | None:
    """Convertit une date choisie en horodatage UTC à minuit."""
    if value is None:
        return None
    return datetime.combine(value, time.min, tzinfo=timezone.utc).isoformat()


def get_profile_from_query_params() -> str | None:
    """Retourne le profil URL valide, ou ``None`` si aucun n'est sélectionné."""
    profile = str(st.query_params.get("profile", "")).lower()
    return profile if profile in PROFILES else None


def _select_profile(profile: str) -> None:
    """Met à jour le profil actif dans l'URL puis recharge l'application."""
    st.query_params["profile"] = profile
    st.rerun()


@st.dialog("Bienvenue dans notre journal")
def render_profile_selector_dialog() -> None:
    """Demande le journal à afficher lors d'une première visite."""
    st.write("Quel journal souhaitez-vous découvrir ?")
    first, second = st.columns(2)
    with first:
        if st.button("Le Journal de Thibaut", type="primary", use_container_width=True):
            _select_profile("thibaut")
    with second:
        if st.button("Le Journal de Clara", type="primary", use_container_width=True):
            _select_profile("clara")


def render_profile_switch(profile: str) -> None:
    """Affiche un bouton permanent pour alterner entre les deux journaux."""
    other_profile = "clara" if profile == "thibaut" else "thibaut"
    st.caption(f"Journal affiché : **{PROFILES[profile]}**")
    if st.button(
        f"Voir le journal de {PROFILES[other_profile]}",
        key="switch_profile",
        use_container_width=True,
    ):
        _select_profile(other_profile)


def _format_date(value: str | None) -> str:
    """Formate la date ISO fournie par Supabase pour l'affichage."""
    if not value:
        return "Date inconnue"
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime("%d/%m/%Y")
    except ValueError:
        return value


def _photo_preview(photo: dict[str, Any]) -> str:
    """Retourne l’aperçu s’il existe, sinon l’image originale."""
    return photo.get("preview_img") or next(iter(_photo_images(photo)), "")


def _photo_images(photo: dict[str, Any]) -> list[str]:
    """Lit la liste JSON d’images et accepte aussi les anciennes URL simples."""
    image_url = photo.get("image_url")
    if not image_url:
        return []
    try:
        decoded = json.loads(image_url)
    except (TypeError, json.JSONDecodeError):
        decoded = image_url
    if isinstance(decoded, list):
        return [url for url in decoded if isinstance(url, str) and url]
    return [decoded] if isinstance(decoded, str) and decoded else []


def _change_gallery_index(photo_id: int, image_count: int, step: int) -> None:
    key = f"photo_gallery_index_{photo_id}"
    st.session_state[key] = (st.session_state.get(key, 0) + step) % image_count


def _rotate_gallery_photo(photo_id: int, image_index: int, degrees: int) -> None:
    key = f"photo_rotation_{photo_id}_{image_index}"
    st.session_state[key] = (st.session_state.get(key, 0) + degrees) % 360


def _show_photo_dialog(photo: dict[str, Any]) -> None:
    """Ouvre le détail avec le texte avant une galerie de vignettes."""
    title = photo.get("title") or "Sans titre"

    @st.dialog(title, width="large")
    def render_contents() -> None:
        if photo.get("category"):
            st.caption(photo["category"])
        if photo.get("date_start") or photo.get("date_end"):
            start = _format_date(photo.get("date_start")) if photo.get("date_start") else "?"
            end = _format_date(photo.get("date_end")) if photo.get("date_end") else "?"
            st.caption(f"{start} – {end}")
        if photo.get("location"):
            st.caption(f"📍 {photo['location']}")
        if photo.get("emoji"):
            st.markdown(photo["emoji"])
        if photo.get("content"):
            st.write(photo["content"])

        photo_images = _photo_images(photo)
        if photo_images:
            gallery_key = f"photo_gallery_index_{photo['id']}"
            st.session_state.setdefault(gallery_key, 0)
            st.session_state[gallery_key] %= len(photo_images)
            current_index = st.session_state[gallery_key]
            rotation_key = f"photo_rotation_{photo['id']}_{current_index}"
            st.session_state.setdefault(rotation_key, 0)
            rotation = st.session_state[rotation_key]
            st.markdown(
                f"""
                <style>
                [role="dialog"] [data-testid="stImage"] img {{
                    display: block;
                    width: min(100%, 420px);
                    height: 420px;
                    object-fit: contain;
                    border-radius: 10px;
                    background: rgba(0, 0, 0, .12);
                    margin: 0 auto;
                    transform: rotate({rotation}deg);
                }}
                </style>
                """,
                unsafe_allow_html=True,
            )
            previous, image_area, following = st.columns([1, 10, 1])
            with previous:
                st.button(
                    "←",
                    key=f"photo_gallery_previous_{photo['id']}",
                    disabled=len(photo_images) < 2,
                    use_container_width=True,
                    on_click=_change_gallery_index,
                    args=(photo["id"], len(photo_images), -1),
                )
            with following:
                st.button(
                    "→",
                    key=f"photo_gallery_next_{photo['id']}",
                    disabled=len(photo_images) < 2,
                    use_container_width=True,
                    on_click=_change_gallery_index,
                    args=(photo["id"], len(photo_images), 1),
                )
            with image_area:
                st.image(
                    photo_images[current_index],
                    use_container_width=True,
                )
                rotate_left, counter, rotate_right = st.columns([1, 2, 1])
                with rotate_left:
                    st.button(
                        "↶ 90°",
                        key=f"photo_rotate_left_{photo['id']}_{current_index}",
                        use_container_width=True,
                        on_click=_rotate_gallery_photo,
                        args=(photo["id"], current_index, -90),
                    )
                with counter:
                    if len(photo_images) > 1:
                        st.caption(f"Photo {current_index + 1} sur {len(photo_images)}")
                with rotate_right:
                    st.button(
                        "↻ 90°",
                        key=f"photo_rotate_right_{photo['id']}_{current_index}",
                        use_container_width=True,
                        on_click=_rotate_gallery_photo,
                        args=(photo["id"], current_index, 90),
                    )

    render_contents()


@st.dialog("Supprimer ce souvenir ?")
def _confirm_delete_photo(photo: dict[str, Any]) -> None:
    """Demande confirmation avant de supprimer la carte et ses fichiers."""
    st.warning(
        f"La suppression de « {photo.get('title') or 'Sans titre'} » est définitive. "
        "Les images associées dans Storage seront également supprimées."
    )
    confirm, cancel = st.columns(2)
    with confirm:
        if st.button("Supprimer définitivement", type="primary", use_container_width=True):
            try:
                delete_photo(
                    photo_id=photo["id"],
                    image_url=photo["image_url"],
                    preview_img=photo.get("preview_img"),
                )
                get_photos.clear()
                get_map_photos.clear()
                st.success("Souvenir supprimé.")
                st.rerun()
            except RuntimeError as error:
                st.error(str(error))
    with cancel:
        if st.button("Annuler", use_container_width=True):
            st.rerun()


def render_gallery_sidebar(profile: str) -> list[dict[str, Any]] | None:
    """Affiche le tri et le sommaire défilant dans la barre latérale."""
    sort_by = st.selectbox(
        "Trier les souvenirs par",
        options=["date_start", "created_at"],
        format_func=lambda value: {
            "date_start": "Date de début (décroissante)",
            "created_at": "Date de publication (décroissante)",
        }[value],
        key=f"gallery_sort_{profile}",
    )
    try:
        photos = get_photos(profile, sort_by=sort_by)
    except RuntimeError as error:
        st.error(str(error))
        return None

    if not photos:
        st.caption("Aucun souvenir à afficher.")
        return photos

    st.markdown("**Sommaire des souvenirs**")
    links = []
    for photo in photos:
        title = html.escape(photo.get("title") or "Sans titre")
        category = html.escape(photo.get("category") or "Non classé")
        start_date = html.escape(_format_date(photo.get("date_start")))
        anchor = html.escape(f"photo-{photo['id']}", quote=True)
        links.append(
            f'<a href="#{anchor}" target="_self" '
            'style="display:block; padding:.4rem .2rem; text-decoration:none;">'
            f'{title}<br><span style="opacity:.7;font-size:.85em">'
            f'{start_date} · {category}</span></a>'
        )
    st.markdown(
        '<div style="height:320px; overflow-y:auto; padding-right:.4rem;">'
        + "".join(links)
        + "</div>",
        unsafe_allow_html=True,
    )
    return photos


def render_gallery(
    profile: str,
    photos: list[dict[str, Any]] | None,
) -> None:
    """Affiche un fil vertical de cartes avec texte et aperçu côte à côte."""
    st.title(f"📖 Le journal de {PROFILES[profile]}")
    st.caption("Ici nous partageons nos souvenirs et aventures avec vous depuis notre arrivée au Canada (les cools comme les moins cools).")

    if photos is None:
        return
    if not photos:
        st.info("Le journal est encore vide. Ajoutez le premier souvenir depuis l'espace admin.")
        return

    st.markdown(
        """
        <style>
        [data-testid="stVerticalBlockBorderWrapper"] [data-testid="stImage"] img {
            width: 100%;
            height: 240px;
            object-fit: cover;
            border-radius: 12px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    for photo in photos:
        st.markdown(
            f'<div id="photo-{html.escape(str(photo["id"]), quote=True)}"></div>',
            unsafe_allow_html=True,
        )
        with st.container(border=True):
            text_column, image_column = st.columns([2, 1])
            with text_column:
                st.subheader(photo.get("title") or "Sans titre")
                if photo.get("date_start") or photo.get("date_end"):
                    start = _format_date(photo.get("date_start")) if photo.get("date_start") else "?"
                    end = _format_date(photo.get("date_end")) if photo.get("date_end") else "?"
                    st.caption(f"📅 {start} – {end}")
                elif photo.get("created_at"):
                    st.caption(f"📅 {_format_date(photo.get('created_at'))}")
                if photo.get("location"):
                    st.caption(f"📍 {photo['location']}")
                if photo.get("category"):
                    st.caption(photo["category"])
                if photo.get("emoji"):
                    st.markdown(photo["emoji"])
                content = (photo.get("content") or "").strip()
                if content:
                    excerpt = content[:280].rstrip()
                    if len(content) > 280:
                        excerpt += "…"
                    st.write(excerpt)
                if st.button(
                    "Lire plus et voir la galerie",
                    key=f"enlarge_{photo['id']}",
                    use_container_width=True,
                ):
                    _show_photo_dialog(photo)
            with image_column:
                st.image(_photo_preview(photo), use_container_width=True)


def render_map() -> None:
    """Affiche sur une carte les souvenirs de tous les profils géolocalisés."""
    st.title("🗺️ Carte interactive")
    try:
        photos = get_map_photos()
    except RuntimeError as error:
        st.error(str(error))
        return

    grouped_locations: dict[tuple[float, float], list[dict[str, Any]]] = {}
    for photo in photos:
        try:
            latitude = float(photo["latitude"])
            longitude = float(photo["longitude"])
        except (KeyError, TypeError, ValueError):
            continue
        if -90 <= latitude <= 90 and -180 <= longitude <= 180:
            grouped_locations.setdefault((latitude, longitude), []).append(photo)

    if not grouped_locations:
        st.info("Aucun souvenir géolocalisé pour le moment.")
        return

    center = [
        sum(latitude for latitude, _ in grouped_locations) / len(grouped_locations),
        sum(longitude for _, longitude in grouped_locations) / len(grouped_locations),
    ]
    map_view = folium.Map(location=center, zoom_start=4, control_scale=True)
    for (latitude, longitude), grouped_photos in grouped_locations.items():
        place_name = next(
            (photo["location"] for photo in grouped_photos if photo.get("location")),
            "Lieu inconnu",
        )
        location_markup = html.escape(str(place_name))
        memories_markup = "".join(
            "<li>"
            f"<time>{html.escape(_format_date(photo.get('date_start') or photo.get('created_at')))}</time>"
            f" — {html.escape(photo.get('title') or 'Sans titre')}</li>"
            for photo in grouped_photos
        )
        popup_html = (
            f'<div style="min-width:220px"><strong>{location_markup}</strong>'
            f"<ul style=\"margin:8px 0 0;padding-left:20px\">{memories_markup}</ul></div>"
        )
        folium.Marker(
            location=[latitude, longitude],
            tooltip=f"{place_name} · {len(grouped_photos)} souvenir(s)",
            popup=folium.Popup(popup_html, max_width=260),
            icon=folium.Icon(color="red", icon="map-marker", prefix="fa"),
        ).add_to(map_view)

    if len(grouped_locations) > 1:
        map_view.fit_bounds(
            [[latitude, longitude] for latitude, longitude in grouped_locations],
            padding=(24, 24),
        )
    st_folium(map_view, height=650, use_container_width=True, returned_objects=[])


def _is_admin_authenticated() -> bool:
    """Demande et vérifie le mot de passe administrateur pour cette session."""
    if st.session_state.get("is_admin", False):
        return True

    password = st.text_input("Mot de passe", type="password", key="admin_password")
    if st.button("Déverrouiller", type="primary", use_container_width=True):
        expected_password = st.secrets.get("ADMIN_PASSWORD", "")
        if expected_password and hmac.compare_digest(password, expected_password):
            st.session_state.is_admin = True
            st.rerun()
        st.error("Mot de passe incorrect.")
    return False


def _search_location_options(searchterm: str) -> list[tuple[str, dict[str, Any]]]:
    """Fournit des adresses candidates à la recherche interactive."""
    st.session_state.location_search_error = None
    try:
        return search_locations(searchterm)
    except RuntimeError as error:
        st.session_state.location_search_error = str(error)
        return []


def render_admin() -> None:
    """Affiche l'espace sécurisé de publication des souvenirs."""
    st.title("🔒 Espace Admin")
    st.caption("Publiez une nouvelle photo dans le journal familial.")

    if not _is_admin_authenticated():
        return

    form_was_reset = st.session_state.pop("reset_new_photo_form", False)
    if form_was_reset:
        for widget_key in (
            "photo_title",
            "photo_category",
            "photo_location_search",
            "photo_date_start",
            "photo_date_end",
            "photo_content",
            "photo_emoji",
            "photo_profile",
            "photo_upload",
            "photo_preview_upload",
        ):
            st.session_state.pop(widget_key, None)
        st.session_state.pop("location_search_error", None)

    if st.button("Se déconnecter"):
        st.session_state.is_admin = False
        st.rerun()
    if form_was_reset:
        st.success("Souvenir publié avec succès !")

    with st.expander("Gérer les souvenirs publiés"):
        profile_to_manage = st.selectbox(
            "Journal à gérer",
            options=list(PROFILES),
            format_func=lambda value: PROFILES[value],
            key="admin_manage_profile",
        )
        try:
            existing_photos = get_photos(profile_to_manage)
        except RuntimeError as error:
            st.error(str(error))
            existing_photos = []

        if not existing_photos:
            st.info("Aucun souvenir dans ce journal.")
        for photo in existing_photos:
            with st.container(border=True):
                preview, details = st.columns([1, 3])
                with preview:
                    st.image(_photo_preview(photo), use_container_width=True)
                with details:
                    st.subheader(photo.get("title") or "Sans titre")
                    st.caption(
                        f"{PROFILES[photo['profile']]} · "
                        f"{_format_date(photo.get('created_at'))}"
                    )
                    if st.button(
                        "Supprimer ce souvenir",
                        key=f"delete_photo_{photo['id']}",
                        type="secondary",
                    ):
                        _confirm_delete_photo(photo)

    title = st.text_input(
        "Titre / légende",
        placeholder="Un merveilleux coucher de soleil",
        key="photo_title",
    )
    category = st.text_input(
        "Catégorie", placeholder="Voyage, famille…", key="photo_category"
    )
    location_result = st_searchbox(
        _search_location_options,
        label="Lieu",
        placeholder="Saisissez au moins trois caractères, puis choisissez une adresse",
        key="photo_location_search",
        debounce=1000,
    )
    location = ""
    latitude = longitude = None
    if isinstance(location_result, dict):
        location = str(location_result.get("location", "")).strip()
        try:
            latitude = float(location_result["latitude"])
            longitude = float(location_result["longitude"])
        except (KeyError, TypeError, ValueError):
            latitude = longitude = None
    if latitude is not None and longitude is not None:
        st.caption(f"Coordonnées sélectionnées : {latitude:.5f}, {longitude:.5f}")
    if st.session_state.get("location_search_error"):
        st.warning(st.session_state.location_search_error)
    date_start = st.date_input(
        "Date de début", value=None, format="DD/MM/YYYY", key="photo_date_start"
    )
    date_end = st.date_input(
        "Date de fin", value=None, format="DD/MM/YYYY", key="photo_date_end"
    )
    content = st.text_area("Description", key="photo_content")
    emoji = st.text_input("Emoji", placeholder="📷", key="photo_emoji")
    profile = st.selectbox(
        "Publier dans le journal de",
        options=list(PROFILES),
        format_func=lambda value: PROFILES[value],
        key="photo_profile",
    )
    preview_file = st.file_uploader(
        "Image d’aperçu de la carte (obligatoire)",
        type=["jpg", "jpeg", "png", "webp"],
        key="photo_preview_upload",
    )
    uploaded_files = st.file_uploader(
        "Photos du souvenir (ajoutez-en une ou plusieurs)",
        type=["jpg", "jpeg", "png", "webp"],
        accept_multiple_files=True,
        key="photo_upload",
    )

    required_fields_filled = all(
        (
            title.strip(),
            category.strip(),
            location.strip(),
            latitude is not None,
            longitude is not None,
            date_start,
            date_end,
            content.strip(),
            emoji.strip(),
            profile,
            preview_file,
            uploaded_files,
        )
    )
    if date_start and date_end and date_end < date_start:
        required_fields_filled = False
        st.warning("La date de fin doit être égale ou postérieure à la date de début.")

    submitted = st.button(
        "Publier le souvenir",
        type="primary",
        use_container_width=True,
        disabled=not required_fields_filled,
    )
    if not submitted:
        return

    try:
        with st.spinner("Compression et publication en cours..."):
            compressed_preview = compress_image(preview_file)
            preview_url = upload_image(
                compressed_preview.getvalue(), label="l’image d’aperçu"
            )
            photo_urls = []
            for index, uploaded_file in enumerate(uploaded_files, start=1):
                compressed_image = compress_image(uploaded_file)
                photo_urls.append(
                    upload_image(
                        compressed_image.getvalue(),
                        label=f"la photo {index}",
                    )
                )
            insert_photo(
                title=title.strip(),
                category=category,
                image_url=json.dumps(photo_urls),
                location=location.strip() or None,
                profile=profile,
                date_start=_date_as_utc_timestamp(date_start),
                date_end=_date_as_utc_timestamp(date_end),
                preview_img=preview_url,
                content=content.strip() or None,
                emoji=emoji.strip() or None,
                latitude=latitude,
                longitude=longitude,
            )
            get_photos.clear()
            get_map_photos.clear()
        st.session_state.reset_new_photo_form = True
        st.rerun()
    except (RuntimeError, ValueError) as error:
        st.error(str(error))
