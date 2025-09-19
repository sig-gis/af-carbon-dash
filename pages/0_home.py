import streamlit as st

st.set_page_config(layout="wide", page_title="Home", page_icon="🌲")

st.title("Welcome to the Carbon Dashboard")
st.markdown("""
Navigate to 🌲 Project Builder in the sidebar to begin exploring the app. 

Inside 🌲 Project Builder, advance through tabs to design your project and estimate outcomes.
- **Site Selection Map**: Select the FVS Variant Location geometry which contains your project location. Your selected FVS Variant Location will auto-populate helpful planting parameter defaults, including species mix, for you. 
- **Planting Scenario**: Estimate certified carbon units under different protocols.
    - *Planting Parameters*: design your reforestation plan (survival percentage, site index, and species mix) and estimate \*FVS results in real time. 
    - *Carbon Estimates*: estimate ERTs (tons CO₂e/acre) under different protocols.
    - *Credits*: Customize financial factors to estimate net project revenue.
            

\*Real-time estimates based on regression models trained on FVS runs.
""")

st.subheader("Warning: This is pre-release software which may contain errors and incomplete or misleading information. It is intended for UX experimentation only.")