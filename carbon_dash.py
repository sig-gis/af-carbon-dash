import streamlit as st

home = st.Page("pages/0_home.py", title="🏠 Home")
project = st.Page("pages/1_project_builder.py", title="🌲 Project Builder")
faq = st.Page("pages/5_faq.py", title="❓ Frequently Asked Questions")
pg = st.navigation([
    home,
    project,
    faq,
])
st.set_page_config(page_title="American Forests Dashboard", page_icon="🌲")
pg.run()