import os
import streamlit as st

project = st.Page("pages/1_project_builder.py", title="🌲 Project Builder")
faq = st.Page("pages/2_faq.py", title="❓ Frequently Asked Questions")

pages = [project, faq]
if os.environ.get("ENV") != "production":
    admin = st.Page("pages/3_admin.py", title="⚙️ Model Management")
    pages.append(admin)

pg = st.navigation(pages)
st.set_page_config(page_title="American Forests Dashboard", page_icon="🌲")
pg.run()