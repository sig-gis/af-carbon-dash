import re
import os
from pathlib import Path

import mlflow
import mlflow.pyfunc

from utils.functions.mlflow_models import FVSCollectionModel


def parse_model_filename(pkl_path: Path):
    """
    Example file names:
      PN_v3_603_models.pkl --> (variant="PN", version="3", loccode="603")
      CR_v2_303_models.pkl --> (variant="CR", version="2", loccode="303")
    """
    m = re.match(r"([A-Z]{2})_v(\d+)_(\d+)_models\.pkl$", pkl_path.name)
    if not m:
        return None
    variant, version, loccode = m.groups()
    return variant, version, loccode


def get_model_name(variant: str, loccode: str) -> str:
    """
    MLflow registry model name convention.
    Example: af-carbon-dash-FVS-PN-603
    """
    return f"af-carbon-dash-FVS-{variant}-{loccode}"


def log_and_register_for_file(pkl_path: Path) -> None:
    parsed = parse_model_filename(pkl_path)
    if parsed is None:
        print(f"Skipping {pkl_path.name}: filename did not match pattern.")
        return

    variant, version, loccode = parsed
    model_name = get_model_name(variant, loccode)

    print(f"Logging & registering model for {pkl_path.name} -> {model_name}, v{version}")

    with mlflow.start_run(run_name=f"{model_name}-v{version}"):
        # register the pyfunc model
        model_info = mlflow.pyfunc.log_model(
            name="model",
            python_model=FVSCollectionModel(),
            artifacts={"models_pkl": str(pkl_path)},
            registered_model_name=model_name,
            infer_code_paths=True
        )
    
    print(f"Logged model to {model_info.model_uri}")
    print(f"Registered/updated model {model_name}")


def main():
    # # Optional: allow overriding tracking URI via env var
    # # export MLFLOW_TRACKING_URI="file:/full/path/to/mlruns" or a server URI
    # tracking_uri = os.getenv("MLFLOW_TRACKING_URI")
    # if tracking_uri:
    #     mlflow.set_tracking_uri(tracking_uri)
    #     print(f"Using MLflow tracking URI: {tracking_uri}")
    # else: # fall back on sensible default
    #     mlflow.set_tracking_uri("file:mlruns")
    mlflow.set_tracking_uri("file:mlruns")
    project_root = Path(__file__).resolve().parents[1]
    data_dir = project_root / "data"

    pkl_files = sorted(
        p for p in data_dir.glob("*_models.pkl") if p.is_file()
    )

    print(f"Using MLflow tracking URI: {mlflow.get_tracking_uri()}")
    print(f"Found {len(pkl_files)} model files:")
    for p in pkl_files:
        print(f" - {p.name}")

    for p in pkl_files:
        log_and_register_for_file(p)


if __name__ == "__main__":
    # Lock all model dependencies (including transitive) at log time so that
    # the resulting MLflow models are fully reproducible across environments.
    # See: MLFLOW_LOCK_MODEL_DEPENDENCIES in the MLflow docs.
    # https://mlflow.org/docs/latest/ml/model/dependencies/#saving-extra-code-with-an-mlflow-model
    os.environ["MLFLOW_LOCK_MODEL_DEPENDENCIES"] = "true"
    main()
