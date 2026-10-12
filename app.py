"""Point d'entrée de l'application Journal de voyage."""

import streamlit as st

from src.views import (
    get_profile_from_query_params,
    render_admin,
    render_gallery,
    render_gallery_sidebar,
    render_map,
    render_profile_selector_dialog,
    render_profile_switch,
)

st.set_page_config(
    page_title="Journal l'aventure Canadienne",
    page_icon="📖",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    f"""
    <style>
    [data-testid="stVerticalBlockBorderWrapper"], [data-testid="stForm"] {{
        background: rgba(255, 255, 255, .82);
        border: 1px solid rgba(31, 41, 55, .2);
        border-radius: 12px;
        padding: .75rem;
        margin-bottom: 1rem;
        box-shadow: 0 4px 6px rgba(0, 0, 0, .1);
    }}
    [data-testid="stVerticalBlockBorderWrapper"] h1,
    [data-testid="stVerticalBlockBorderWrapper"] h2,
    [data-testid="stVerticalBlockBorderWrapper"] h3,
    [data-testid="stVerticalBlockBorderWrapper"] p,
    [data-testid="stVerticalBlockBorderWrapper"] [data-testid="stCaptionContainer"],
    [data-testid="stForm"] label {{ color: #1f2937; }}
    [role="dialog"] {{
        color: #1f2937;
        background-color: #ffffff;
        border-radius: 14px;
    }}
    [role="dialog"] h1,
    [role="dialog"] h2,
    [role="dialog"] h3,
    [role="dialog"] h4,
    [role="dialog"] p,
    [role="dialog"] label,
    [role="dialog"] [data-testid="stMarkdownContainer"],
    [role="dialog"] [data-testid="stCaptionContainer"] {{
        color: #1f2937 !important;
    }}
    [role="dialog"] [data-testid="stCaptionContainer"] {{ color: #4b5563 !important; }}
    [data-testid="stAlert"] p,
    [data-testid="stAlert"] [data-testid="stMarkdownContainer"] {{
        color: #1f2937 !important;
    }}
    [data-testid="stButton"] button {{ border-radius: 10px; }}
    </style>
    """,
    unsafe_allow_html=True,
)

profile = get_profile_from_query_params()
if profile is None:
    render_profile_selector_dialog()
    st.stop()

with st.sidebar:
    st.title("Journal familial")
    page = st.radio(
        "Navigation",
        ["📖 Le Journal", "🗺️ Carte interactive", "🔒 Espace Admin"],
    )
    st.divider()
    render_profile_switch(profile)
    if page == "📖 Le Journal":
        gallery_photos = render_gallery_sidebar(profile)
    st.caption("Les souvenirs et aventures que nous partageons.")

if page == "📖 Le Journal":
    render_gallery(profile, gallery_photos)
elif page == "🗺️ Carte interactive":
    render_map()
else:
    render_admin()
