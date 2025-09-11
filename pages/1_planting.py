import streamlit as st
import json
import pandas as pd
import numpy as np
import altair as alt

st.set_page_config(page_title="Planting Scenario", page_icon="🌲")
st.title("🌲 Planting Scenario")

# --- User inputs ---
# variant = st.selectbox("FVS Variant", options=["PN", "WC", "SO"])
variant_options = ["AK",
                    "BM",
                    "CA",
                    "CI",
                    "CR",
                    "CS",
                    "EC",
                    "EM",
                    "IE",
                    "LS",
                    "NC",
                    "NE",
                    "PN",
                    "SN",
                    "SO",
                    "TT",
                    "UT",
                    "WC",
                    "WS"]

# Default to session_state if available
default_variant = st.session_state.get("selected_variant", variant_options[0])

# Dictionary for each FVS variant; random values for now, replace with real values
variant_presets = {
    "AK": {"survival": 70, "si": 110, "tpa_df": 50, "tpa_rc": 20, "tpa_wh": 10},
    "BM": {"survival": 65, "si": 120, "tpa_df": 60, "tpa_rc": 25, "tpa_wh": 15},
    "CA": {"survival": 80, "si": 130, "tpa_df": 55, "tpa_rc": 30, "tpa_wh": 10},
    "CI": {"survival": 75, "si": 125, "tpa_df": 45, "tpa_rc": 25, "tpa_wh": 20},
    "CR": {"survival": 60, "si": 115, "tpa_df": 40, "tpa_rc": 30, "tpa_wh": 15},
    "CS": {"survival": 68, "si": 118, "tpa_df": 50, "tpa_rc": 20, "tpa_wh": 15},
    "EC": {"survival": 72, "si": 122, "tpa_df": 55, "tpa_rc": 15, "tpa_wh": 20},
    "EM": {"survival": 66, "si": 119, "tpa_df": 60, "tpa_rc": 20, "tpa_wh": 10},
    "IE": {"survival": 70, "si": 124, "tpa_df": 50, "tpa_rc": 25, "tpa_wh": 15},
    "LS": {"survival": 65, "si": 117, "tpa_df": 45, "tpa_rc": 30, "tpa_wh": 10},
    "NC": {"survival": 75, "si": 128, "tpa_df": 55, "tpa_rc": 25, "tpa_wh": 10},
    "NE": {"survival": 68, "si": 120, "tpa_df": 50, "tpa_rc": 20, "tpa_wh": 15},
    "PN": {"survival": 70, "si": 125, "tpa_df": 60, "tpa_rc": 15, "tpa_wh": 20},
    "SN": {"survival": 66, "si": 123, "tpa_df": 55, "tpa_rc": 25, "tpa_wh": 10},
    "SO": {"survival": 72, "si": 126, "tpa_df": 50, "tpa_rc": 30, "tpa_wh": 10},
    "TT": {"survival": 65, "si": 119, "tpa_df": 45, "tpa_rc": 20, "tpa_wh": 15},
    "UT": {"survival": 70, "si": 121, "tpa_df": 55, "tpa_rc": 15, "tpa_wh": 20},
    "WC": {"survival": 68, "si": 124, "tpa_df": 50, "tpa_rc": 25, "tpa_wh": 10},
    "WS": {"survival": 66, "si": 122, "tpa_df": 60, "tpa_rc": 20, "tpa_wh": 15}
}

# variant = st.selectbox(
#     "FVS Variant",
#     options=variant_options,
#     index=variant_options.index(default_variant) if default_variant in variant_options else 0
# )
variant = st.session_state.get("selected_variant", variant_options[0])

st.markdown(f"**FVS Variant: ** {variant}")

# --- Update slider defaults based on selected variant ---
preset = variant_presets[variant]

# survival = st.slider("Survival Percentage", min_value=40, max_value=90, value=70)
# si = st.slider("Site Index", min_value=96, max_value=137, value=int(np.mean([96, 137])))
survival = st.slider(
    "Survival Percentage", 
    min_value=40, 
    max_value=90, 
    value=preset["survival"]
)
si = st.slider(
    "Site Index", 
    min_value=96, 
    max_value=137, 
    value=preset["si"]
)

st.subheader("🌲 Species Mix (TPA)")
# tpa_df = st.slider("Douglas Fir", 0, 435, 45)
# tpa_rc = st.slider("Red Cedar", 0, 436 - tpa_df, 0)
# tpa_wh = st.slider("Western Hemlock", 0, 437 - tpa_df - tpa_rc, 0)
tpa_df = st.slider("Douglas Fir", 0, 435, preset["tpa_df"])
tpa_rc = st.slider("Red Cedar", 0, 436 - tpa_df, preset["tpa_rc"])
tpa_wh = st.slider("Western Hemlock", 0, 437 - tpa_df - tpa_rc, preset["tpa_wh"])
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
