import streamlit as st
import json
import pandas as pd
import numpy as np
import altair as alt


st.set_page_config(page_title="Planting Scenario", page_icon="🌲")

st.title("🌲 Planting Scenario")

# --- User inputs ---
variant = st.selectbox("FVS Variant", options=["PN", "WC", "SO"])
survival = st.slider("Survival Percentage", min_value=40, max_value=90, value=70)
si = st.slider("Site Index", min_value=96, max_value=137, value=int(np.mean([96, 137])))

st.subheader("🌲 Species Mix (TPA)")
tpa_df = st.slider("Douglas Fir", 0, 435, 45)
tpa_rc = st.slider("Red Cedar", 0, 436 - tpa_df, 0)
tpa_wh = st.slider("Western Hemlock", 0, 437 - tpa_df - tpa_rc, 0)
tpa_total = tpa_df + tpa_rc + tpa_wh
st.markdown(f"Total TPA: {tpa_total}")

# --- Carbon Score Calculation ---
# Read coefficients from JSON file
with open("conf/base/carbon_model_coefficients.json", "r") as file:
    coefficients = json.load(file)
# Calculate carbon output based on coefficients
years, c_scores, ann_c_scores = [], [], []
for year in coefficients.keys():
    c_score = (coefficients[year]['TPA_DF'] * tpa_df 
               + coefficients[year]['TPA_RC'] * tpa_rc 
               + coefficients[year]['TPA_WH'] * tpa_wh
               + coefficients[year]['TPA_total'] * tpa_total
               + coefficients[year]['Survival'] * survival
               + coefficients[year]['SI'] * si
               + coefficients[year]['Intercept'])
    if len(c_scores) > 1:
        ann_c_score = c_score - c_scores[-1]
    else:
        ann_c_score = c_score
    c_scores.append(c_score)
    ann_c_scores.append(ann_c_score)
    years.append(int(year))

df = pd.DataFrame({"Year": years, "C_Score": c_scores, "Annual_C_Score": ann_c_scores})
st.session_state.carbon_df = df

# --- Plot ---
line = alt.Chart(df).mark_line(point=True).encode(
    x=alt.X('Year:O', title='Year', axis=alt.Axis(labelAngle=30)),  
    y=alt.Y('C_Score:Q', title='Onsite Carbon (tons/acre)'),
    tooltip=['Year', 'C_Score']
).properties(
    title="Cumulative Onsite Carbon",
    width=600,
    height=400
)

# Show in Streamlit
st.altair_chart(line, use_container_width=True)

# -- Display Results ---
# st.success(f"Average Annual Carbon Output: {df['Annual_C_Score'].mean():.2f}")
st.success(f"Final Carbon Output (year {max(df['Year'])}): {df['C_Score'].iloc[-1]:.2f}")
