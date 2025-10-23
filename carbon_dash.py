import streamlit as st

project = st.Page("pages/1_project_builder.py", title="🌲 Project Builder")
faq = st.Page("pages/5_faq.py", title="❓ Frequently Asked Questions")
cog = st.Page("pages/6_cog_test.py", title="TITILER COG TEST WITH PUBLIC SENTINEL-2 COG")
pg = st.navigation([
    # project,
    # faq,
    cog
])
st.set_page_config(page_title="American Forests Dashboard - COG TEST", page_icon="🌲")
pg.run()