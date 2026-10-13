import json
from pathlib import Path

import pandas as pd
import streamlit as st

st.set_page_config(layout="wide", page_title="Glossary", page_icon="🌲")

BASE_DIR = Path(__file__).resolve().parent.parent
GLOSSARY_PATH = BASE_DIR / "conf" / "base" / "glossary_terms.json"

st.title("📘 Glossary")
st.markdown(
    "Definitions for important terms used throughout the dashboard and API. "
    "Use the search and category filters to quickly find a term."
)

@st.cache_data
def load_glossary() -> pd.DataFrame:
    with GLOSSARY_PATH.open("r", encoding="utf-8") as f:
        terms = json.load(f)
    df = pd.DataFrame(terms).fillna("")
    return df.sort_values(["category", "term"], key=lambda col: col.str.lower()).reset_index(drop=True)

glossary_df = load_glossary()

search = st.text_input("Search glossary", placeholder="Search term, definition, alias, or repo location")
categories = sorted(glossary_df["category"].unique())
selected_categories = st.multiselect("Filter by category", categories)

filtered_df = glossary_df.copy()
if selected_categories:
    filtered_df = filtered_df[filtered_df["category"].isin(selected_categories)]

if search.strip():
    query = search.strip().lower()
    searchable = filtered_df.apply(
        lambda row: " ".join(
            [
                str(row.get("term", "")),
                str(row.get("definition", "")),
                str(row.get("also_known_as", "")),
                str(row.get("category", "")),
                " ".join(row.get("repo_locations", []) or []),
            ]
        ),
        axis=1,
    ).str.lower()
    filtered_df = filtered_df[searchable.str.contains(query, regex=False)]

st.caption(f"Showing {len(filtered_df)} of {len(glossary_df)} terms.")

if filtered_df.empty:
    st.info("No glossary terms match the current filters.")
else:
    for category, category_df in filtered_df.groupby("category", sort=True):
        st.subheader(category)
        for _, row in category_df.sort_values("term", key=lambda col: col.str.lower()).iterrows():
            with st.expander(row["term"]):
                st.markdown(row["definition"])
                details = []
                if row["also_known_as"]:
                    details.append(f"**Also known as:** {row['also_known_as']}")
                repo_locations = row.get("repo_locations", []) or []
                if repo_locations:
                    details.append(f"**Found in repo:** {', '.join(repo_locations)}")
                if details:
                    st.caption("  \n".join(details))
