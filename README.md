# MGH Patient Encounter Analytics (Streamlit)

Dashboard over synthetic data for ~1,000 patients of Massachusetts General Hospital (2011–2022).

It answers:
1. How many patients were **admitted / readmitted** over time?
2. How long do patients **stay** on average?
3. What is the **average cost per visit**?
4. How many **procedures are covered by insurance**?

A **Data source** tab documents the files, metric definitions and lets you preview/download each table.

## Project layout

```
app.py                      Streamlit app
data/                       encounters.csv, procedures.csv, patients.csv, organizations.csv
requirements.txt
startup.sh                  Azure startup command
.streamlit/config.toml
.github/workflows/azure-deploy.yml
```

## Run locally

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

## Deploy to Azure App Service from GitHub

### 1. Push to GitHub
```bash
git init && git add . && git commit -m "Initial dashboard"
git branch -M main
git remote add origin https://github.com/<you>/<repo>.git
git push -u origin main
```

### 2. Create the Web App (Azure CLI)
```bash
az login
az group create -n rg-mgh-dashboard -l centralindia
az appservice plan create -n plan-mgh -g rg-mgh-dashboard --is-linux --sku B1
az webapp create -n <unique-app-name> -g rg-mgh-dashboard -p plan-mgh --runtime "PYTHON:3.11"

# startup command + build dependencies on Azure
az webapp config set -n <unique-app-name> -g rg-mgh-dashboard --startup-file "bash startup.sh"
az webapp config appsettings set -n <unique-app-name> -g rg-mgh-dashboard \
  --settings SCM_DO_BUILD_DURING_DEPLOYMENT=true WEBSITES_PORT=8000
# Streamlit needs websockets
az webapp config set -n <unique-app-name> -g rg-mgh-dashboard --web-sockets-enabled true
```
Use B1 or higher; the free F1 tier is too small and has no always-on/websocket support for Streamlit.

### 3. Connect GitHub Actions
1. Azure Portal → your Web App → **Overview → Download publish profile**.
2. GitHub repo → **Settings → Secrets and variables → Actions → New repository secret**
   Name: `AZURE_WEBAPP_PUBLISH_PROFILE`, value: the full contents of the downloaded file.
   (If the download is disabled, enable *SCM Basic Auth Publishing Credentials* under Web App → Configuration → General settings.)
3. Edit `AZURE_WEBAPP_NAME` in `.github/workflows/azure-deploy.yml`.
4. Push to `main`. The workflow deploys, and the app appears at `https://<unique-app-name>.azurewebsites.net`.

Alternative: Web App → **Deployment Center → GitHub** wires up a workflow for you; keep the startup command and app settings above.

### Troubleshooting
- Blank page / reconnecting loop: confirm WebSockets are on and the startup command is `bash startup.sh`.
- 502 on first load: first start installs dependencies; check **Log stream**.
- Data files are ~16 MB, which is fine for GitHub. For larger data, move them to Azure Blob Storage.

## Metric definitions
- **Admission**: encounter of the selected type(s), default `inpatient`.
- **Readmission**: admission starting 0–N days (default 30) after the same patient's previous admission ended.
- **Length of stay**: `STOP − START` in days.
- **Cost per visit**: `TOTAL_CLAIM_COST` per encounter.
- **Covered procedure**: the procedure's encounter has `PAYER_COVERAGE > 0` (the procedures file has no payer field of its own).
