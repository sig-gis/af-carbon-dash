# from quarto import render

# render("report.ipynb",
#        output_file="reports/example_report.pdf")


# Run this in cmd to activate the the venv and generate the report
# ..\.venv\Scripts\activate
# python gen-reports.py


import pandas as pd
import os
import subprocess
import re
import datetime

# timestamp string
timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")

# the dataset
df = pd.read_csv("data/credits_proforma.csv")

# column to loop over
group_col = "Protocol"
group_values = df[group_col].unique()

# ensure reports folder exists
os.makedirs("reports", exist_ok=True)

print("Rendering combined report...")
subprocess.run([
    "quarto", "render", "report.ipynb",
    "--to", "typst-pdf",
    "--output-dir", "reports",
    "--output", f"report_{timestamp}.pdf",
    "--execute"
# #   The lines below were useful when exporting the report as html
#     "--execute-echo", "false",     # hide code execution
#     "--execute-warning", "false",  # hide warnings
#     "--execute-message", "false"   # hide messages
])