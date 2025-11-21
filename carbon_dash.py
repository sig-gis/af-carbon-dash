import streamlit as st

project = st.Page("pages/1_project_builder.py", title="🌲 Project Builder")
faq = st.Page("pages/2_faq.py", title="❓ Frequently Asked Questions")
pg = st.navigation([
    project,
    faq,
])
st.set_page_config(page_title="American Forests Dashboard", page_icon="🌲")
pg.run()