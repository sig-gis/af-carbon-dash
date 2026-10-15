import os
import pandas as pd
import joblib

pd.set_option("display.max_columns", 100)
pd.set_option("display.max_rows", 750)
pd.set_option("display.width", 500)

BASE_DIR = "/mnt/share/rem/PC585_AF_Refor_data/fvs"
SPECIES = {
    "EC":   ["PP", "DF", "WL", "WP"], # PIPO, PSME, LAOC, PIMO3 (western white pine)
    "CR_1": ["PP", "DF", "SW", "PM"], # PIPO, PSME, PIST3 (southwestern white pine), PIMO (singleleaf pinyon)
    "CR_2": ["PM", "UJ", "PP", "DF"], # PIMO (southwestern white pine), JUOS (Utah juniper), PIPO, PSME
    "IE_1": ["PP", "DF", "WL", "WP"], # PIPO, PSME, LAOC,  PIMO3 (western white pine)
    "IE_2": ["WB"], # PIAL
    "CI":   ["PP", "DF", "WL", "WP"], # PIPO, PSME, LAOC, PIMO3 (western white pine)
    "BM":   ["PP", "DF", "WL", "WP"], # PIPO, PSME, LAOC, PIMO3 (western white pine)
    "SO":   ["PP", "DF", "WF", "SP"], # PIPO, PSME, ABCO, PILA
    "WS_1": ["PP", "JP", "WF", "IC"], # PIPO, PIJE, ABCO, CADE27
    "WS_2": ["PP", "DF", "WP", "WF"], # PIPO, PSME, PIMO3 (western white pine), ABCO
    "CA_1": ["PP", "WF", "IC", "SP"], # PIPO, ABCO, CADE27, PILA
    "CA_2": ["IO", "BO", "BL", "SP"], # QUWI2, QUKE, QUDO, PILA
    "EM":   ["PP", "DF", "WL", "LP"], # PIPO, PSME, LAOC, PICO
    "PN":   ["DF", "WH", "RC", "SS"], # PSME, TSHE, THPL, PISI
    "WC_1": ["WB"], # PIAL
    "WC_2": ["DF", "WH", "RC", "GF"], # PSME, TSHE, THPL, ABGR
    "NC_1": ["PP", "SP", "RW", "IC"], # PIPO, PILA, SESE3, CADE27
    "NC_2": ["MA", "BO", "DF", "PP"], # QUKE is the only oak spp available; MA = Pacific madrone = Arbutus menziesii
    "UT_1": ["PP", "DF", "BS", "WF"], # PIPO, PSME, PIPU (blue spruce = Picea pungens), ABCO
    "UT_2": ["PM", "UJ", "PP", "BS"], # PIMO (singleleaf pinyon), JUOS, PIPO, PIPU (blue spruce = Picea pungens)
    "AK":   ["SS", "WS", "WH", "RC"], # PISI, PIGL (white spruce = Picea glauca), TSHE, THPL
    "TT":   ["PP", "DF", "BS", "LM"], #  PIPO, PSME, PIPU, PIFL2 (limber pine = Pinus flexilis)
}
PCT_LEVELS = [0, 1, 2]

df = pd.DataFrame(columns=["Variant", "Location", "PCT Level", "Number of Models"])

for variant in sorted(SPECIES.keys())[:]:
    location_dirs = os.listdir(f"{BASE_DIR}/{variant}")

    for location in location_dirs:
        for pct_level in PCT_LEVELS:
            model_file = f"{BASE_DIR}/{variant}/{location}/{variant}_v4_PCT{pct_level}_Jenkins_{location}_ridge_models.pkl"
            ridge_models = joblib.load(open(model_file, "rb"))
            if (variant == "IE_2") or (variant == "WC_1"):
                # 20 levels of year, 8 levels of target variable (only 1 level of XX_TPA)
                assert len(ridge_models.keys()) == 160, f"{variant}{location}-PCT{pct_level}: {len(ridge_models.keys())}"
            else:
                # 20 levels of year, 11 levels of target variable (4 levels of XX_TPA)
                assert len(ridge_models.keys()) == 220, f"{variant}{location}-PCT{pct_level}: {len(ridge_models.keys())}"
            df.loc[-1] = [variant, location, pct_level, len(ridge_models.keys())]
            df.index += 1
print(df)
