"""Composants d'interface Streamlit du journal et de son administration."""

from __future__ import annotations

import hmac
import html
import json
import unicodedata
from datetime import date, datetime, time, timezone
from typing import Any

import streamlit as st
import folium
from folium.plugins import MarkerCluster
from streamlit_searchbox import st_searchbox
from streamlit_folium import st_folium

from src.database import (
    delete_photo,
    get_map_photos,
    get_photos,
    insert_photo,
    update_photo,
    upload_image,
)
from src.geocoding import search_locations
from src.image_utils import compress_image

PROFILES = {"thibaut": "Thibaut", "clara": "Clara"}


def _category_label(photo: dict[str, Any]) -> str:
    return str(photo.get("category") or "Non classé").strip() or "Non classé"


def _date_as_utc_timestamp(value: date | None) -> str | None:
    """Convertit une date choisie en horodatage UTC à minuit."""
    if value is None:
        return None
    return datetime.combine(value, time.min, tzinfo=timezone.utc).isoformat()


def _date_input_value(value: str | None) -> date | None:
    """Convertit une date stockée en valeur utilisable par st.date_input."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None


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


def _toggle_card_content(key: str) -> None:
    st.session_state[key] = not st.session_state.get(key, False)


def _show_photo_dialog(photo: dict[str, Any]) -> None:
    """Ouvre une galerie plein cadre navigable par gestes tactiles."""
    @st.dialog("Galerie photo", width="large")
    def render_contents() -> None:
        photo_images = _photo_images(photo)
        if not photo_images:
            return

        gallery_key = f"photo_gallery_index_{photo['id']}"
        st.session_state.setdefault(gallery_key, 0)
        initial_index = st.session_state[gallery_key] % len(photo_images)
        image_urls = json.dumps(photo_images).replace("<", "\\u003c")
        gallery_html = r"""
        <style>
          html, body { margin: 0; padding: 0; overflow: hidden; background: #111; }
          .gallery-controls {
            display: flex; justify-content: flex-end; gap: .5rem;
            padding: .25rem .5rem; background: #111;
          }
          .gallery-controls button {
            width: 2.5rem; height: 2.5rem; border: 0; border-radius: 50%;
            color: white; background: #333; font-size: 1.4rem; cursor: pointer;
          }
          .viewer {
            width: 100%; height: min(78vh, 680px); min-height: 300px;
            display: flex; align-items: center; justify-content: center;
            overflow: hidden; background: #111; touch-action: none;
            user-select: none; -webkit-user-select: none;
          }
          .viewer img {
            width: 100%; height: 100%; object-fit: contain;
            transform-origin: center center; will-change: transform;
            pointer-events: none; -webkit-user-drag: none;
          }
        </style>
        <div class="gallery-controls">
          <button id="previous" type="button" aria-label="Photo précédente">&#8592;</button>
          <button id="next" type="button" aria-label="Photo suivante">&#8594;</button>
        </div>
        <div class="viewer" id="viewer"><img id="photo" draggable="false"></div>
        <script>
          const images = __IMAGES__;
          let index = __INDEX__;
          const viewer = document.getElementById("viewer");
          const photo = document.getElementById("photo");
          const pointers = new Map();
          let scale = 1, offsetX = 0, offsetY = 0;
          let gesture = null, lastTap = 0;
          const clamp = (value, min, max) => Math.max(min, Math.min(max, value));
          const distance = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);
          function draw() {
            photo.src = images[index];
            photo.style.transform = `translate(${offsetX}px, ${offsetY}px) scale(${scale})`;
          }
          function changePhoto(step) {
            index = (index + step + images.length) % images.length;
            scale = 1; offsetX = 0; offsetY = 0; draw();
          }
          document.getElementById("previous").addEventListener("click", () => changePhoto(-1));
          document.getElementById("next").addEventListener("click", () => changePhoto(1));
          function clampPan() {
            const maxX = viewer.clientWidth * (scale - 1) / 2;
            const maxY = viewer.clientHeight * (scale - 1) / 2;
            offsetX = clamp(offsetX, -maxX, maxX);
            offsetY = clamp(offsetY, -maxY, maxY);
          }
          viewer.addEventListener("pointerdown", event => {
            event.preventDefault();
            viewer.setPointerCapture(event.pointerId);
            pointers.set(event.pointerId, {x: event.clientX, y: event.clientY});
            if (pointers.size === 2) {
              const pair = [...pointers.values()];
              gesture = {mode: "pinch", startDistance: distance(pair[0], pair[1]), startScale: scale};
            } else {
              gesture = {mode: "single", startX: event.clientX, startY: event.clientY,
                lastX: event.clientX, lastY: event.clientY, startOffsetX: offsetX,
                startOffsetY: offsetY, moved: false};
            }
          });
          viewer.addEventListener("pointermove", event => {
            if (!pointers.has(event.pointerId)) return;
            pointers.set(event.pointerId, {x: event.clientX, y: event.clientY});
            if (pointers.size >= 2 && gesture?.mode === "pinch") {
              const pair = [...pointers.values()];
              scale = clamp(gesture.startScale * distance(pair[0], pair[1]) / gesture.startDistance, 1, 4);
              if (scale === 1) { offsetX = 0; offsetY = 0; }
              clampPan(); draw();
            } else if (pointers.size === 1 && gesture?.mode === "single") {
              const dx = event.clientX - gesture.startX;
              const dy = event.clientY - gesture.startY;
              gesture.lastX = event.clientX; gesture.lastY = event.clientY;
              if (Math.abs(dx) > 8 || Math.abs(dy) > 8) gesture.moved = true;
              if (scale > 1) {
                offsetX = gesture.startOffsetX + dx;
                offsetY = gesture.startOffsetY + dy;
                clampPan(); draw();
              }
            }
          });
          function endPointer(event) {
            const priorGesture = gesture;
            pointers.delete(event.pointerId);
            if (pointers.size === 1) {
              const remaining = [...pointers.values()][0];
              gesture = {mode: "single", startX: remaining.x, startY: remaining.y,
                lastX: remaining.x, lastY: remaining.y, startOffsetX: offsetX,
                startOffsetY: offsetY, moved: true};
              return;
            }
            if (pointers.size === 0) {
              if (priorGesture?.mode === "single" && scale === 1) {
                const dx = event.clientX - priorGesture.startX;
                const dy = event.clientY - priorGesture.startY;
                if (Math.abs(dx) > 45 && Math.abs(dx) > Math.abs(dy) * 1.25) changePhoto(dx < 0 ? 1 : -1);
              }
              gesture = null;
            }
          }
          viewer.addEventListener("pointerup", endPointer);
          viewer.addEventListener("pointercancel", endPointer);
          viewer.addEventListener("click", () => {
            const now = Date.now();
            if (now - lastTap < 320) {
              scale = scale > 1 ? 1 : 2;
              if (scale === 1) { offsetX = 0; offsetY = 0; }
              clampPan(); draw(); lastTap = 0;
            } else lastTap = now;
          });
          draw();
        </script>
        """
        gallery_html = gallery_html.replace("__IMAGES__", image_urls).replace("__INDEX__", str(initial_index))
        st.components.v1.html(gallery_html, height=680, scrolling=False)

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
                    content_key = f"expanded_content_{photo['id']}"
                    expanded = st.session_state.get(content_key, False)
                    if len(content) > 280 and not expanded:
                        st.write(content[:280].rstrip() + "\u2026")
                        st.button(
                            "Lire plus",
                            key=f"read_more_{photo['id']}",
                            on_click=_toggle_card_content,
                            args=(content_key,),
                        )
                    else:
                        st.write(content)
                        if len(content) > 280:
                            st.button(
                                "Lire moins",
                                key=f"read_less_{photo['id']}",
                                on_click=_toggle_card_content,
                                args=(content_key,),
                            )
            with image_column:
                st.image(_photo_preview(photo), use_container_width=True)
                if _photo_images(photo):
                    if st.button(
                        "\U0001F4F7 Voir les photos",
                        key=f"view_photos_{photo['id']}",
                        use_container_width=True,
                    ):
                        _show_photo_dialog(photo)
def render_map() -> None:
    """Affiche sur une carte les souvenirs de tous les profils géolocalisés."""
    st.title("🗺️ Carte interactive")
    try:
        photos = get_map_photos()
    except RuntimeError as error:
        st.error(str(error))
        return

    geolocated_photos: list[dict[str, Any]] = []
    for photo in photos:
        try:
            latitude = float(photo["latitude"])
            longitude = float(photo["longitude"])
        except (KeyError, TypeError, ValueError):
            continue
        if -90 <= latitude <= 90 and -180 <= longitude <= 180:
            geolocated_photos.append(photo)

    if not geolocated_photos:
        st.info("Aucun souvenir géolocalisé pour le moment.")
        return

    trip_titles = sorted(
        {str(photo.get("title") or "Sans titre") for photo in geolocated_photos},
        key=str.casefold,
    )
    selected_titles = st.multiselect(
        "Filtrer par voyage",
        options=trip_titles,
        placeholder="Tous les voyages",
        help="Choisissez un ou plusieurs titres pour filtrer les lieux affichés. Videz la sélection pour tout réafficher.",
        key="map_trip_filter",
    )
    selected_photos = [
        photo
        for photo in geolocated_photos
        if not selected_titles
        or str(photo.get("title") or "Sans titre") in selected_titles
    ]

    grouped_locations: dict[tuple[float, float, str], list[dict[str, Any]]] = {}
    for photo in selected_photos:
        location = (
            float(photo["latitude"]),
            float(photo["longitude"]),
            _category_label(photo),
        )
        grouped_locations.setdefault(location, []).append(photo)

    if not grouped_locations:
        st.info("Aucun lieu ne correspond aux titres sélectionnés.")
        return

    center = [
        sum(latitude for latitude, _, _ in grouped_locations) / len(grouped_locations),
        sum(longitude for _, longitude, _ in grouped_locations) / len(grouped_locations),
    ]
    map_view = folium.Map(
        location=center,
        zoom_start=4,
        tiles=None,
        control_scale=True,
    )
    folium.TileLayer(
        tiles="CartoDB Voyager",
        name="Carte claire",
        overlay=False,
        control=True,
    ).add_to(map_view)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Tiles © Esri — Source: Esri, Maxar, Earthstar Geographics, and the GIS User Community",
        name="Vue satellite",
        overlay=False,
        control=True,
    ).add_to(map_view)
    marker_cluster = MarkerCluster(
        name="Souvenirs",
        show=True,
        options={"showCoverageOnHover": False, "zoomToBoundsOnClick": True},
    ).add_to(map_view)
    category_colors: dict[str, str] = {}
    fallback_colors = ["green", "purple", "orange", "cadetblue", "darkred", "darkgreen", "darkpurple", "pink", "gray", "darkblue"]
    fallback_color_index = 0
    for category in sorted({_category_label(photo) for photo in geolocated_photos}, key=str.casefold):
        normalized = "".join(
            char
            for char in unicodedata.normalize("NFKD", category).casefold()
            if not unicodedata.combining(char)
        )
        if "voyage" in normalized:
            category_colors[category] = "red"
        elif "travail" in normalized:
            category_colors[category] = "blue"
        elif normalized == "non classe":
            category_colors[category] = "gray"
        else:
            category_colors[category] = fallback_colors[fallback_color_index % len(fallback_colors)]
            fallback_color_index += 1

    for (latitude, longitude, category), grouped_photos in grouped_locations.items():
        place_name = next(
            (photo["location"] for photo in grouped_photos if photo.get("location")),
            "Lieu inconnu",
        )
        location_markup = html.escape(str(place_name))
        category_markup = html.escape(category)
        memories_markup = "".join(
            "<li>"
            f"<time>{html.escape(_format_date(photo.get('date_start') or photo.get('created_at')))}</time>"
            f" — {html.escape(photo.get('title') or 'Sans titre')}</li>"
            for photo in grouped_photos
        )
        popup_html = (
            f'<div style="min-width:220px"><strong>{location_markup}</strong>'
            f'<div style="color:#4b5563;font-size:.9em">{category_markup}</div>'
            f"<ul style=\"margin:8px 0 0;padding-left:20px\">{memories_markup}</ul></div>"
        )
        folium.Marker(
            location=[latitude, longitude],
            tooltip=f"{place_name} · {category} · {len(grouped_photos)} souvenir(s)",
            popup=folium.Popup(popup_html, max_width=260),
            icon=folium.Icon(
                color=category_colors[category],
                icon="map-marker",
                prefix="fa",
            ),
        ).add_to(marker_cluster)

    if len(grouped_locations) > 1:
        map_view.fit_bounds(
            [[latitude, longitude] for latitude, longitude, _ in grouped_locations],
            padding=(24, 24),
        )
    color_hex = {
        "red": "#d63b35", "blue": "#2d6ca2", "green": "#2e8b57",
        "purple": "#6f42a5", "orange": "#e87924", "cadetblue": "#5f9ea0",
        "darkred": "#8b0000", "darkgreen": "#006400", "darkpurple": "#4b0082",
        "pink": "#d66b9b", "gray": "#707070", "darkblue": "#17365d",
    }
    legend_markup = "".join(
        '<span style="display:inline-flex;align-items:center;gap:6px;white-space:nowrap">'
        f'<span style="width:12px;height:12px;border-radius:50%;background:{color_hex[category_colors[category]]}"></span>'
        f"{html.escape(category)}</span>"
        for category in sorted({_category_label(photo) for photo in selected_photos}, key=str.casefold)
    )
    st.markdown(
        '<div style="display:flex;flex-wrap:wrap;gap:12px;margin:.25rem 0 .75rem">'
        + legend_markup
        + "</div>",
        unsafe_allow_html=True,
    )
    folium.LayerControl(position="topright", collapsed=False).add_to(map_view)
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

    if st.button("\u270f\ufe0f Modifier un souvenir" if not st.session_state.get("admin_edit_mode") else "Retour a la creation", use_container_width=True):
        st.session_state.admin_edit_mode = not st.session_state.get("admin_edit_mode", False)
        st.rerun()
    if st.session_state.pop("photo_updated", False):
        st.success("Souvenir mis à jour avec succès !")

    if st.session_state.get("admin_edit_mode", False):
        st.subheader("Modifier un souvenir")
        try:
            editable_photos = get_photos("thibaut") + get_photos("clara")
        except RuntimeError as error:
            st.error(str(error))
            editable_photos = []

        if not editable_photos:
            st.info("Aucun souvenir a modifier.")
            st.stop()

        selected_photo = st.selectbox(
            "Souvenir a modifier",
            options=editable_photos,
            format_func=lambda item: f"{PROFILES.get(item.get('profile'), item.get('profile', ''))} - {item.get('title') or 'Sans titre'}",
            index=None,
            placeholder="Choisissez un souvenir",
            key="edit_photo_selection",
        )
        if selected_photo is None:
            st.stop()

        photo_id = selected_photo["id"]
        with st.form(f"edit_photo_form_{photo_id}"):
            edit_title = st.text_input("Titre / legende", value=selected_photo.get("title") or "", key=f"edit_{photo_id}_title")
            edit_category = st.text_input("Categorie", value=selected_photo.get("category") or "", key=f"edit_{photo_id}_category")
            edit_location = st.text_input("Lieu", value=selected_photo.get("location") or "", key=f"edit_{photo_id}_location")
            coord1, coord2 = st.columns(2)
            with coord1:
                try:
                    edit_latitude = float(selected_photo["latitude"]) if selected_photo.get("latitude") is not None else None
                except (TypeError, ValueError):
                    edit_latitude = None
                edit_latitude = st.number_input("Latitude", value=edit_latitude, min_value=-90.0, max_value=90.0, format="%.6f", key=f"edit_{photo_id}_latitude")
            with coord2:
                try:
                    edit_longitude = float(selected_photo["longitude"]) if selected_photo.get("longitude") is not None else None
                except (TypeError, ValueError):
                    edit_longitude = None
                edit_longitude = st.number_input("Longitude", value=edit_longitude, min_value=-180.0, max_value=180.0, format="%.6f", key=f"edit_{photo_id}_longitude")
            edit_start = st.date_input("Date de debut", value=_date_input_value(selected_photo.get("date_start")), format="DD/MM/YYYY", key=f"edit_{photo_id}_start")
            edit_end = st.date_input("Date de fin", value=_date_input_value(selected_photo.get("date_end")), format="DD/MM/YYYY", key=f"edit_{photo_id}_end")
            edit_content = st.text_area("Description", value=selected_photo.get("content") or "", key=f"edit_{photo_id}_content")
            edit_emoji = st.text_input("Emoji", value=selected_photo.get("emoji") or "", key=f"edit_{photo_id}_emoji")
            save_edit = st.form_submit_button("Enregistrer les modifications", type="primary", use_container_width=True)
        if save_edit:
            if edit_end and edit_start and edit_end < edit_start:
                st.error("La date de fin doit etre egale ou posterieure a la date de debut.")
            elif not edit_title.strip():
                st.error("Le titre est obligatoire.")
            else:
                try:
                    update_photo(photo_id=photo_id, values={
                        "title": edit_title.strip(), "category": edit_category.strip() or None,
                        "location": edit_location.strip() or None,
                        "latitude": edit_latitude, "longitude": edit_longitude,
                        "date_start": _date_as_utc_timestamp(edit_start),
                        "date_end": _date_as_utc_timestamp(edit_end),
                        "content": edit_content.strip() or None, "emoji": edit_emoji.strip() or None,
                    })
                    get_photos.clear()
                    get_map_photos.clear()
                    st.session_state.photo_updated = True
                    st.rerun()
                except RuntimeError as error:
                    st.error(str(error))
        st.stop()

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
