#!/bin/bash
# Azure App Service (Linux) startup command for Streamlit
python -m streamlit run app.py \
  --server.port "${PORT:-8000}" \
  --server.address 0.0.0.0 \
  --server.headless true \
  --server.enableCORS false \
  --server.enableXsrfProtection false \
  --browser.gatherUsageStats false
