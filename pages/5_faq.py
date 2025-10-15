import streamlit as st

st.set_page_config(layout="wide", page_title="Home", page_icon="🌲")

st.title("❓Frequently Asked Questions")

# Define the FAQs as a list of dictionaries
faqs = [
    {
        "q": 'What does "Cumulative On-Site Carbon" mean?',
        "a": """
**Cumulative On-Site Carbon** is the total net amount of carbon stored on a property over time, adding up all eligible carbon *(note to discuss: minus losses from harvest or disturbances?)*. It reflects everything that happens within **one acre** in the selected variant.
        """
    },
    {
        "q": "What is the baseline scenario assumption?",
        "a": """
The baseline scenario in the current version of the dashboard assumes **bare ground with no natural regeneration**.
        """
    },
    {
        "q": "What Forest Vegetation Simulator (FVS) modeling approach is applied?",
        "a": """
The current version of the dashboard applies a **let-grow** simulation for **40 years**, with a growth/reporting interval of **5 years**.
        """
    },
    {
        "q": "How are the five-year outputs converted to annual CO₂e/ac stocking values?",
        "a": """
We apply a **cubic spline interpolation** to create continuous **annual** stocking values from **5-year** intervals.
        """
    },
    {
        "q": "What is the difference between the carbon protocols?",
        "a": """
The same project scenario can yield different credit numbers across protocols because rules may differ for baseline *(note to discuss: not accounted for yet)*, additionality *(note to discuss: not accounted for yet)*, leakage (0%), risk/buffer deductions, uncertainty (0%), and measurement *(note to discuss: Jenkins vs FVS)*.
This dashboard currently supports:
- [Verra (VCS)](https://verra.org/methodologies/vm0047-afforestation-reforestation-and-revegetation-v1-0/)
- [ACR](https://acrcarbon.org/methodology/afforestation-and-reforestation-of-degraded-lands/)
- [CAR](https://www.climateactionreserve.org/wp-content/uploads/2023/07/Final_Forest_Protocol_V5.1_7.14.2023.pdf)
- [Isometric](https://registry.isometric.com/protocol/reforestation/1.0#data-sharing)
- [Gold Standard](https://globalgoals.goldstandard.org/403-luf-ar-methodology-ghgs-emission-reduction-and-sequestration-methodology/)

**Modeled buffer assumptions here:** Verra/ACR/CAR = **20%**, Gold Standard = **0%**, Isometric = **25%** *(note to discuss: why is this 25%?)*.  
*Note:* To isolate protocol-rule effects, this dashboard uses **FVS modules** for all protocols (we do not switch between Jenkins and FVS).
        """
    },
    {
        "q": "How are FVS simulations approximated for real-time analysis in the dashboard?",
        "a": "*Coming soon.*"
    },
    {
        "q": "Is it possible to model an unrealistic scenario?",
        "a": "Yes. The dashboard will warn you when the total TPA (trees per acre) for either of the tree species exceeds a cap, but extreme inputs can still produce unrealistic scenarios."
    },
]

# Render expanders (first one expanded)
for i, item in enumerate(faqs):
    with st.expander(item["q"], expanded=(i == 0)):
        st.markdown(item["a"])

# Special case: LaTeX formula in its own expander
with st.expander("How are the Full verification costs calculated?"):
    st.markdown("""
The following formula is used to calculate the full verification costs, based on user inputs selected in the Financial Options drop-down menu:
""")
    st.latex(r"""
\textit{Full\ verification\ costs} =
\textit{Number\ of\ plots} \times \textit{Cost\ per\ CFI\ plot} \times (1 + \textit{Anticipated\ inflation})
""")

