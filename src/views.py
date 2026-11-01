"""Composants d'interface Streamlit du journal et de son administration."""

from __future__ import annotations

import hmac
import html
import json
import unicodedata
import calendar as calendar_module
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
CATEGORY_COLOR_HEX = {
    "red": "#d63b35", "blue": "#2d6ca2", "green": "#2e8b57",
    "purple": "#6f42a5", "orange": "#e87924", "cadetblue": "#5f9ea0",
    "darkred": "#8b0000", "darkgreen": "#006400", "darkpurple": "#4b0082",
    "pink": "#d66b9b", "gray": "#707070", "darkblue": "#17365d",
}
CATEGORY_FALLBACK_COLORS = (
    "green", "purple", "orange", "cadetblue", "darkred", "darkgreen",
    "darkpurple", "pink", "gray", "darkblue",
)


def _category_label(photo: dict[str, Any]) -> str:
    return str(photo.get("category") or "Non classé").strip() or "Non classé"


def _category_marker_color(category: str) -> str:
    """Retourne une couleur stable partagÃ©e par les marqueurs de carte et frise."""
    normalized = "".join(
        char
        for char in unicodedata.normalize("NFKD", category).casefold()
        if not unicodedata.combining(char)
    )
    if "voyage" in normalized:
        return "red"
    if "travail" in normalized:
        return "blue"
    if normalized == "non classe":
        return "gray"
    color_index = sum((index + 1) * ord(char) for index, char in enumerate(normalized))
    return CATEGORY_FALLBACK_COLORS[color_index % len(CATEGORY_FALLBACK_COLORS)]


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
    st.markdown(
        """
        **🧭 Le mode d'emploi (version courte, promis !) **

        - **📖 Journal** : lisez les cartes, ouvrez les galeries, glissez pour défiler et pincez pour zoomer. La frise vous dépose pile sur le souvenir (téléportation sans DeLorean 🚗).
        - **📅 Calendrier** : sautez de mois en mois et survolez les jours avec photo pour découvrir leurs secrets. Pas de rendez-vous chez l'ophtalmo requis 👀
        - **🗺️ Carte** : filtrez les voyages, cliquez sur les marqueurs, zoomez et passez en satellite. Boussole facultative 😉
        - **🛠️ Espace Admin** : les coulisses pour ajouter, modifier ou supprimer des souvenirs. Attention, pouvoir de rangement 🧹
        """
    )
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
    """Ouvre une galerie adaptée au bureau et au mobile, avec zoom tactile."""
    @st.dialog("Galerie photo", width="large")
    def render_contents() -> None:
        photo_images = _photo_images(photo)
        if not photo_images:
            return

        st.markdown(
            """
            <style>
              div[data-testid="stDialog"] div[role="dialog"] {
                box-sizing: border-box !important;
                position: fixed !important;
                inset: 0 !important;
                width: 100vw !important;
                max-width: 100vw !important;
                height: 100dvh !important;
                max-height: 100dvh !important;
                margin: 0 !important;
                padding: 0 !important;
                border-radius: 0 !important;
                background: #080a10 !important;
                overflow: hidden !important;
                transform: none !important;
              }
              div[data-testid="stDialog"] div[role="dialog"] h2 {
                position: fixed !important;
                top: max(env(safe-area-inset-top), 1rem) !important;
                left: max(env(safe-area-inset-left), 1rem) !important;
                z-index: 10000 !important;
                margin: 0 !important;
                color: #fff !important;
                font-size: 1.25rem !important;
              }
              div[data-testid="stDialog"] div[role="dialog"] iframe {
                position: fixed !important;
                inset: 0 !important;
                width: 100vw !important;
                max-width: 100vw !important;
                height: 100dvh !important;
                max-height: 100dvh !important;
                border: 0 !important;
                z-index: 10 !important;
              }
              div[data-testid="stDialog"] div[role="dialog"] button[aria-label="Close"],
              div[data-testid="stDialog"] div[role="dialog"] button[aria-label="Fermer"] {
                position: fixed !important;
                top: max(env(safe-area-inset-top), .75rem) !important;
                right: max(env(safe-area-inset-right), .75rem) !important;
                z-index: 10001 !important;
                width: 2.75rem !important;
                height: 2.75rem !important;
                border: 1px solid rgba(255,255,255,.35) !important;
                border-radius: 50% !important;
                color: #fff !important;
                background: rgba(30,30,30,.72) !important;
                backdrop-filter: blur(8px);
              }
            </style>
            """,
            unsafe_allow_html=True,
        )

        gallery_key = f"photo_gallery_index_{photo['id']}"
        st.session_state.setdefault(gallery_key, 0)
        initial_index = st.session_state[gallery_key] % len(photo_images)
        image_urls = json.dumps(photo_images).replace("<", "\\u003c")
        gallery_html = r"""
        <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
        <style>
          html, body { width:100%; height:100%; margin:0; padding:0; overflow:hidden; background:#080a10; }
          .gallery-controls { position:absolute; inset:0; z-index:2; pointer-events:none; }
          .gallery-controls button {
            position:absolute; top:50%; transform:translateY(-50%);
            width:3rem; height:3rem; border:1px solid rgba(255,255,255,.3);
            border-radius:50%; color:white; background:rgba(35,35,35,.68);
            font-size:1.7rem; cursor:pointer; pointer-events:auto; backdrop-filter:blur(8px);
          }
          #previous { left:max(env(safe-area-inset-left), .75rem); }
          #next { right:max(env(safe-area-inset-right), .75rem); }
          .viewer {
            position:absolute; inset:0; width:100vw; height:100dvh;
            display:flex; align-items:center; justify-content:center;
            overflow:hidden; background:#080a10; touch-action:none;
            user-select:none; -webkit-user-select:none;
          }
          .viewer::before {
            content:""; position:absolute; inset:-32px; z-index:0;
            background-image:var(--photo-background); background-size:cover; background-position:center;
            filter:blur(28px) brightness(.42); opacity:.72; transform:scale(1.06);
          }
          .viewer img {
            position:relative; z-index:1; display:block; object-fit:contain;
            max-width:100%; max-height:100%; transform-origin:center center;
            will-change:transform; pointer-events:none; -webkit-user-drag:none;
            box-shadow:0 12px 48px rgba(0,0,0,.32);
          }
          @media (min-width: 701px) {
            .viewer img { max-width:min(72vw, 1100px); max-height:72vh; }
          }
          @media (max-width: 700px) {
            .viewer img { max-width:96vw; max-height:88dvh; }
            .gallery-controls button { width:2.75rem; height:2.75rem; }
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
          function fitImage() {
            if (!photo.naturalWidth || !photo.naturalHeight) return;
            const mobile = window.matchMedia("(max-width: 700px)").matches;
            const maxHeight = window.innerHeight * (mobile ? 0.88 : 0.72);
            const maxWidth = mobile ? viewer.clientWidth * 0.96 : Math.min(viewer.clientWidth * 0.72, 1100);
            const ratio = photo.naturalWidth / photo.naturalHeight;
            const width = Math.min(maxWidth, maxHeight * ratio);
            photo.style.width = `${width}px`;
            photo.style.height = `${width / ratio}px`;
          }
          function draw() {
            photo.src = images[index];
            viewer.style.setProperty("--photo-background", `url("${images[index]}")`);
            photo.style.transform = `translate(${offsetX}px, ${offsetY}px) scale(${scale})`;
          }
          photo.addEventListener("load", fitImage);
          window.addEventListener("resize", fitImage);
          function changePhoto(step) {
            index = (index + step + images.length) % images.length;
            scale = 1; offsetX = 0; offsetY = 0; draw();
          }
          document.getElementById("previous").addEventListener("click", () => changePhoto(-1));
          document.getElementById("next").addEventListener("click", () => changePhoto(1));
          function clampPan() {
            const maxX = photo.clientWidth * (scale - 1) / 2;
            const maxY = photo.clientHeight * (scale - 1) / 2;
            offsetX = clamp(offsetX, -maxX, maxX);
            offsetY = clamp(offsetY, -maxY, maxY);
          }
          viewer.addEventListener("pointerdown", event => {
            event.preventDefault();
            viewer.setPointerCapture(event.pointerId);
            pointers.set(event.pointerId, {x:event.clientX, y:event.clientY});
            if (pointers.size === 2) {
              const pair = [...pointers.values()];
              gesture = {mode:"pinch", startDistance:distance(pair[0], pair[1]), startScale:scale};
            } else {
              gesture = {mode:"single", startX:event.clientX, startY:event.clientY,
                startOffsetX:offsetX, startOffsetY:offsetY};
            }
          });
          viewer.addEventListener("pointermove", event => {
            if (!pointers.has(event.pointerId)) return;
            pointers.set(event.pointerId, {x:event.clientX, y:event.clientY});
            if (pointers.size >= 2 && gesture?.mode === "pinch") {
              const pair = [...pointers.values()];
              scale = clamp(gesture.startScale * distance(pair[0], pair[1]) / gesture.startDistance, 1, 4);
              if (scale === 1) { offsetX = 0; offsetY = 0; }
              clampPan(); photo.style.transform = `translate(${offsetX}px, ${offsetY}px) scale(${scale})`;
            } else if (pointers.size === 1 && gesture?.mode === "single" && scale > 1) {
              offsetX = gesture.startOffsetX + event.clientX - gesture.startX;
              offsetY = gesture.startOffsetY + event.clientY - gesture.startY;
              clampPan(); photo.style.transform = `translate(${offsetX}px, ${offsetY}px) scale(${scale})`;
            }
          });
          function endPointer(event) {
            const priorGesture = gesture;
            pointers.delete(event.pointerId);
            if (pointers.size === 1) {
              const remaining = [...pointers.values()][0];
              gesture = {mode:"single", startX:remaining.x, startY:remaining.y,
                startOffsetX:offsetX, startOffsetY:offsetY};
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
              clampPan(); photo.style.transform = `translate(${offsetX}px, ${offsetY}px) scale(${scale})`;
              lastTap = 0;
            } else lastTap = now;
          });
          draw();
        </script>
        """
        gallery_html = gallery_html.replace("__IMAGES__", image_urls).replace("__INDEX__", str(initial_index))
        st.components.v1.html(gallery_html, height=900, scrolling=False)

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
    _render_journal_timeline(photos)
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
                preview_image = _photo_preview(photo)
                if preview_image:
                    st.image(preview_image, use_container_width=True)
                else:
                    st.caption("📷 Pas de photo cette fois — le souvenir compte quand même !")
                if _photo_images(photo):
                    if st.button(
                        "\U0001F4F7 Voir les photos",
                        key=f"view_photos_{photo['id']}",
                        use_container_width=True,
                    ):
                        _show_photo_dialog(photo)


def _photo_calendar_date(value: str | None) -> date | None:
    """Convertit une date de souvenir ou un horodatage en date de calendrier."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except (AttributeError, TypeError, ValueError):
        return None


def _render_journal_timeline(photos: list[dict[str, Any]]) -> None:
    """Affiche une frise dont les marqueurs font défiler le journal jusqu'aux cartes."""
    items = []
    for photo in photos:
        event_day = _photo_calendar_date(
            photo.get("date_end") or photo.get("date_start") or photo.get("created_at")
        )
        if event_day is not None:
            items.append((event_day, photo))
    items.sort(key=lambda item: (item[0], str(item[1].get("title") or "").casefold()))
    if not items:
        return

    first_date, last_date = items[0][0], items[-1][0]
    span = max(1, (last_date - first_date).days)
    months = []
    cursor = date(first_date.year, first_date.month, 1)
    last_month = date(last_date.year, last_date.month, 1)
    while cursor <= last_month:
        months.append(cursor)
        next_month = cursor.month + 1
        cursor = date(cursor.year + (next_month > 12), 1 if next_month > 12 else next_month, 1)

    width = max(760, len(items) * 90 + 80, len(months) * 110 + 80)
    month_names = (
        "janv.", "févr.", "mars", "avr.", "mai", "juin",
        "juil.", "août", "sept.", "oct.", "nov.", "déc.",
    )
    ticks = []
    for index, month in enumerate(months):
        fraction = 0.5 if first_date == last_date else min(
            1, max(0, (month - first_date).days / span)
        )
        left = (40 + fraction * (width - 80)) / width * 100
        edge = "timeline-first" if index == 0 else "timeline-last" if index == len(months) - 1 else ""
        ticks.append(
            f'<div class="journal-timeline-tick {edge}" style="left:{left:.3f}%">'
            f'<span>{month_names[month.month - 1]} {month.year}</span></div>'
        )

    day_counts: dict[date, int] = {}
    day_seen: dict[date, int] = {}
    for event_day, _ in items:
        day_counts[event_day] = day_counts.get(event_day, 0) + 1
    markers = []
    for index, (event_day, photo) in enumerate(items):
        seen = day_seen.get(event_day, 0)
        day_seen[event_day] = seen + 1
        fraction = (event_day - first_date).days / span if span > 1 else 0.5
        offset = (seen - (day_counts[event_day] - 1) / 2) * 12
        left = (40 + fraction * (width - 80) + offset) / width * 100
        title = html.escape(photo.get("title") or "Sans titre")
        category = html.escape(photo.get("category") or "Non classé")
        location = html.escape(photo.get("location") or "Lieu non précisé")
        memory_id = html.escape(str(photo["id"]), quote=True)
        marker_color = CATEGORY_COLOR_HEX[
            _category_marker_color(str(photo.get("category") or "Non classé"))
        ]
        lane = "lower" if seen % 2 else "upper"
        edge = "first" if index == 0 else "last" if index == len(items) - 1 else ""
        markers.append(
            f'<a class="journal-timeline-marker {lane} {edge}" '
            f'href="#photo-{memory_id}" style="left:{left:.3f}%;--marker-color:{marker_color}" '
            f'aria-label="Voir {title}, {event_day.strftime("%d/%m/%Y")}">'
            '<span class="journal-timeline-dot"></span>'
            f'<span class="journal-timeline-tooltip"><strong>{title}</strong>'
            f'<br>{category} · {location}<br>{event_day.strftime("%d/%m/%Y")}</span></a>'
        )

    st.subheader("Frise chronologique")
    st.caption(
        "🕰️ Survolez un repère pour les détails, cliquez pour atterrir pile sur le souvenir "
        "(téléportation, sans remonter toute la page !), puis faites défiler pour voyager dans le temps."
    )
    st.markdown(
        f"""
        <style>
          .journal-timeline-scroll {{ overflow-x:auto; overflow-y:hidden; padding:1rem 0; }}
          .journal-timeline-content {{ position:relative; width:{width}px; height:280px; }}
          .journal-timeline-track {{ position:relative; height:240px; }}
          .journal-timeline-rail {{ position:absolute; left:40px; right:40px; top:112px; height:4px;
            border-radius:4px; background:#d1d5db; }}
          .journal-timeline-marker {{ position:absolute; z-index:1; top:112px; width:0; height:0; color:inherit; }}
          .journal-timeline-dot {{ position:absolute; left:-8px; top:-7px; width:16px; height:16px;
            border:3px solid white; border-radius:50%; background:var(--marker-color,#ef4444);
            box-shadow:0 0 0 2px var(--marker-color,#ef4444); cursor:pointer; }}
          .journal-timeline-tooltip {{ position:absolute; left:0; display:none; width:190px; padding:.55rem;
            border-radius:8px; color:white; background:#1f2937; font-size:.78rem; line-height:1.4;
            overflow-wrap:anywhere; text-decoration:none; box-shadow:0 4px 12px #0003; transform:translateX(-50%); }}
          .journal-timeline-marker.upper .journal-timeline-tooltip {{ bottom:16px; }}
          .journal-timeline-marker.lower .journal-timeline-tooltip {{ top:16px; }}
          .journal-timeline-marker.first .journal-timeline-tooltip {{ left:0; transform:none; }}
          .journal-timeline-marker.last .journal-timeline-tooltip {{ left:auto; right:0; transform:none; }}
          .journal-timeline-marker:hover, .journal-timeline-marker:focus {{ z-index:5; }}
          .journal-timeline-marker:hover .journal-timeline-tooltip,
          .journal-timeline-marker:focus .journal-timeline-tooltip {{ display:block; }}
          .journal-timeline-tick {{ position:absolute; z-index:0; top:104px; height:28px; width:1px; background:#9ca3af; }}
          .journal-timeline-tick span {{ position:absolute; top:34px; left:50%; white-space:nowrap;
            color:#4b5563; font-size:.78rem; transform:translateX(-50%); }}
          .journal-timeline-tick.timeline-first span {{ left:0; transform:none; }}
          .journal-timeline-tick.timeline-last span {{ left:auto; right:0; transform:none; }}
          .journal-timeline-dates {{ display:flex; justify-content:space-between; padding:0 20px;
            color:#4b5563; font-size:.85rem; }}
          @media (max-width:700px) {{ .journal-timeline-tooltip {{ width:155px; font-size:.7rem; }} }}
        </style>
        <div class="journal-timeline-scroll"><div class="journal-timeline-content">
          <div class="journal-timeline-track"><div class="journal-timeline-rail"></div>
            {''.join(ticks)}{''.join(markers)}</div>
          <div class="journal-timeline-dates"><span>Première date : {first_date.strftime("%d/%m/%Y")}</span>
            <span>Dernière date : {last_date.strftime("%d/%m/%Y")}</span></div>
        </div></div>
        """,
        unsafe_allow_html=True,
    )


def render_calendar(profile: str) -> None:
    """Affiche les souvenirs d'un journal dans un calendrier mensuel."""
    st.title(f"📅 Calendrier de {PROFILES[profile]}")

    try:
        photos = get_photos(profile)
    except RuntimeError as error:
        st.error(str(error))
        return

    month_key = f"calendar_month_{profile}"
    st.session_state.setdefault(month_key, date.today().replace(day=1))
    displayed_month = st.session_state[month_key]
    previous, month_label, following = st.columns([1, 5, 1])
    with previous:
        if st.button("←", key=f"calendar_previous_{profile}", help="Mois précédent"):
            year, month = displayed_month.year, displayed_month.month - 1
            if month == 0:
                year, month = year - 1, 12
            st.session_state[month_key] = date(year, month, 1)
            st.rerun()
    with month_label:
        month_names = (
            "janvier", "février", "mars", "avril", "mai", "juin",
            "juillet", "août", "septembre", "octobre", "novembre", "décembre",
        )
        st.subheader(f"{month_names[displayed_month.month - 1].capitalize()} {displayed_month.year}")
    with following:
        if st.button("→", key=f"calendar_next_{profile}", help="Mois suivant"):
            year, month = displayed_month.year, displayed_month.month + 1
            if month == 13:
                year, month = year + 1, 1
            st.session_state[month_key] = date(year, month, 1)
            st.rerun()

    memories_by_day: dict[date, list[dict[str, Any]]] = {}
    for photo in photos:
        event_day = _photo_calendar_date(
            photo.get("date_end") or photo.get("date_start") or photo.get("created_at")
        )
        if event_day is None or event_day.month != displayed_month.month or event_day.year != displayed_month.year:
            continue
        memories_by_day.setdefault(event_day, []).append(photo)

    weekday_headers = "".join(
        f'<div class="calendar-weekday">{name}</div>'
        for name in ("Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim")
    )
    first_weekday, days_in_month = calendar_module.monthrange(
        displayed_month.year, displayed_month.month
    )
    cells: list[str] = []
    for day_number in range(1, days_in_month + 1):
        current_day = date(displayed_month.year, displayed_month.month, day_number)
        day_memories = memories_by_day.get(current_day, [])
        memory = day_memories[0] if day_memories else None
        image = _photo_preview(memory) if memory else ""
        safe_image = html.escape(image, quote=True)
        cell_styles = []
        if day_number == 1:
            cell_styles.append(f"grid-column-start:{first_weekday + 1}")
        if image:
            cell_styles.append(f"--memory-image: url('{safe_image}')")
        cell_style = f' style="{";".join(cell_styles)}"' if cell_styles else ""
        today_class = " calendar-day-today" if current_day == date.today() else ""
        if memory:
            title = html.escape(memory.get("title") or "Sans titre")
            category = html.escape(memory.get("category") or "Non classé")
            location = html.escape(memory.get("location") or "Lieu non précisé")
            extra = f'<span class="calendar-extra">{category}<br>{location}</span>'
            count = (
                f'<span class="calendar-count">+{len(day_memories) - 1}</span>'
                if len(day_memories) > 1 else ""
            )
            details = f'<span class="calendar-title">{title}</span>{extra}{count}'
            image_class = "" if image else " calendar-day-memory-no-image"
            cells.append(
                f'<div class="calendar-day calendar-day-memory{image_class}{today_class}"{cell_style}>'
                f'<span class="calendar-number">{day_number}</span>'
                f'<div class="calendar-details">{details}</div></div>'
            )
        else:
            cells.append(
                f'<div class="calendar-day calendar-day-no-memory{today_class}"{cell_style}>'
                f'<span class="calendar-number">{day_number}</span></div>'
            )

    st.markdown(
        """
        <style>
          .memory-calendar { display:grid; grid-template-columns:repeat(7,minmax(0,1fr)); gap:.4rem; }
          .calendar-weekday { text-align:center; font-weight:700; padding:.45rem 0; color:#374151; }
          .calendar-day { position:relative; min-width:0; aspect-ratio:1.12; overflow:hidden;
            border-radius:10px; background:#e5e7eb; }
          .calendar-day-empty { background:#f4f3f7; }
          .calendar-day-no-memory { background:#e9e8f1; border:1px solid #d8d7e3; }
          .calendar-day-memory { color:white; background-image:linear-gradient(180deg,rgba(0,0,0,.2),rgba(0,0,0,.08) 40%,rgba(0,0,0,.78)),var(--memory-image);
            background-size:cover; background-position:center; }
          .calendar-day-memory-no-image { background:#7b8798; }
          .calendar-number { position:absolute; z-index:1; top:.35rem; left:.45rem; font-weight:700;
            text-shadow:0 1px 4px #000; }
          .calendar-details { position:absolute; inset:auto 0 0; display:flex; flex-direction:column; gap:.15rem;
            padding:.45rem; font-size:.78rem; line-height:1.2; overflow-wrap:anywhere; }
          .calendar-title { font-weight:700; }
          .calendar-extra { max-height:0; opacity:0; overflow:hidden; transition:max-height .2s,opacity .2s; }
          .calendar-day-memory:hover .calendar-extra,
          .calendar-day-memory:focus-within .calendar-extra { max-height:4rem; opacity:1; }
          .calendar-count { position:absolute; right:.4rem; top:.35rem; padding:.15rem .35rem;
            border-radius:1rem; background:rgba(0,0,0,.65); font-size:.7rem; }
          .calendar-day-today { outline:3px solid #ef4444; outline-offset:-3px; }
          @media (max-width:700px) {
            .memory-calendar { gap:.2rem; }
            .calendar-day { aspect-ratio:.78; border-radius:6px; }
            .calendar-weekday { font-size:.72rem; }
            .calendar-number { top:.2rem; left:.25rem; font-size:.78rem; }
            .calendar-details { padding:.25rem; font-size:.62rem; }
            .calendar-day-memory .calendar-extra { max-height:4rem; opacity:1; }
            .calendar-count { right:.2rem; top:.2rem; font-size:.62rem; }
          }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div class="memory-calendar">{weekday_headers}{"".join(cells)}</div>',
        unsafe_allow_html=True,
    )

    timeline_items = []
    for photo in photos:
        event_day = _photo_calendar_date(
            photo.get("date_end") or photo.get("date_start") or photo.get("created_at")
        )
        if event_day is not None:
            timeline_items.append((event_day, photo))
    timeline_items.sort(key=lambda item: (item[0], str(item[1].get("title") or "").casefold()))

    st.subheader("Frise chronologique")
    st.caption("🕵️ Chaque marqueur = un souvenir. Survolez-le pour son titre, sa catégorie, son lieu et sa date; la frise fait le guide touristique !")
    if not timeline_items:
        st.caption("La frise apparaîtra dès qu’un souvenir aura une date.")
    else:
        first_date = timeline_items[0][0]
        last_date = timeline_items[-1][0]
        date_span = max(1, (last_date - first_date).days)
        month_ticks: list[date] = []
        month_cursor = date(first_date.year, first_date.month, 1)
        final_month = date(last_date.year, last_date.month, 1)
        while month_cursor <= final_month:
            month_ticks.append(month_cursor)
            next_month = month_cursor.month + 1
            month_cursor = date(
                month_cursor.year + (next_month > 12),
                1 if next_month > 12 else next_month,
                1,
            )
        track_width = max(760, len(timeline_items) * 90 + 80, len(month_ticks) * 110 + 80)
        same_day_counts: dict[date, int] = {}
        for event_day, _ in timeline_items:
            same_day_counts[event_day] = same_day_counts.get(event_day, 0) + 1
        same_day_seen: dict[date, int] = {}
        markers = []
        for item_index, (event_day, photo) in enumerate(timeline_items):
            fraction = (event_day - first_date).days / date_span if date_span > 1 else 0.5
            same_day_index = same_day_seen.get(event_day, 0)
            same_day_seen[event_day] = same_day_index + 1
            same_day_offset = (same_day_index - (same_day_counts[event_day] - 1) / 2) * 12
            left_percent = (
                40 + fraction * (track_width - 80) + same_day_offset
            ) / track_width * 100
            title = html.escape(photo.get("title") or "Sans titre")
            category = html.escape(photo.get("category") or "Non classé")
            location = html.escape(photo.get("location") or "Lieu non précisé")
            marker_date = html.escape(event_day.strftime("%d/%m/%Y"))
            marker_color = CATEGORY_COLOR_HEX[
                _category_marker_color(str(photo.get("category") or "Non classé"))
            ]
            lane = "timeline-marker-lower" if same_day_index % 2 else "timeline-marker-upper"
            edge = "timeline-marker-first" if item_index == 0 else (
                "timeline-marker-last" if item_index == len(timeline_items) - 1 else ""
            )
            markers.append(
                f'<div class="timeline-marker {lane} {edge}" '
                f'style="left:{left_percent:.3f}%;--marker-color:{marker_color}">'
                '<span class="timeline-dot"></span>'
                f'<span class="timeline-tooltip"><strong>{title}</strong>'
                f'<br>{category} · {location}<br>{marker_date}</span></div>'
            )
        ticks = []
        short_month_names = (
            "janv.", "févr.", "mars", "avr.", "mai", "juin",
            "juil.", "août", "sept.", "oct.", "nov.", "déc.",
        )
        for index, tick_date in enumerate(month_ticks):
            fraction = (
                0.5 if first_date == last_date else
                min(1, max(0, (tick_date - first_date).days / date_span))
            )
            left_percent = (40 + fraction * (track_width - 80)) / track_width * 100
            edge = "timeline-tick-first" if index == 0 else (
                "timeline-tick-last" if index == len(month_ticks) - 1 else ""
            )
            label = f"{short_month_names[tick_date.month - 1]} {tick_date.year}"
            ticks.append(
                f'<div class="timeline-tick {edge}" style="left:{left_percent:.3f}%">'
                f'<span>{label}</span></div>'
            )
        start_label = html.escape(first_date.strftime("%d/%m/%Y"))
        end_label = html.escape(last_date.strftime("%d/%m/%Y"))
        st.markdown(
            f"""
            <style>
              .timeline-scroll {{ overflow-x:auto; overflow-y:hidden; padding:1rem 0; }}
              .timeline-content {{ position:relative; height:280px; }}
              .timeline-track {{ position:relative; height:240px; }}
              .timeline-rail {{ position:absolute; left:40px; right:40px; top:112px; height:4px;
                border-radius:4px; background:#d1d5db; }}
              .timeline-marker {{ position:absolute; z-index:1; top:112px; width:0; height:0; }}
              .timeline-dot {{ position:absolute; left:-8px; top:-7px; width:16px; height:16px;
                border:3px solid white; border-radius:50%; background:var(--marker-color,#ef4444);
                box-shadow:0 0 0 2px var(--marker-color,#ef4444); cursor:pointer; }}
              .timeline-tooltip {{ position:absolute; left:0; display:none; width:190px; padding:.5rem;
                border-radius:8px; color:white; background:#1f2937; font-size:.78rem; line-height:1.35;
                overflow-wrap:anywhere; box-shadow:0 4px 12px #0003; transform:translateX(-50%); }}
              .timeline-marker-upper .timeline-tooltip {{ bottom:16px; }}
              .timeline-marker-lower .timeline-tooltip {{ top:16px; }}
              .timeline-marker-first .timeline-tooltip {{ left:0; transform:none; }}
              .timeline-marker-last .timeline-tooltip {{ left:auto; right:0; transform:none; }}
              .timeline-marker:hover {{ z-index:5; }}
              .timeline-marker:hover .timeline-tooltip {{ display:block; }}
              .timeline-tick {{ position:absolute; z-index:0; top:104px; height:28px; width:1px;
                background:#9ca3af; }}
              .timeline-tick span {{ position:absolute; top:34px; left:50%; white-space:nowrap;
                color:#4b5563; font-size:.78rem; transform:translateX(-50%); }}
              .timeline-tick-first span {{ left:0; transform:none; }}
              .timeline-tick-last span {{ left:auto; right:0; transform:none; }}
              .timeline-endpoints {{ display:flex; justify-content:space-between; gap:1rem;
                padding:0 20px; color:#4b5563; font-size:.85rem; }}
              @media (max-width:700px) {{ .timeline-tooltip {{ width:155px; font-size:.7rem; }} }}
            </style>
            <div class="timeline-scroll"><div class="timeline-content" style="width:{track_width}px">
              <div class="timeline-track"><div class="timeline-rail"></div>{''.join(ticks)}{''.join(markers)}</div>
              <div class="timeline-endpoints"><span>Première date : {start_label}</span>
                <span>Dernière date : {end_label}</span></div>
            </div></div>
            """,
            unsafe_allow_html=True,
        )


def render_map() -> None:
    """Affiche sur une carte les souvenirs de tous les profils géolocalisés."""
    st.title("🗺️ Carte interactive")
    try:
        photos = get_map_photos()
    except RuntimeError as error:
        st.error(str(error))
        return

    st.caption(
        "🔎 Zoomez et dézoomez pour explorer les lieux, cliquez sur un marqueur pour découvrir les souvenirs associés, "
        "puis filtrez par voyage ou passez en satellite. Promis, la carte ne mord pas 😉"
    )
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
    category_colors = {
        category: _category_marker_color(category)
        for category in {_category_label(photo) for photo in geolocated_photos}
    }

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
    legend_markup = "".join(
        '<span style="display:inline-flex;align-items:center;gap:6px;white-space:nowrap">'
        f'<span style="width:12px;height:12px;border-radius:50%;background:{CATEGORY_COLOR_HEX[category_colors[category]]}"></span>'
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
                    preview_image = _photo_preview(photo)
                    if preview_image:
                        st.image(preview_image, use_container_width=True)
                    else:
                        st.caption("Aucune photo")
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
        "Photo principale (facultative)",
        type=["jpg", "jpeg", "png", "webp"],
        key="photo_preview_upload",
    )
    uploaded_files = st.file_uploader(
        "Photos du souvenir (facultatif — ajoutez-en une ou plusieurs)",
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
            preview_url = None
            if preview_file is not None:
                compressed_preview = compress_image(preview_file)
                preview_url = upload_image(
                    compressed_preview.getvalue(), label="la photo principale"
                )
            photo_urls = []
            for index, uploaded_file in enumerate(uploaded_files or [], start=1):
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
