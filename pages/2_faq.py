import streamlit as st

st.set_page_config(layout="wide", page_title="Home", page_icon="🌲")

st.title("❓Frequently Asked Questions")

# Define the FAQs as a list of dictionaries
faqs = [
    {
        "q": 'What does "Cumulative On-Site Carbon" mean?',
        "a": """
**Cumulative On-Site Carbon** is the net amount of carbon stored within a project area over time, adding up all eligible carbon. It reflects everything that happens within **each acre** in the selected variant.
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
The current version of the dashboard approximates a **let-grow** simulation for the duration of the project, with a growth/reporting interval of **5 years**.
        """
    },
    {
        "q": "How are the five-year outputs converted to annual CO₂e/ac stocking values?",
        "a": """
We apply a **cubic spline interpolation** to create continuous **annual** stocking values from **5-year** intervals. The resulting annual estimates are available for download as a separate .csv file from the dashboard.
        """
    },
    {
        "q": "What is the difference between the carbon protocols?",
        "a": """
The same project scenario can yield different credit numbers across protocols because of differences in accounting rules. Below are the protocols currently supported in this dashboard and the modeled assumptions for risk/buffer, leakage, uncertainty, and measurement.

| Protocol | Risk/Buffer | Leakage | Uncertainty | Measurement |
|---|---:|---:|---:|---:|
| [Verra (VCS)](https://verra.org/methodologies/vm0047-afforestation-reforestation-and-revegetation-v1-0/) | 20% | 0% | 0% | Jenkins(https://academic.oup.com/forestscience/article-abstract/49/1/12/4617214) |
| [ACR](https://acrcarbon.org/methodology/afforestation-and-reforestation-of-degraded-lands/) | 20% | 0% | 0% | Jenkins |
| [CAR](https://www.climateactionreserve.org/wp-content/uploads/2023/07/Final_Forest_Protocol_V5.1_7.14.2023.pdf) | 20% | 0% | 0% | Jenkins |
| [Isometric](https://registry.isometric.com/protocol/reforestation/1.0#data-sharing) | 25% | 0% | 0% | Jenkins |
| [Gold Standard](https://globalgoals.goldstandard.org/403-luf-ar-methodology-ghgs-emission-reduction-and-sequestration-methodology/) | 0% | 0% | 0% | Jenkins |

*Note 1:* To isolate protocol-rule effects, this dashboard uses **Jenkins biomass equations for all protocols** (we do not switch between Jenkins and FVS Fire and Fuels module).

*Note 2:* The **25% risk buffer** for *Isometric* reflects a valid value within their allowed range. Because this dashboard compares **default assumptions**, 20% would be most consistent across protocols. However, the current 25% value serves as a **placeholder** until the **financial verification cost step** is implemented, which will further differentiate Isometric from the others. *This value will be updated in future versions.*
        """
    },
    {
        "q": "How are FVS simulations approximated for real-time analysis in the dashboard?",
        "a": "A representative sample of single-stand FVS simulations is first generated across the project lifetime, spanning a range of plausible planting parameters and species combinations. These simulations are run for each supported FVS Variant using variant-appropriate species."
        "The resulting FVS outputs are then used as a training dataset for machine learning models (in this case, polynomial regression models) that approximate FVS-predicted values at each timestep across the project lifetime. When users adjust planting parameters, these models generate real-time predictions of FVS outputs without the computational latency of running a full FVS simulation."
        "This approach preserves the growth dynamics and carbon accumulation behavior modeled by FVS while enabling efficient, interactive scenario analysis."
        "Machine learning is used strictly as a computational approximation of FVS outputs and does not introduce new growth assumptions or carbon accounting rules."
    },
    {
        "q": "Is it possible to model an unrealistic scenario?",
        "a": "Yes. The dashboard would have warned you if the total TPA (trees per acre) exceeds a cap, but extreme inputs can still produce unrealistic scenarios."
    },
]

# Render expanders (first one expanded)
for i, item in enumerate(faqs):
    with st.expander(item["q"], expanded=(i == 0)):
        st.markdown(item["a"])

# Special case: LaTeX formula in its own expander
with st.expander("How are the full verification costs calculated?"):
    st.markdown("""
The following formula is used to calculate the full verification costs, based on user inputs selected in the Financial Options drop-down menu:
""")
    st.latex(r"""
\textit{Full\ verification\ costs} =
\textit{Number\ of\ plots} \times \textit{Cost\ per\ CFI\ plot} \times (1 + \textit{Anticipated\ inflation})
""")

