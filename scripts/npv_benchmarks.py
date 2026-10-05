# [[file:../../../../data/Nextcloud-SIG/dschmidt_working_projects/PC585_AF_Reforestation/PC585_breakeven_analysis.org::*Batched][Batched:1]]
import time, copy
from aff_dash_client.client import AFFDashClient

batch_size = 1000

# AK, BM, CA, CI, IE, NC, SO, TT, UT_1,WC_2 don't work yet
varlocs = {
    #"AK": {
    #    "locations": [703, 1004, 1005],
    #    "site_index": [41, 120],
    #    "survival": [70],
    #    "pct_level": ["PCT0", "PCT1", "PCT2"],
    #    },
    #"BM": {
    #    "locations": [604, 607, 614, 616, 619],
    #    #"site_index": [70, 145],
    #    "site_index": [96, 137],
    #    "survival": [70],
    #    "pct_level": ["PCT0", "PCT1", "PCT2"],
    #    },
    #"CA": {
    #    "locations": [505, 506, 508, 511, 513, 514, 515, 516, 518, 610, 611],
    #    "site_index": [41, 120],
    #    "survival": [70],
    #    "pct_level": ["PCT0", "PCT1", "PCT2"],
    #    },
    #"CI": {
    #    "locations": [402, 406, 412, 413, 414, 415],
    #    #"site_index": [40, 160],
    #    "site_index": [96, 137],
    #    "survival": [70],
    #    "pct_level": ["PCT0", "PCT1", "PCT2"],
    #    },
    #"CR_1": { # this works
    #    "locations": [201, 202, 203, 204, 205, 206, 207, 208, 209, 210, 211, 301, 302, 303, 304, 305, 306, 307, 308, 309, 311, 312, 501, 512],
    #    "site_index": [40, 110],
    #    "survival": [65],
    #    "pct_level": ["PCT0", "PCT1", "PCT2"],
    #    },
    #"EC": { # this works
    #    "locations": [603, 605, 606, 608, 613, 617, 621, 699],
    #    "site_index": [40, 110],
    #    "survival": [70],
    #    "pct_level": ["PCT0", "PCT1", "PCT2"],
    #},
    #"EM": { # this works
    #    "locations": [102, 108, 109, 111, 112, 115],
    #    "site_index": [40, 160],
    #    "survival": [70],
    #    "pct_level": ["PCT0", "PCT1", "PCT2"],
    #    },
    #"IE": {
    #    "locations": [103, 105, 160, 110, 113, 114, 116, 117, 118, 621],
    #    "site_index": [40, 160],
    #    "survival": [70],
    #    "pct_level": ["PCT0", "PCT1", "PCT2"],
    #    },
    #"NC_1": { #
    #    "locations": [505, 507, 508, 510, 518, 611, 705],
    #    "site_index": [40, 160],
    #    "survival": [70],
    #    "pct_level": ["PCT0", "PCT1", "PCT2"],
    #    },
    "PN": { # this works
        "locations": [603, 606, 609, 612, 613, 615, 708, 709, 712, 800],
        "site_index": [96, 137],
        "survival": [70],
        "pct_level": ["PCT0", "PCT1", "PCT2"],
        },
    #"SO": {
    #    "locations": [505, 506, 509, 511, 514, 601, 602, 610, 619, 620, 702],
    #    "site_index": [70, 145],
    #    "survival": [70],
    #    "pct_level": ["PCT0", "PCT1", "PCT2"],
    #    },
    #"TT": {
    #    "locations": [403, 404, 405, 414, 415, 416],
    #    "site_index": [70, 145],
    #    "survival": [70],
    #    "pct_level": ["PCT0", "PCT1", "PCT2"],
    #    },
    #"UT_1": {
    #    "locations": [401, 404, 407, 408, 409, 410, 417, 418, 419, 504],
    #    "site_index": [40, 160],
    #    "survival": [70],
    #    "pct_level": ["PCT0", "PCT1", "PCT2"],
    #    },
    #"WC_2": {
    #    "locations": [603, 605, 606, 610, 613, 615, 618, 708, 709, 710, 711],
    #    "site_index": [96, 137],
    #    "survival": [70],
    #    "pct_level": ["PCT0", "PCT1", "PCT2"],
    #    },
    #"WS_1": { # this works
    #    "locations": [417, 501, 502, 503, 504, 506, 507, 511, 512, 513, 515, 516, 517],
    #    "site_index": [25, 110],
    #    "survival": [70],
    #    "pct_level": ["PCT0", "PCT1", "PCT2"],
    #    },
}

default_financial_params = {
    "ACR":
    {
        'anticipated_inflation': 0.03,
        'cost_per_cfi_plot': 150,
        'credit_price_increase': 0.02,
        'discount_rate': 0.06,
        'issuance_fee_per_ert': 0.15,
        'num_plots': 250,
        'planting_cost': 1000,
        'price_per_ert_initial': 25.0,
        'registry_fees': 500,
        'validation_cost': 45000,
        'verification_cost': 25000
    }
}
# Target parameter values: all variant-locations plus:
#npv_years = [5, 10, 15, 20, 25, 30, 35, 40, 45, 50] # 40 is the key year
#discount_rates = [0.06, 0.10] # 0.10 is the new default
#ert_prices = [15, 25, 35, 45, 55] # 25 is Keith's best guess
#issuance_fees = [0.15, 0.30] # 0.30 is the new default

# Test #1:  Just PN locations
#npv_years = [40]
#discount_rates = [0.06, 0.10] # 0.10 is the new default
#ert_prices = [25] # 25 is Keith's best guess
#issuance_fees = [0.15, 0.30] # 0.30 is the new default
# Output:
#: 240 scenarios to evaluate
#: Approx. run time: 234.09 sec
#: Approx. 0.98 sec per scenario


# Test #2: Just PN locations
npv_years = [40]
discount_rates = [0.06] # 0.10 is the new default
ert_prices = [25] # 25 is Keith's best guess
issuance_fees = [0.15] # 0.30 is the new default
#: 60 scenarios to evaluate
#: Approx. run time: 36.68 sec
#: Approx. 0.61 sec per scenario

aff_dash_client = AFFDashClient()

# build a list of scenarios
scenarios = []
for variant in varlocs.keys():
    for location in varlocs[variant]["locations"]:
        for si in varlocs[variant]["site_index"]:
            for survival in varlocs[variant]["survival"]:
                for pct in varlocs[variant]["pct_level"]:
                    for npv_year in npv_years:
                        for discount_rate in discount_rates:
                            for ert_price in ert_prices:
                                for issuance_fee in issuance_fees:

                                    # update financial params
                                    financial_params = copy.deepcopy(default_financial_params)
                                    financial_params["ACR"]["discount_rate"] = discount_rate
                                    financial_params["ACR"]["price_per_ert_initial"] = ert_price
                                    financial_params["ACR"]["issuance_fee_per_ert"] = issuance_fee

                                    scenario = {
                                        # primary parameters
                                        "variant": variant,
                                        "loccode": str(location),
                                        "si": si,
                                        "survival": survival,
                                        "pct_level": pct,
                                        "npv_year": npv_year,
                                        "financial_params": financial_params,

                                        # fixed parameters
                                        "species_tpa": [65, 65, 64, 64],
                                        "protocols": ["ACR"],

                                        # objective
                                        "solve": {"variable": "net_acres", "target": "npv", "value": 0},
                                        #"solve": {"variable": "net_acres", "target": "tnr", "value": 1_000_000},
                                        #"solve": {"variable": "net_acres", "target": "npv", "value": 500_000},
                                    }
                                    scenarios.append(scenario)

print(f"{len(scenarios)} scenarios to evaluate")

start_time = time.time()
results, errors = aff_dash_client.run_many(scenarios, batch_size=batch_size) # 1000 is the max
run_time = time.time() - start_time

print(f"Approx. run time: {round(run_time, 2)} sec")
print(f"Approx. {round((run_time / len(scenarios)), 2)} sec per scenario")

#print(results)
# Batched:1 ends here
