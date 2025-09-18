import streamlit as st

home = st.Page("pages/0_home.py", title="🏠 Home")
project = st.Page("pages/1_5_map_planting.py", title="🌲 Project Builder")
pg = st.navigation([
    home,
    project,
])
st.set_page_config(page_title="American Forests Dashboard", page_icon="🌲")
pg.run()