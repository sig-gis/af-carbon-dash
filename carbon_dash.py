import streamlit as st

home = st.Page("pages/0_home.py", title="🏠 Home")
planting = st.Page("pages/1_planting.py", title="🌲 Planting Scenario")
carbon_est = st.Page("pages/2_carbon_est.py", title="📈 Carbon Units Estimate")
credits = st.Page("pages/3_credits.py", title="📈 Credits")
maps = st.Page("pages/1_5_map_planting.py", title="🌲 Project Builder")
pg = st.navigation([
    home,
    maps,
    # planting,
    # carbon_est,
    credits
])
st.set_page_config(page_title="American Forests Dashboard", page_icon="🌲")
pg.run()