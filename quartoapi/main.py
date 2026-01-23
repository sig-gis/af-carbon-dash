from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pathlib import Path
import subprocess
import datetime
import os
import pandas as pd
import tempfile
import shutil

from schemas import ReportRequest

app = FastAPI(title="Quarto Report Service")

QUARTO_DIR = Path("../quarto")  # Relative to this script's location

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/reports/generate")
def generate_report(req: ReportRequest = None):
    """
    Generate a PDF report using Quarto.
    If req is provided, generates temp CSVs from the data.
    Otherwise, uses existing data in quarto/data/.
    """
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")

    # Ensure reports folder exists
    reports_dir = QUARTO_DIR / "reports"
    reports_dir.mkdir(exist_ok=True)

    output_file = reports_dir / f"report_{timestamp}.pdf"

    # Change to quarto directory for execution
    original_cwd = os.getcwd()
    temp_dir = None

    try:
        os.chdir(QUARTO_DIR)

        if req:
            # Create temp data directory
            temp_dir = tempfile.mkdtemp()
            temp_data_dir = Path(temp_dir) / "data"
            temp_data_dir.mkdir()

            # Generate CSVs from request data
            pd.DataFrame(req.data.planting_design).to_csv(temp_data_dir / "planting_design.csv", index=False, header=None)
            pd.DataFrame(req.data.species_mix).to_csv(temp_data_dir / "species_mix.csv", index=False, header=None)
            pd.DataFrame(req.data.financial_options1).to_csv(temp_data_dir / "financial_options1.csv", index=False, header=None)
            pd.DataFrame(req.data.financial_options2).to_csv(temp_data_dir / "financial_options2.csv", index=False, header=None)
            pd.DataFrame(req.data.carbon).to_csv(temp_data_dir / "carbon.csv", index=False)
            # Save variant
            pd.DataFrame([{"variant": req.data.selected_variant}]).to_csv(temp_data_dir / "variant.csv", index=False)

            # Copy temp data to quarto data folder (or modify notebook to use temp dir)
            # For simplicity, copy to data/
            data_dir = Path("data")
            data_dir.mkdir(exist_ok=True)
            for file in temp_data_dir.glob("*.csv"):
                shutil.copy(file, data_dir / file.name)

        # Run quarto render
        result = subprocess.run([
            "quarto", "render", "report.ipynb",
            "--to", "typst-pdf",
            "--output-dir", "reports",
            "--output", f"report_{timestamp}.pdf",
            "--execute"
        ], capture_output=True, text=True)

        if result.returncode != 0:
            raise HTTPException(status_code=500, detail=f"Quarto render failed: {result.stderr}")

        # Return the PDF file
        return FileResponse(
            path=output_file,
            media_type='application/pdf',
            filename=f"report_{timestamp}.pdf"
        )

    finally:
        os.chdir(original_cwd)
        if temp_dir and Path(temp_dir).exists():
            shutil.rmtree(temp_dir)
