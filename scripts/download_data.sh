#!/usr/bin/env bash
# Download the Kaggle "Store Sales - Time Series Forecasting" (Corporacion Favorita) data
# and build the SQLite finance database.
#
# Prereqs:
#   1. Kaggle account -> Settings -> API -> "Create New Token" (gives username + key)
#   2. Join the competition once and accept the rules:
#      https://www.kaggle.com/competitions/store-sales-time-series-forecasting/rules
#   3. Set KAGGLE_USERNAME and KAGGLE_KEY (Codespaces secrets or `export ...`)
set -euo pipefail
cd "$(dirname "$0")/.."

mkdir -p data/raw
kaggle competitions download -c store-sales-time-series-forecasting -p data/raw
unzip -o data/raw/store-sales-time-series-forecasting.zip -d data/raw
rm -f data/raw/store-sales-time-series-forecasting.zip

rm -f data/processed/finance.db
python -m src.etl
echo "Done. Run: streamlit run app.py"
