import pickle
import numpy as np
import pandas as pd
from sklearn.preprocessing import PolynomialFeatures

poly = PolynomialFeatures(degree=3, include_bias=False)

def build_input_vector(survival: int, total_tpa: int, sp1: int, sp2: int, sp3: int, sp4: int, si: int) -> np.ndarray:
    """
    Expected species order for supported variants:
    - PN: DF, WH, RC, SS
    - EC: PP, DF, WL, PM
    """
    X = np.array([[float(survival), float(total_tpa), float(sp1), float(sp2), float(sp3), float(sp4), float(si)]], dtype=float)
    return poly.fit_transform(X)

def pick_fvs_models(base, variant, loccode) -> str:
    """
    Pick the right models to load based on user-selected Variant and loc code. 

    Returns: (str) path to the model to load
    """
    return f"{base}/{variant}_v3_{loccode}_models.pkl"

def load_fvs_models(path) -> dict:
    """
    Load the models from the path determined in pick_fvs_modes. 

    Returns: (dict) models for correct variant-location with keys: (year, variable)
    """
    with open(path, 'rb') as f: 
        models = pickle.load(f)
    return models

def predict_metrics(models, X_poly: np.ndarray) -> list[dict]:
    rows = []
    for (year, var), m in models.items():
        y_pred = max(m.predict(X_poly)[0], 0)
        rows.append({"Year": int(year), "Variable": var, "Value": y_pred})
    metrics_df = (
        pd.DataFrame(rows)
        .pivot(index="Year", columns="Variable", values="Value")
        .reset_index()
    )
    return metrics_df