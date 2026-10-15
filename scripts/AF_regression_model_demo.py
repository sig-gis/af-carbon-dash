import pandas as pd
import joblib
import sklearn

pd.set_option("display.max_columns", 100)
pd.set_option("display.max_rows", 250)
pd.set_option("display.width", 500)

####################################### SET THESE ##############################################
################################################################################################
BASE_DIR = "/mnt/share/rem/PC585_AF_Refor_data/fvs"
VARIANT = "CR_1"
LOCATION = "201"
PCT_LEVEL = "PCT0" # PCT0, PCT1, or PCT2
VERSION = "v4" # do not change
EQN_SET = "Jenkins" # do not change
YEARS = range(2029, 2129, 5) # start, end, step size

# Survival, total_TPA, SP1_TPA, SP2_TPA, SP3_TPA, SP4_TPA, SI
# pick a set of input values as if you had entered them via the dashboard (note that these values are not sanity-checked here)
#inputs = [65, 340, 1, 1, 1, 1, 110]
inputs = [65, 340, 200, 100, 20, 20, 110] # pick a set of input values as if you had entered them via the dashboard

# choose a subset of outputs...
# ABLD_C = aboveground and belowground live and dead carbon
# BA = basal area
# QMD = quadratic mean diameter
# Tpa = trees per acre
# SDI = stand density index
# TCuFt = total cubic feet volume
# MCuFt = merchantable cubic feet volume
#TARGETS = ["ABLD_C", "BA", "QMD", "Tpa", "SDI", "TCuFt", "MCuFt"]

# ... or also include varloc-specific species TPA targets if desired (e.g., "DF_TPA"); species are listed in D2_regression_model_manifest.csv

# to reiterate:
# these are inputs: total_TPA, SP1_TPA, SP2_TPA, SP3_TPA, SP4_TPA
# these are outputs: Tpa, varloc-specific TPA by species (e.g., PP_TPA)
TARGETS = ["ABLD_C", "BA", "QMD", "Tpa", "SDI", "TCuFt", "MCuFt", "PP_TPA", "DF_TPA", "SW_TPA", "PM_TPA"]
################################################################################################

model_file = f"{BASE_DIR}/{VARIANT}/{LOCATION}/{VARIANT}_{VERSION}_{PCT_LEVEL}_{EQN_SET}_{LOCATION}_ridge_models.pkl"

# outputs are unpredictable if the sum of the individual input TPAs doesn't equal the total input TPA (this is handled by the dashboard code in production)
assert inputs[1] == sum(inputs[2:6])

print("sklearn version: ", sklearn.__version__)
print("pandas version: ", pd.__version__)

ridge_models = joblib.load(open(model_file, "rb"))

X = pd.DataFrame({"Survival": [inputs[0]], "total_TPA": [inputs[1]], "SP1_TPA": [inputs[2]], "SP2_TPA": [inputs[3]], "SP3_TPA": [inputs[4]], "SP4_TPA": [inputs[5]], "SI": [inputs[6]]}) # wrap the inputs in a dataframe or sklearn will complain

# print the outputs...
for year in range(2029, 2129, 5):
    print(year)
    [print(f"   target: {target:<6}, value: {round(ridge_models[(year, target)].predict(X)[0], 4)}") for target in TARGETS]

# ... or save them in a long-format dataframe for further analysis
out_df = pd.DataFrame(columns=["Year", "Target", "Value"])
for year in YEARS:
    for target in TARGETS:
        out_df.loc[-1] = [year, target, ridge_models[(year, target)].predict(X)[0]]
        out_df.index += 1

print(out_df)
