"""Point d'entrée de l'application Journal de voyage."""

import random

import streamlit as st

from src.views import (
    get_profile_from_query_params,
    render_calendar,
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
    .stApp {{
        background: linear-gradient(135deg, #2c1d11 0%, #1a110b 100%);
        color: #f4e8d8;
    }}
    [data-testid="stAppViewContainer"], [data-testid="stMain"] {{ background: transparent; }}
    [data-testid="stSidebar"] {{ background: rgba(44, 29, 17, .94); }}
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"],
    [data-testid="stSidebar"] label,
    [data-testid="stSidebar"] p {{ color: #f4e8d8; }}
    [data-testid="stSidebar"] [data-testid="stButton"] button {{
        background: #b45309;
        color: #fff;
        border: 0;
    }}
    .autumn-leaves {{
        position: fixed;
        inset: 0;
        width: 100vw;
        height: 100vh;
        overflow: hidden;
        pointer-events: none;
        z-index: 100;
        contain: paint;
    }}
    .autumn-leaf {{
        position: absolute;
        top: 0;
        width: var(--leaf-size);
        height: calc(var(--leaf-size) * .68);
        border-radius: 0 100% 0 100%;
        background: var(--leaf-color);
        opacity: .75;
        animation: autumn-fall var(--fall-duration) var(--fall-delay) linear infinite;
        will-change: transform;
    }}
    .autumn-leaf::after {{
        content: "";
        position: absolute;
        left: 18%;
        top: 50%;
        width: 72%;
        height: 1px;
        background: rgba(255, 230, 190, .65);
        transform: rotate(-24deg);
        transform-origin: left;
    }}
    @keyframes autumn-fall {{
        0% {{ transform: translate3d(0, -12vh, 0) rotate(0deg); opacity: 0; }}
        15% {{ opacity: .8; }}
        50% {{ transform: translate3d(var(--leaf-drift), 50vh, 0) rotate(180deg); }}
        100% {{ transform: translate3d(var(--leaf-drift-back), 112vh, 0) rotate(var(--leaf-rotation)); opacity: .15; }}
    }}
    @media (prefers-reduced-motion: reduce) {{ .autumn-leaves {{ display: none; }} }}
    [data-testid="stVerticalBlockBorderWrapper"], [data-testid="stForm"] {{
        background: rgba(35, 26, 20, .9);
        border: 1px solid rgba(236, 180, 120, .24);
        border-radius: 12px;
        padding: .75rem;
        margin-bottom: 1rem;
        box-shadow: 0 4px 12px rgba(0, 0, 0, .24);
    }}
    [data-testid="stVerticalBlockBorderWrapper"] h1,
    [data-testid="stVerticalBlockBorderWrapper"] h2,
    [data-testid="stVerticalBlockBorderWrapper"] h3,
    [data-testid="stVerticalBlockBorderWrapper"] p,
    [data-testid="stVerticalBlockBorderWrapper"] [data-testid="stCaptionContainer"],
    [data-testid="stForm"] label {{ color: #f4e8d8; }}
    [role="dialog"] {{
        color: #f4e8d8;
        background-color: #24170f;
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
        color: #f4e8d8 !important;
    }}
    [role="dialog"] [data-testid="stCaptionContainer"] {{ color: #d3c0ad !important; }}
    [data-testid="stAlert"] p,
    [data-testid="stAlert"] [data-testid="stMarkdownContainer"] {{
        color: #f4e8d8 !important;
    }}
    [data-testid="stButton"] button {{ border-radius: 10px; }}
    [data-testid="stSidebarCollapseButton"],
    [data-testid="stSidebarExpandButton"],
    [data-testid="stExpandSidebarButton"] {{
        width: auto;
        min-width: 2.5rem;
        padding: 0 0.65rem;
        gap: 0.4rem;
    }}
    [data-testid="stSidebarCollapseButton"] svg,
    [data-testid="stSidebarExpandButton"] svg,
    [data-testid="stExpandSidebarButton"] svg {{ display: none; }}
    [data-testid="stSidebarCollapseButton"]::after,
    [data-testid="stSidebarExpandButton"]::after,
    [data-testid="stExpandSidebarButton"]::after {{
        content: "Changer de vue & Filtres";
        white-space: nowrap;
    }}
    </style>
    """,
    unsafe_allow_html=True,
)

leaf_rng = random.Random()
leaf_colors = ["#b45309", "#d97706", "#9a3412", "#c2410c", "#a16207"]
autumn_leaves = []
for _ in range(12):
    fall_duration = leaf_rng.uniform(12, 23)
    autumn_leaves.append(
        '<span class="autumn-leaf" style="'
        f'left:{leaf_rng.randint(0, 100)}%;'
        f'--leaf-size:{leaf_rng.randint(14, 28)}px;'
        f'--fall-duration:{fall_duration:.1f}s;'
        f'--fall-delay:{leaf_rng.uniform(-fall_duration, 0):.1f}s;'
        f'--leaf-drift:{leaf_rng.randint(-90, 90)}px;'
        f'--leaf-drift-back:{leaf_rng.randint(-90, 90)}px;'
        f'--leaf-rotation:{leaf_rng.choice([-540, -360, 360, 540])}deg;'
        f'--leaf-color:{leaf_rng.choice(leaf_colors)}"></span>'
    )
st.markdown(
    f'<div class="autumn-leaves">{"".join(autumn_leaves)}</div>',
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
        [
            "\U0001F4D6 Le Journal",
            "\U0001F4C5 Calendrier",
            "\U0001F5FA\ufe0f Carte interactive",
            "\U0001F512 Espace Admin",
        ],
    )
    st.divider()
    render_profile_switch(profile)
    if page == "\U0001F4D6 Le Journal":
        gallery_photos = render_gallery_sidebar(profile)
    st.caption("Les souvenirs et aventures que nous partageons.")

if page == "\U0001F4D6 Le Journal":
    render_gallery(profile, gallery_photos)
elif page == "\U0001F4C5 Calendrier":
    render_calendar(profile)
elif page == "\U0001F5FA\ufe0f Carte interactive":
    render_map()
else:
    render_admin()