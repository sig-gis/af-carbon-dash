import streamlit as st
import altair as alt
import pandas as pd
from scipy.interpolate import make_interp_spline
import numpy as np

st.set_page_config(page_title="Carbon Units Estimate", page_icon="📈")

st.title("📈 Carbon Units Estimate")

# --- Retrieve carbon_df from previous page ---
if "carbon_df" not in st.session_state:
    st.error("No carbon data found. Please return to the Planting Scenario page first.")
    st.stop()

df = st.session_state.carbon_df.copy()

# --- User input: Acreage ---
acreage = st.number_input("Enter acreage:", min_value=1, value=100)
# --- User input: Protocol ---
protocol = st.selectbox("Select Protocol", options=["ACR", "CAR", "VERRA"])

# --- Build ACR DataFrame ---
df_acr = st.session_state.carbon_df.copy()
df_acr['Area_acres'] = acreage
df_acr['Onsite Total CO2'] = df_acr['C_Score'] * 3.667 # Convert C_Score to CO2 equivalent (1 ton C = 3.667 tons CO2)
df_acr['StudyArea_ModelType'] = "Project"
df_acr['StudyArea_Protocol'] = "ACR"

# interpolate missing years
# Pick the columns
df_poly = df_acr[['Year', 'Onsite Total CO2']]
# Sort by year
df_poly = df_poly.sort_values('Year')
# Get X (years) and y (stocking) values
X = df_poly['Year'].values
y = df_poly['Onsite Total CO2'].values
# Create the spline interpolation function
spline = make_interp_spline(X, y, k=3)  # cubic spline
# Predict for every year between min and max year
years_interp = np.arange(df_poly['Year'].min(), df_poly['Year'].max() + 1)
y_interp = spline(years_interp)
# Collect results
df_interp = pd.DataFrame({
    'Year': years_interp,
    'Onsite Total CO2_interp': y_interp,
    'ModelType': 'Project'
})

# Make project_df
project_df = df_interp.copy() # everything so far is project

# Add baseline as 0
# Identify all years
all_years = df_interp['Year'].unique()
all_years = np.sort(all_years)
# Create a new DataFrame for Baseline
baseline_df = pd.DataFrame({
    'Year': all_years,
    'Onsite Total CO2_interp': 0,
    'ModelType': 'Baseline',
})

# Calculate delta C 
baseline_df['delta_C_baseline'] = baseline_df['Onsite Total CO2_interp'].diff()
project_df['delta_C_project'] = project_df['Onsite Total CO2_interp'].diff()

# Merge baseline and project deltas
merged_df = pd.merge(baseline_df[['Year', 'delta_C_baseline']], project_df[['Year', 'delta_C_project']], on='Year')

# Calculate C_total: difference between project and baseline delta
merged_df['C_total'] = merged_df['delta_C_project'] - merged_df['delta_C_baseline']

# Calculate risk buffer (20% of C_total)
BUF = 0.20
merged_df['BUF'] = merged_df['C_total'] * BUF

# Calculate ERTs
merged_df['ERT'] = merged_df['C_total'] - merged_df['BUF']

# Round delta_C_project, delta_C_baseline, C_total, BUF and ERT columns (cleaning up)
merged_df['delta_C_project'] = merged_df['delta_C_project'].round(2)
merged_df['delta_C_baseline'] = merged_df['delta_C_baseline'].round(2)
merged_df['C_total'] = merged_df['C_total'].round(2)
merged_df['BUF'] = merged_df['BUF'].round(2)
merged_df['ERT'] = merged_df['ERT'].round(2)

st.session_state.merged_df = merged_df

# -- PLot ERTs ---
ERT_chart = alt.Chart(merged_df).mark_line(point=True).encode(
    x=alt.X('Year:O', title='Year', axis=alt.Axis(labelAngle=30)),
    y=alt.Y('ERT:Q', title='ERTs (tonnes CO₂e)'),
    tooltip=['Year', 'ERT']
).properties(
    title='Annual ERT Estimates',
    width=600,
    height=400
).configure_axis(
    grid=True,
    gridOpacity=0.3
)

st.altair_chart(ERT_chart, use_container_width=True)
