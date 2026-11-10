"""
Massachusetts General Hospital - Patient Encounters Dashboard
Synthetic data (Synthea) on ~1k patients, 2011-2022.
Run locally:  streamlit run app.py
"""
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
BASE_DIR = Path(__file__).parent


def find_csv(name: str) -> Path:
    """Find <name>.csv in data/ or the repo root, ignoring letter case."""
    for folder in (BASE_DIR / "data", BASE_DIR / "Data", BASE_DIR):
        if folder.is_dir():
            for p in folder.glob("*.csv"):
                if p.name.lower() == f"{name}.csv":
                    return p
    raise FileNotFoundError(
        f"{name}.csv not found. Put the four CSVs in a 'data' folder next to app.py."
    )

st.set_page_config(
    page_title="MGH Patient Analytics",
    page_icon="🏥",
    layout="wide",
)

# --------------------------------------------------------------------------
# Data loading
# --------------------------------------------------------------------------


@st.cache_data(show_spinner="Loading data...")
def load_data():
    enc = pd.read_csv(find_csv("encounters"), encoding="utf-8-sig")
    proc = pd.read_csv(find_csv("procedures"), encoding="utf-8-sig")
    pat = pd.read_csv(find_csv("patients"), encoding="utf-8-sig")
    org = pd.read_csv(find_csv("organizations"), encoding="utf-8-sig")

    for df in (enc, proc):
        for col in ("START", "STOP"):
            df[col] = pd.to_datetime(df[col], utc=True).dt.tz_convert(None)

    enc = enc.rename(columns={"Id": "ENCOUNTER_ID"})
    enc["LOS_DAYS"] = (enc["STOP"] - enc["START"]).dt.total_seconds() / 86400
    enc["YEAR"] = enc["START"].dt.year
    enc["MONTH"] = enc["START"].dt.to_period("M").dt.to_timestamp()
    enc["PAYER_SHORT"] = "Payer " + enc["PAYER"].str[:6]

    pat = pat.rename(columns={"Id": "PATIENT"})
    org = org.rename(columns={"Id": "ORGANIZATION"})
    return enc, proc, pat, org


def flag_admissions(enc: pd.DataFrame, admit_classes, window_days: int) -> pd.DataFrame:
    """Return admission rows with a READMISSION flag.

    Readmission = the patient's next admission starts 0..window_days days
    after the previous admission ended (overlapping records are not counted).
    """
    adm = enc[enc["ENCOUNTERCLASS"].isin(admit_classes)].sort_values(["PATIENT", "START"]).copy()
    prev_stop = adm.groupby("PATIENT")["STOP"].shift()
    adm["GAP_DAYS"] = (adm["START"] - prev_stop).dt.total_seconds() / 86400
    adm["READMISSION"] = adm["GAP_DAYS"].between(0, window_days)
    return adm


enc_all, proc_all, patients, orgs = load_data()
hospital = orgs.iloc[0]["NAME"].title()

# --------------------------------------------------------------------------
# Sidebar filters
# --------------------------------------------------------------------------
st.sidebar.title("🏥 Filters")

min_year, max_year = int(enc_all["YEAR"].min()), int(enc_all["YEAR"].max())
year_range = st.sidebar.slider("Year range", min_year, max_year, (min_year, max_year))

all_classes = sorted(enc_all["ENCOUNTERCLASS"].unique())
visit_classes = st.sidebar.multiselect(
    "Encounter types (cost & procedure analysis)", all_classes, default=all_classes
)
admit_classes = st.sidebar.multiselect(
    "Counts as an admission",
    all_classes,
    default=["inpatient"],
    help="Admissions and length of stay are calculated on these encounter types.",
)
window = st.sidebar.slider(
    "Readmission window (days)", 7, 90, 30,
    help="A readmission is an admission that starts within this many days of the patient's previous discharge.",
)
exclude_outliers = st.sidebar.checkbox(
    "Exclude stays longer than 30 days", value=False,
    help="A few synthetic stays last for months and skew the average.",
)
freq = st.sidebar.radio("Time granularity", ["Monthly", "Yearly"], horizontal=True)

if not admit_classes or not visit_classes:
    st.warning("Select at least one encounter type in each sidebar list.")
    st.stop()

in_range = enc_all["YEAR"].between(*year_range)
enc = enc_all[in_range & enc_all["ENCOUNTERCLASS"].isin(visit_classes)]
adm = flag_admissions(enc_all, admit_classes, window)
adm = adm[adm["YEAR"].between(*year_range)]  # flag on full history, then filter
if exclude_outliers:
    adm = adm[adm["LOS_DAYS"] <= 30]

proc = proc_all.merge(
    enc[["ENCOUNTER_ID", "PAYER_SHORT", "ENCOUNTERCLASS", "YEAR", "TOTAL_CLAIM_COST", "PAYER_COVERAGE"]],
    left_on="ENCOUNTER", right_on="ENCOUNTER_ID", how="inner",
)
proc["COVERAGE_STATUS"] = "Not covered"
proc.loc[proc["PAYER_COVERAGE"] > 0, "COVERAGE_STATUS"] = "Partially covered"
proc.loc[
    (proc["PAYER_COVERAGE"] > 0) & (proc["PAYER_COVERAGE"] >= proc["TOTAL_CLAIM_COST"]),
    "COVERAGE_STATUS",
] = "Fully covered"
proc["COVERED"] = proc["PAYER_COVERAGE"] > 0

period_col = "MONTH" if freq == "Monthly" else "YEAR"
COLORS = {"primary": "#1f77b4", "accent": "#d62728", "muted": "#9aa5b1", "good": "#2ca02c"}

# --------------------------------------------------------------------------
# Header + KPIs
# --------------------------------------------------------------------------
st.title(f"{hospital} — Patient Encounter Analytics")
st.caption(
    f"Synthetic data · {patients.shape[0]:,} patients · {enc_all['START'].min():%b %Y} – "
    f"{enc_all['START'].max():%b %Y} · showing {year_range[0]}–{year_range[1]}"
)

n_adm = len(adm)
n_readm = int(adm["READMISSION"].sum())
readm_rate = n_readm / n_adm if n_adm else 0
avg_los = adm["LOS_DAYS"].mean() if n_adm else float("nan")
avg_cost = enc["TOTAL_CLAIM_COST"].mean() if len(enc) else float("nan")
cov_pct = proc["COVERED"].mean() if len(proc) else float("nan")

k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Admissions", f"{n_adm:,}")
k2.metric(f"Readmissions ({window}d)", f"{n_readm:,}", f"{readm_rate:.1%} of admissions", delta_color="off")
k3.metric("Avg length of stay", f"{avg_los:.2f} days")
k4.metric("Avg cost per visit", f"${avg_cost:,.0f}")
k5.metric("Procedures covered", f"{cov_pct:.1%}", f"{int(proc['COVERED'].sum()):,} of {len(proc):,}", delta_color="off")

tab1, tab2, tab3, tab4, tab5 = st.tabs(
    ["📈 Admissions", "🛏️ Length of stay", "💵 Cost per visit", "🩺 Procedure coverage", "🗂️ Data source"]
)

# --------------------------------------------------------------------------
# 1. Admissions / readmissions over time
# --------------------------------------------------------------------------
with tab1:
    st.subheader("How many patients have been admitted or readmitted over time?")
    ts = (
        adm.groupby(period_col)
        .agg(
            Admissions=("ENCOUNTER_ID", "size"),
            Readmissions=("READMISSION", "sum"),
            Patients=("PATIENT", "nunique"),
        )
        .reset_index()
    )
    ts["Initial admissions"] = ts["Admissions"] - ts["Readmissions"]
    ts["Readmission rate"] = ts["Readmissions"] / ts["Admissions"]

    fig = go.Figure()
    fig.add_bar(x=ts[period_col], y=ts["Initial admissions"], name="Initial admissions", marker_color=COLORS["primary"])
    fig.add_bar(x=ts[period_col], y=ts["Readmissions"], name="Readmissions", marker_color=COLORS["accent"])
    fig.update_layout(
        barmode="stack", height=420, hovermode="x unified",
        yaxis_title="Admissions", xaxis_title=None, legend=dict(orientation="h", y=1.1),
    )
    st.plotly_chart(fig, width="stretch")

    c1, c2 = st.columns(2)
    with c1:
        yearly = ts if freq == "Yearly" else (
            adm.groupby("YEAR").agg(Admissions=("ENCOUNTER_ID", "size"), Readmissions=("READMISSION", "sum")).reset_index()
        )
        yearly = yearly.assign(Rate=yearly["Readmissions"] / yearly["Admissions"])
        fig = px.line(yearly, x="YEAR", y="Rate", markers=True, title=f"{window}-day readmission rate by year")
        fig.update_yaxes(tickformat=".0%", rangemode="tozero")
        fig.update_layout(height=340, xaxis_title=None, yaxis_title=None)
        st.plotly_chart(fig, width="stretch")
    with c2:
        uniq = adm.groupby("YEAR")["PATIENT"].nunique().reset_index(name="Unique patients")
        fig = px.bar(uniq, x="YEAR", y="Unique patients", title="Unique patients admitted per year")
        fig.update_layout(height=340, xaxis_title=None)
        st.plotly_chart(fig, width="stretch")

    repeat = adm.groupby("PATIENT").size()
    st.info(
        f"**{(repeat > 1).sum():,}** of **{len(repeat):,}** admitted patients were admitted more than once "
        f"(max {repeat.max() if len(repeat) else 0} admissions for a single patient)."
    )

# --------------------------------------------------------------------------
# 2. Length of stay
# --------------------------------------------------------------------------
with tab2:
    st.subheader("How long are patients staying in the hospital, on average?")
    m1, m2, m3 = st.columns(3)
    m1.metric("Mean stay", f"{adm['LOS_DAYS'].mean():.2f} days")
    m2.metric("Median stay", f"{adm['LOS_DAYS'].median():.2f} days")
    m3.metric("90th percentile", f"{adm['LOS_DAYS'].quantile(0.9):.2f} days")

    c1, c2 = st.columns(2)
    with c1:
        los_ts = adm.groupby(period_col)["LOS_DAYS"].mean().reset_index()
        fig = px.line(los_ts, x=period_col, y="LOS_DAYS", markers=(freq == "Yearly"),
                      title=f"Average length of stay ({freq.lower()})")
        fig.update_layout(height=360, xaxis_title=None, yaxis_title="Days")
        st.plotly_chart(fig, width="stretch")
    with c2:
        fig = px.histogram(adm[adm["LOS_DAYS"] <= 30], x="LOS_DAYS", nbins=30,
                           title="Distribution of stays (up to 30 days)")
        fig.update_layout(height=360, xaxis_title="Days", yaxis_title="Admissions")
        st.plotly_chart(fig, width="stretch")

    by_cls = (
        enc.groupby("ENCOUNTERCLASS")["LOS_DAYS"].agg(["count", "mean", "median"]).round(3)
        .rename(columns={"count": "Encounters", "mean": "Mean days", "median": "Median days"})
        .sort_values("Mean days", ascending=False)
    )
    st.markdown("**Length of stay by encounter type**")
    st.dataframe(by_cls, width="stretch")

# --------------------------------------------------------------------------
# 3. Cost per visit
# --------------------------------------------------------------------------
with tab3:
    st.subheader("How much is the average cost per visit?")
    st.caption("Cost per visit = `TOTAL_CLAIM_COST` of each encounter. Costs are heavily right-skewed, so the median is shown too.")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Mean cost / visit", f"${enc['TOTAL_CLAIM_COST'].mean():,.0f}")
    m2.metric("Median cost / visit", f"${enc['TOTAL_CLAIM_COST'].median():,.0f}")
    m3.metric("Avg paid by payer", f"${enc['PAYER_COVERAGE'].mean():,.0f}")
    m4.metric("Avg patient responsibility", f"${(enc['TOTAL_CLAIM_COST'] - enc['PAYER_COVERAGE']).mean():,.0f}")

    c1, c2 = st.columns(2)
    with c1:
        cost_cls = enc.groupby("ENCOUNTERCLASS")["TOTAL_CLAIM_COST"].mean().sort_values().reset_index()
        fig = px.bar(cost_cls, x="TOTAL_CLAIM_COST", y="ENCOUNTERCLASS", orientation="h",
                     title="Average cost per visit by encounter type")
        fig.update_layout(height=360, xaxis_title="USD", yaxis_title=None)
        fig.update_xaxes(tickprefix="$")
        st.plotly_chart(fig, width="stretch")
    with c2:
        cost_ts = enc.groupby("YEAR")["TOTAL_CLAIM_COST"].mean().reset_index()
        fig = px.line(cost_ts, x="YEAR", y="TOTAL_CLAIM_COST", markers=True, title="Average cost per visit by year")
        fig.update_layout(height=360, xaxis_title=None, yaxis_title="USD")
        fig.update_yaxes(tickprefix="$")
        st.plotly_chart(fig, width="stretch")

    split = (
        enc.groupby("YEAR")[["PAYER_COVERAGE", "TOTAL_CLAIM_COST"]].sum().reset_index()
        .assign(Patient=lambda d: d["TOTAL_CLAIM_COST"] - d["PAYER_COVERAGE"])
        .rename(columns={"PAYER_COVERAGE": "Paid by payer", "Patient": "Paid by patient / uncovered"})
    )
    fig = px.bar(split, x="YEAR", y=["Paid by payer", "Paid by patient / uncovered"],
                 title="Who pays? Total claim cost by year",
                 color_discrete_sequence=[COLORS["primary"], COLORS["muted"]])
    fig.update_layout(height=360, xaxis_title=None, yaxis_title="USD", legend_title=None)
    st.plotly_chart(fig, width="stretch")

# --------------------------------------------------------------------------
# 4. Procedures covered by insurance
# --------------------------------------------------------------------------
with tab4:
    st.subheader("How many procedures are covered by insurance?")
    st.caption(
        "The procedures file has no payer data of its own, so a procedure counts as **covered** when its "
        "encounter had a payer contribution (`PAYER_COVERAGE > 0`); **fully covered** when the payer paid the whole claim."
    )
    cnt = proc["COVERAGE_STATUS"].value_counts().reindex(
        ["Fully covered", "Partially covered", "Not covered"], fill_value=0
    )
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total procedures", f"{len(proc):,}")
    m2.metric("Covered (any amount)", f"{int(proc['COVERED'].sum()):,}")
    m3.metric("Fully covered", f"{cnt['Fully covered']:,}")
    m4.metric("Not covered", f"{cnt['Not covered']:,}")

    c1, c2 = st.columns(2)
    with c1:
        fig = px.pie(values=cnt.values, names=cnt.index, hole=0.5, title="Procedures by coverage status",
                     color=cnt.index,
                     color_discrete_map={"Fully covered": COLORS["good"], "Partially covered": COLORS["primary"],
                                         "Not covered": COLORS["muted"]})
        fig.update_layout(height=380)
        st.plotly_chart(fig, width="stretch")
    with c2:
        yr = proc.groupby("YEAR")["COVERED"].mean().reset_index()
        fig = px.line(yr, x="YEAR", y="COVERED", markers=True, title="% of procedures covered by year")
        fig.update_yaxes(tickformat=".0%", rangemode="tozero")
        fig.update_layout(height=380, xaxis_title=None, yaxis_title=None)
        st.plotly_chart(fig, width="stretch")

    by_payer = (
        proc.groupby("PAYER_SHORT")
        .agg(Procedures=("CODE", "size"), Covered=("COVERED", "sum"))
        .assign(**{"% covered": lambda d: d["Covered"] / d["Procedures"]})
        .sort_values("Procedures", ascending=False)
    )
    st.markdown("**Coverage by payer** (payer IDs are anonymised in the source data)")
    st.dataframe(by_payer.style.format({"% covered": "{:.1%}", "Procedures": "{:,}", "Covered": "{:,}"}),
                 width="stretch")

    top = (
        proc.groupby("DESCRIPTION")
        .agg(Procedures=("CODE", "size"), **{"% covered": ("COVERED", "mean")}, **{"Avg base cost": ("BASE_COST", "mean")})
        .sort_values("Procedures", ascending=False).head(15)
    )
    st.markdown("**Top 15 procedures**")
    st.dataframe(top.style.format({"% covered": "{:.1%}", "Avg base cost": "${:,.0f}", "Procedures": "{:,}"}),
                 width="stretch")

# --------------------------------------------------------------------------
# 5. Data source
# --------------------------------------------------------------------------
with tab5:
    st.subheader("Data source")
    st.markdown(
        f"""
**Synthetic data on ~1,000 patients of {hospital}, 2011–2022**, including patient demographics,
insurance coverage, and medical encounters and procedures. The records are generated
(Synthea-style) and do **not** describe real people.

| File | Rows | What it holds |
|---|---|---|
| `encounters.csv` | {len(enc_all):,} | Visits: class, dates, costs, payer coverage, reason |
| `procedures.csv` | {len(proc_all):,} | Procedures performed during an encounter, with base cost |
| `patients.csv` | {len(patients):,} | Demographics: birth/death date, gender, race, location |
| `organizations.csv` | {len(orgs):,} | The hospital: name, address, coordinates |

**Metric definitions**
- **Admission** – an encounter of the type(s) chosen in the sidebar (default: `inpatient`).
- **Readmission** – an admission starting 0–{window} days after the same patient's previous admission ended.
- **Length of stay** – `STOP − START` of the encounter, in days.
- **Cost per visit** – `TOTAL_CLAIM_COST` per encounter.
- **Covered procedure** – the procedure's encounter has `PAYER_COVERAGE > 0`.
        """
    )
    choice = st.selectbox("Preview a table", ["encounters", "procedures", "patients", "organizations"])
    frames = {"encounters": enc_all.drop(columns=["MONTH", "PAYER_SHORT"]), "procedures": proc_all,
              "patients": patients, "organizations": orgs}
    st.dataframe(frames[choice].head(200), width="stretch")
        raw = find_csv(choice).read_bytes()
    st.download_button(f"Download {choice}.csv", raw, file_name=f"{choice}.csv", mime="text/csv")
