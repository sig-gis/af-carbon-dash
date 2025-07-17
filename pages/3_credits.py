import streamlit as st

st.set_page_config(page_title="Credits", page_icon="📈")


net_acres = st.number_input("Net Acres:", min_value=1, value=1000, step=100)
n_plots = st.number_input("# Plots:", min_value=1, value=100)
cost_per_cfi_plot = st.number_input("Cost per CFI plot:", min_value=1, value=100)
price_per_crt = st.number_input("Price/CRT:", min_value=1, value=100)
validation_cost = st.number_input("Validation (costs):", min_value=1, value=100)
full_verification_cost = st.number_input("Full Verification (costs):", min_value=1, value=100)
desktop_verification_cost = st.number_input("Desktop Verification (costs):", min_value=1, value=100)
listing_fees = st.number_input("Listing account opening fees:", min_value=1, value=100)
issuance_fees = st.number_input("Issuance fees:", min_value=1, value=100)
crt_increase = st.number_input("Anticipated Credit Price Increase:", min_value=1, value=100)
inflation = st.number_input("Anticipated Inflation:", min_value=1, value=100)
discount = st.number_input("Discount Rate:", min_value=1, value=100)
