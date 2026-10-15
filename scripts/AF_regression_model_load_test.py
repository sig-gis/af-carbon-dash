import joblib
import os

import numpy as np
import pandas as pd
import seaborn as sns
from matplotlib import pyplot as plt

pd.set_option("display.max_columns", 100)
pd.set_option("display.max_rows", 750)
pd.set_option("display.width", 500)

BASE_DIR = "/mnt/share/rem/PC585_AF_Refor_data/fvs"

AF_PARAMS = {}
AF_PARAMS["SPECIES"] = {
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
AF_PARAMS["SI"] = {
     # [min SI, max SI, step size], site species
    "EC":   [[50, 110, 10], "DF"],
    "CR_1": [[40, 110, 10], "PP"],
    "CR_2": [[30, 105, 10], "PP"],
    "IE_1": [[70, 80, 10], "PP"], # one dummy step since FVS does not use SI for this variant
    "IE_2": [[70, 80, 10], "PP"], # one dummy step since FVS does not use SI for this variant
    "CI":   [[40, 160, 20], "PP"], # dummy steps since FVS does not use SI for this variant
    "BM":   [[70, 150, 10], "PP"],
    "SO":   [[70, 150, 10], "PP"],
    "WS_1": [[20, 110, 15], "PP"],
    "WS_2": [[20, 110, 15], "PP"],
    "CA_1": [[20, 110, 15], "PP"],
    "CA_2": [[20, 110, 15], "PP"],
    "EM":   [[40, 160, 15], "PP"],
    "PN":   [[96, 144, 8],  "DF"],
    "WC_1":   [[96, 144, 8], "DF"],
    "WC_2":   [[96, 144, 8], "DF"],
    "NC_1": [[25, 115, 10], "PP"],
    "NC_2": [[20, 90, 10], "TO"],
    "UT_1": [[40, 160, 15], "PP"],
    "UT_2": [[40, 160, 15], "PP"],
    "AK":   [[40, 120, 10], "SS"],
    "TT":   [[10, 110, 10], "DF"],
}
AF_PARAMS["SURVIVAL"] = {
    "EC":   [50, 90, 5],
    "CR_1": [20, 90, 5],
    "CR_2": [20, 90, 5],
    "IE_1": [50, 90, 5],
    "IE_2": [50, 90, 5],
    "CI":   [50, 90, 5],
    "BM":   [50, 90, 5],
    "SO":   [50, 90, 5],
    "WS_1": [50, 90, 5],
    "WS_2": [50, 90, 5],
    "CA_1": [50, 90, 5],
    "CA_2": [50, 90, 5],
    "EM":   [50, 90, 5],
    "PN":   [50, 90, 5],
    "WC_1": [50, 90, 5],
    "WC_2": [50, 90, 5],
    "NC_1": [50, 90, 5],
    "NC_2": [50, 90, 5],
    "UT_1": [50, 90, 5],
    "UT_2": [50, 90, 5],
    "AK":   [50, 90, 5],
    "TT":   [50, 90, 5],
}
AF_PARAMS["TPAS"] = {"MIN_TPA": 100, "MAX_TPA": 460, "STEP_TPA": 20}
PCT_LEVELS = [0, 1, 2]
TARGETS = ["ABLD_C", "BA", "QMD", "Tpa", "SDI", "TCuFt", "MCuFt"]
YEARS = range(2029, 2129, 5) # start, end, step size
REPLICATIONS = 30

np.random.seed(1234567789)

def get_random_inputs(variant: str, parameters: dict) -> list:
    '''
    Return a list of integers randomly selected from within the allowable range of values.
    '''

    survival = np.random.randint(parameters["SURVIVAL"][variant][0], parameters["SURVIVAL"][variant][1])
    total_TPA = 0
    while (total_TPA < 100) or (total_TPA > 460):
        SP1_TPA = np.random.randint(1, 460)
        SP2_TPA = np.random.randint(1, 460)
        SP3_TPA = np.random.randint(1, 460)
        SP4_TPA = np.random.randint(1, 460)
        total_TPA = SP1_TPA + SP2_TPA + SP3_TPA + SP4_TPA

    SI = np.random.randint(parameters["SI"][variant][0][0], parameters["SI"][variant][0][1])

    return [survival, total_TPA, SP1_TPA, SP2_TPA, SP3_TPA, SP4_TPA, SI]


df = pd.DataFrame(columns=["Variant", "Location", "PCT Level", "Year", "Target", "Random inputs (Surv, total_TPA, TPA1, TPA2, TPA3, TPA4, SI)", "Prediction"])

for variant in sorted(AF_PARAMS["SPECIES"].keys())[:]:
    all_targets = TARGETS + [f"{x}_TPA" for x in AF_PARAMS["SPECIES"][variant]]
    location_dirs = os.listdir(f"{BASE_DIR}/{variant}")
    for location in location_dirs:
        for pct_level in PCT_LEVELS:
            for _ in range(REPLICATIONS):
                random_inputs = get_random_inputs(variant, AF_PARAMS)
                year = np.random.choice(YEARS)
                target = np.random.choice(all_targets)

                model_file = f"{BASE_DIR}/{variant}/{location}/{variant}_v4_PCT{pct_level}_Jenkins_{location}_ridge_models.pkl"
                ridge_models = joblib.load(open(model_file, "rb"))

                if (variant == "IE_2") or (variant == "WC_1"):
                    # 20 levels of year, 8 levels of target variable (only 1 level of XX_TPA)
                    assert len(ridge_models.keys()) == 160, f"{variant}{location}-PCT{pct_level}: {len(ridge_models.keys())}"
                    # special case: skip these predictions
                else:
                    # 20 levels of year, 11 levels of target variable (4 levels of XX_TPA)
                    assert len(ridge_models.keys()) == 220, f"{variant}{location}-PCT{pct_level}: {len(ridge_models.keys())}"

                    X = pd.DataFrame({"Survival": [random_inputs[0]], "total_TPA": [random_inputs[1]], "SP1_TPA": [random_inputs[2]], "SP2_TPA": [random_inputs[3]], "SP3_TPA": [random_inputs[4]], "SP4_TPA": [random_inputs[5]], "SI": [random_inputs[6]]}) # wrap the inputs in a dataframe or sklearn will complain
                    predicted = max(0, (round(ridge_models[(year, target)].predict(X)[0], 4)))
                    df.loc[-1] = [variant, location, pct_level, year, target, random_inputs, predicted]
                    df.index += 1

print(df.groupby("Target").describe()["Prediction"])
print(df)

col_order = sorted(df["Target"].unique().tolist())
fig = sns.displot(df, x="Prediction", hue="Variant", kind="kde", col="Target", col_wrap=6, facet_kws=dict(sharey=False, sharex=False), col_order=col_order, cut=0)
plt.show()
fig.savefig("/tmp/kde.png")
