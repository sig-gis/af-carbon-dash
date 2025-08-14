import streamlit as st
import numpy_financial as npf

st.set_page_config(page_title="Credits", page_icon="📈")

# -- User inputs: proforma options --
with st.popover("Proforma Options"):
    net_acres = st.number_input("Net Acres:", min_value=1, value=239644, step=100)
    num_plots = st.number_input("# Plots:", min_value=1, value=400)
    cost_per_cfi_plot = st.number_input("Cost/CFI Plot:", min_value=1, value=150)
    price_per_ert_initial = st.number_input("Price/ERT (initial):", min_value=1, value=25)
    credit_price_increase = st.number_input("Credit Price Increase:", min_value=0.0, value=0.02, step=0.01, format="%.2f")  # 2%
    registry_fees = st.number_input("Registry Fees:", min_value=1, value=500)  
    validation_cost = st.number_input("Validation Cost:", min_value=1, value=45000)
    verification_cost = st.number_input("Verification Cost:", min_value=1, value=25000)
    issuance_fee_per_ert = st.number_input("Issuance Fee per ERT:", min_value=0.0, value=0.15, step=0.01, format="%.2f")
    anticipated_inflation = st.number_input("Anticipated Inflation:", min_value=0.0, value=0.0, step=0.01, format="%.2f")
    discount_rate = st.number_input("Discount Rate:", min_value=0.0, value=0.06, step=0.01, format="%.2f")  # 6%
    planting_cost = st.number_input("Planting Cost (initial):", min_value=0, value=0)
    seedling_cost = st.number_input("Seedling Cost (initial):", min_value=0, value=0)
# future planting and seedling costs
year_start = 2025
years_advance = 35

# -- Retrieve merged_df from previous page --
if "merged_df" not in st.session_state:
    st.error("No carbon data found. Please return to the Carbon Units Estimate page first.")
    st.stop()
df_ert = st.session_state.merged_df[['Year', 'ERT']].copy()

# -- Calculate Proforma --
# Credit volume
df_ert['ERTs_Sold'] = 0.0
for i in range(5, len(df_ert), 5):
    df_ert.loc[i, 'ERTs_Sold'] = df_ert.loc[i-4:i, 'ERT'].sum()

# Project revenue
df_ert['ERT_Credit_Price'] = price_per_ert_initial * ((1 + credit_price_increase) ** (df_ert['Year'] - year_start))
df_ert['Total_Revenue'] = df_ert['ERTs_Sold'] * df_ert['ERT_Credit_Price']

# Third-party project costs
df_ert['Validation_and_Verification'] = 0
df_ert.loc[df_ert['Year'] == year_start, 'Validation_and_Verification'] = validation_cost
df_ert.loc[(df_ert['Year'] > year_start) & ((df_ert['Year'] - year_start) % 5 == 0), 'Validation_and_Verification'] = verification_cost

df_ert['Survey_Cost'] = 0
df_ert.loc[(df_ert['Year'] - year_start) % 5 == 4, 'Survey_Cost'] = num_plots * cost_per_cfi_plot * (1 + anticipated_inflation)

df_ert['Registry_Fees'] = registry_fees
df_ert['Issuance_Fees'] = df_ert['ERTs_Sold'] * issuance_fee_per_ert
df_ert['Planting_Cost'] = planting_cost
df_ert['Seedling_Cost'] = seedling_cost

df_ert['Total_Costs'] = (
    df_ert['Validation_and_Verification'] +
    df_ert['Survey_Cost'] +
    df_ert['Registry_Fees'] +
    df_ert['Issuance_Fees'] +
    df_ert['Planting_Cost'] +
    df_ert['Seedling_Cost']
)

df_ert['Net_Revenue'] = df_ert['Total_Revenue'] - df_ert['Total_Costs']

# Only show two decimal digits for certain columns
df_ert.style.format({
    'ERT': '{:.2f}',
    'ERTs_Sold': '{:.2f}',
    'ERT_Credit_Price': '{:.2f}',
    'Total_Revenue': '${:,.2f}',
    'Issuance_Fees': '${:,.2f}',
    'Total_Costs': '${:,.2f}',
    'Net_Revenue': '${:,.2f}'
})

# --- Results ---
total_net_revenue = df_ert['Net_Revenue'].sum()
# net present value
npv_yr20 = npf.npv((anticipated_inflation+discount_rate), df_ert[df_ert['Year'] <= (year_start+20)]['Net_Revenue'])
npv_per_acre_yr20 = npv_yr20 / net_acres


st.subheader("Proforma Results Summary")
st.success(f"Total Net Revenue ({year_start}-{(year_start+years_advance)}): ${total_net_revenue:,.2f}")
st.success(f"NPV at year {(year_start+20)}: ${npv_yr20:,.2f}")
st.success(f"NPV/acre at year {(year_start+20)}: ${npv_per_acre_yr20:.2f}")

proforma_csv_output = df_ert.to_csv(index=False).encode('utf-8')
st.download_button(
    label="⬇️ Download Proforma table (CSV)",
    data=proforma_csv_output,
    file_name='credits_proforma.csv',
    mime='text/csv',
    use_container_width=True
)
