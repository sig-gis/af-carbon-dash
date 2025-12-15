import pickle
from pathlib import Path
from typing import Any

import mlflow
import mlflow.pyfunc
import pandas as pd
import numpy as np

from utils.functions.models import build_input_vector, predict_metrics
# build_input_vector(...) -> X_poly
# predict_metrics(models_dict, X_poly) -> pivoted metrics df
# see utils/functions/models.py


class FVSCollectionModel(mlflow.pyfunc.PythonModel):
    """
    Pyfunc wrapper around a dictionary of partitioned FVS models
    stored in a pickle file with keys: (year, variable).
    """

    def load_context(self, context: mlflow.pyfunc.PythonModelContext) -> None:
        """
        Called once when the model is loaded.
        """
        models_pkl_path = Path(context.artifacts["models_pkl"])
        with open(models_pkl_path, "rb") as f:
            self.models = pickle.load(f)

    def predict(self, context: Any, model_input: pd.DataFrame) -> pd.DataFrame:
        """
        For now, we support a single scenario per call:
        - model_input must have columns:
          ['survival', 'total_tpa', 'sp1', 'sp2', 'sp3', 'sp4', 'si'].

        Returns a DataFrame identical in shape to your current
        predict_metrics() output: Year + metric columns.
        """
        required_cols = ["survival", "total_tpa", "sp1", "sp2", "sp3", "sp4", "si"]
        missing = set(required_cols) - set(model_input.columns)
        if missing:
            raise ValueError(f"model_input missing required columns: {missing}")

        if len(model_input) != 1:
            raise ValueError(
                f"Expected exactly 1 row in model_input, got {len(model_input)}. "
                "You can add multi-row support later if needed."
            )

        row = model_input.iloc[0]

        X_poly = build_input_vector(
            survival=row["survival"],
            total_tpa=row["total_tpa"],
            sp1=row["sp1"],
            sp2=row["sp2"],
            sp3=row["sp3"],
            sp4=row["sp4"],
            si=row["si"],
        )

        metrics_df = predict_metrics(self.models, X_poly)
        return metrics_df

def load_fvs_model_from_registry(variant: str, loccode: str, stage: str = "Production"):
    """
    Load the registered pyfunc model for a given variant/loccode.

    stage can be 'Production', 'Staging', or a version string like '1'.
    """
    model_name = f"af-carbon-dash-FVS-{variant}-{loccode}"

    # If stage looks like a digit, treat it as a version
    if stage.isdigit():
        model_uri = f"models:/{model_name}/{stage}"
    else:
        model_uri = f"models:/{model_name}/{stage}"

    return mlflow.pyfunc.load_model(model_uri)


def run_fvs_prediction(m, *, survival, total_tpa, sp1, sp2, sp3, sp4, si) -> pd.DataFrame:
    """
    Small helper to call the pyfunc model with your usual inputs.
    """
    df_in = pd.DataFrame(
        [{
            "survival": survival,
            "total_tpa": total_tpa,
            "sp1": sp1,
            "sp2": sp2,
            "sp3": sp3,
            "sp4": sp4,
            "si": si,
        }]
    )
    df_out = m.predict(df_in)
    return df_out

