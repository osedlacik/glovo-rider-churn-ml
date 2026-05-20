"""
Rider weekly KPI x Contacts x Churn — correlation matrix.

Fetches three BigQuery datasets, merges them at rider-week level, then produces:
  1. Full Pearson correlation heatmap (all features)
  2. Correlation-to-churn bar chart (features ranked by |r| with is_churned)

Usage examples:
    python src/features/correlation_matrix.py --limit 20000
    python src/features/correlation_matrix.py --skip-churn --limit 10000
    python src/features/correlation_matrix.py --output-dir reports/figures
"""

import argparse
import pathlib
import sys

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from google.cloud import bigquery

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

ROOT = pathlib.Path(__file__).parents[2]
FEATURES_SQL_DIR = ROOT / "sql" / "features"
CHURN_SQL_DIR    = ROOT / "sql" / "churn"

BILLING_PROJECT = "dhub-glovo"
CONTACT_TOP_N   = 12   # keep top N contact reasons as individual columns

# ---------------------------------------------------------------------------
# Feature columns (KPI side)
# ---------------------------------------------------------------------------

KPI_FEATURE_COLS = [
    "no_shows", "shifts_done", "all_shifts", "hours_worked", "perc_no_show",
    "total_orders_cpo", "total_bw_orders", "total_earnings",
    "cpo_local_currency", "net_cpo_lc", "perc_stacking",
    "avg_sp_distance_google", "avg_pd_distance_google", "avg_total_distance_google",
    "at_customer_time_in_minutes", "at_vendor_time_in_minutes", "cdt",
    "perc_reas", "earning_per_hour",
]

# Columns for which week-over-week delta features are computed
WOW_TREND_COLS = ["earning_per_hour", "cpo_local_currency", "net_cpo_lc"]

BASE_LABELS = {
    "no_shows":                       "No-shows",
    "shifts_done":                    "Shifts done",
    "all_shifts":                     "All shifts",
    "hours_worked":                   "Hours worked",
    "perc_no_show":                   "No-show %",
    "total_orders_cpo":               "Orders (CPO)",
    "total_bw_orders":                "BW orders",
    "total_earnings":                 "Total earnings",
    "cpo_local_currency":             "CPO (LC)",
    "net_cpo_lc":                     "Net CPO (LC)",
    "perc_stacking":                  "Stacking %",
    "avg_sp_distance_google":         "SP dist (km)",
    "avg_pd_distance_google":         "PD dist (km)",
    "avg_total_distance_google":      "Total dist (km)",
    "at_customer_time_in_minutes":    "At-customer (min)",
    "at_vendor_time_in_minutes":      "At-vendor (min)",
    "cdt":                            "CDT (min)",
    "perc_reas":                      "Reassignment %",
    "earning_per_hour":               "Earnings/hour",
    "earning_per_hour_delta_1w":      "Earnings/hour Δ1w",
    "earning_per_hour_delta_2w":      "Earnings/hour Δ2w",
    "cpo_local_currency_delta_1w":    "CPO (LC) Δ1w",
    "cpo_local_currency_delta_2w":    "CPO (LC) Δ2w",
    "net_cpo_lc_delta_1w":            "Net CPO Δ1w",
    "net_cpo_lc_delta_2w":            "Net CPO Δ2w",
    "tenure_days":                    "Tenure (days)",
    "days_since_last_slot":           "Days since last slot",
    "is_churned":                     "** CHURNED **",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_sql(path: pathlib.Path, limit: int | None = None) -> str:
    import re
    sql = path.read_text(encoding="utf-8").rstrip().rstrip(";")
    if limit:
        if re.search(r"^\s*DECLARE\s+", sql, re.MULTILINE | re.IGNORECASE):
            # BigQuery scripting SQL (DECLARE statements) cannot be wrapped in a
            # subquery — append LIMIT directly to the final SELECT instead.
            sql = sql + f"\nLIMIT {limit}"
        else:
            sql = f"SELECT * FROM (\n{sql}\n) LIMIT {limit}"
    return sql


def fetch(sql: str, project: str, label: str) -> pd.DataFrame:
    client = bigquery.Client(project=project)
    print(f"[BQ] Fetching {label} ...")
    df = client.query(sql).to_dataframe()
    print(f"      -> {len(df):,} rows, {len(df.columns)} cols")
    return df


def normalise_week(df: pd.DataFrame, col: str = "week") -> pd.DataFrame:
    if col in df.columns:
        df[col] = pd.to_datetime(df[col])
    return df

# ---------------------------------------------------------------------------
# Dataset builders
# ---------------------------------------------------------------------------

def build_kpi_rider_week(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate KPI (city/zone/rider/week) -> rider/week by averaging, then add WoW trend deltas."""
    available = [c for c in KPI_FEATURE_COLS if c in df.columns]
    df[available] = df[available].apply(pd.to_numeric, errors="coerce")
    agg = df.groupby(["rider_id", "week"])[available].mean().reset_index()
    agg = agg.sort_values(["rider_id", "week"])
    for col in WOW_TREND_COLS:
        if col not in agg.columns:
            continue
        g = agg.groupby("rider_id")[col]
        agg[f"{col}_delta_1w"] = agg[col] - g.shift(1)
        agg[f"{col}_delta_2w"] = agg[col] - g.shift(2)
    return agg


def build_contacts_rider_week(df: pd.DataFrame) -> pd.DataFrame:
    """Pivot flat contacts -> rider/week wide format (top N reasons + total)."""
    df["ticket_count"] = pd.to_numeric(df["ticket_count"], errors="coerce")

    top = (
        df.groupby("contact_reason_code")["ticket_count"]
        .sum()
        .nlargest(CONTACT_TOP_N)
        .index.tolist()
    )
    df["reason_bucket"] = df["contact_reason_code"].apply(
        lambda x: x if x in top else "other_reason"
    )

    pivot = (
        df.groupby(["rider_id", "week", "reason_bucket"])["ticket_count"]
        .sum()
        .unstack(fill_value=0)
        .reset_index()
    )

    reason_cols = [c for c in pivot.columns if c not in ("rider_id", "week")]
    pivot["total_tickets"] = pivot[reason_cols].sum(axis=1)
    pivot = pivot.rename(
        columns={c: f"contact_{c}" for c in reason_cols}
    )
    return pivot


def build_churn_rider_week(df: pd.DataFrame) -> pd.DataFrame:
    """Extract churn label columns, normalise week column name."""
    if "week_start" in df.columns and "week" not in df.columns:
        df = df.rename(columns={"week_start": "week"})
    keep = [c for c in ["rider_id", "week", "is_churned", "tenure_days"] if c in df.columns]
    out = df[keep].copy()
    for c in ["is_churned", "tenure_days"]:
        if c in out.columns:
            out[c] = pd.to_numeric(out[c], errors="coerce")
    return out.drop_duplicates(subset=["rider_id", "week"])


def build_churn_snapshot(df: pd.DataFrame) -> pd.DataFrame:
    """Build churn snapshot (one row per rider, no week column) for rider-level merge."""
    keep = [c for c in ["rider_id", "is_churned", "tenure_days", "days_since_last_slot"] if c in df.columns]
    out = df[keep].copy()
    for c in ["is_churned", "tenure_days", "days_since_last_slot"]:
        if c in out.columns:
            out[c] = pd.to_numeric(out[c], errors="coerce")
    return out.drop_duplicates(subset=["rider_id"])

# ---------------------------------------------------------------------------
# Merge
# ---------------------------------------------------------------------------

def _coerce_keys(df: pd.DataFrame) -> pd.DataFrame:
    """Normalise join keys so rider_id is always str and week is datetime64."""
    df = df.copy()
    if "rider_id" in df.columns:
        df["rider_id"] = df["rider_id"].astype(str)
    if "week" in df.columns:
        df["week"] = pd.to_datetime(df["week"])
    return df


def merge_all(
    kpi: pd.DataFrame,
    contacts: pd.DataFrame | None,
    churn: pd.DataFrame | None,
    churn_snapshot: bool = False,
) -> pd.DataFrame:
    merged = _coerce_keys(kpi)
    if contacts is not None and len(contacts):
        merged = merged.merge(_coerce_keys(contacts), on=["rider_id", "week"], how="left")
    if churn is not None and len(churn):
        churn_c = _coerce_keys(churn)
        key = ["rider_id"] if churn_snapshot else ["rider_id", "week"]
        merged = merged.merge(churn_c, on=key, how="left")
    return merged


def get_numeric_feature_cols(df: pd.DataFrame) -> list[str]:
    exclude = {"rider_id", "week", "segment", "hire_date", "first_delivery_date",
               "last_delivery_date", "last_active_week", "last_slot_date"}
    return [
        c for c in df.columns
        if c not in exclude and pd.api.types.is_numeric_dtype(df[c])
    ]

# ---------------------------------------------------------------------------
# Plots
# ---------------------------------------------------------------------------

def make_label_map(df: pd.DataFrame) -> dict:
    labels = dict(BASE_LABELS)
    for col in df.columns:
        if col.startswith("contact_") and col not in labels:
            reason = col.replace("contact_", "").replace("_", " ").title()
            labels[col] = f"Contact: {reason}"
    return labels


def plot_full_heatmap(corr: pd.DataFrame, labels: dict, out_path: str) -> None:
    n = len(corr)
    fig_size = max(12, n * 0.72)
    fig, ax = plt.subplots(figsize=(fig_size, fig_size * 0.88))

    mask_upper = np.triu(np.ones_like(corr, dtype=bool), k=1)
    display = [labels.get(c, c) for c in corr.columns]
    corr_d = corr.copy()
    corr_d.index = display
    corr_d.columns = display

    sns.heatmap(
        corr_d, mask=mask_upper,
        annot=True, fmt=".2f",
        cmap="RdYlGn", center=0, vmin=-1, vmax=1,
        linewidths=0.3, annot_kws={"size": 6.5},
        ax=ax,
    )
    ax.set_title(
        "Rider Weekly KPI + Contacts + Churn — Pearson Correlation\n(Poland, 2026-01-01+)",
        fontsize=13, pad=14,
    )
    plt.xticks(rotation=45, ha="right", fontsize=7)
    plt.yticks(rotation=0, fontsize=7)
    plt.tight_layout()
    pathlib.Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    print(f"Saved -> {out_path}")
    plt.close()


def plot_churn_correlation(
    df: pd.DataFrame, feature_cols: list[str], labels: dict, out_path: str
) -> None:
    """Horizontal bar chart — each feature's Pearson r with is_churned."""
    if "is_churned" not in df.columns or df["is_churned"].isna().all():
        print("[info] No churn labels available, skipping churn bar chart")
        return

    cols = [c for c in feature_cols if c != "is_churned"]
    numeric = df[cols + ["is_churned"]].apply(pd.to_numeric, errors="coerce")
    r = numeric.corr(method="pearson")["is_churned"].drop("is_churned").sort_values()

    display = [labels.get(c, c) for c in r.index]
    colors   = ["#d73027" if v > 0 else "#1a9850" for v in r.values]

    fig, ax = plt.subplots(figsize=(10, max(6, len(r) * 0.33)))
    ax.barh(display, r.values, color=colors, edgecolor="white", linewidth=0.4)
    ax.axvline(0, color="black", linewidth=0.8)
    ax.set_xlabel("Pearson r  (red = higher value -> more churn)", fontsize=10)
    ax.set_title(
        "Feature Correlation to CHURN (is_churned)\n(Poland, 2026-01-01+)",
        fontsize=13,
    )
    ax.grid(axis="x", alpha=0.3)
    plt.tight_layout()
    pathlib.Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    print(f"Saved -> {out_path}")
    plt.close()

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Rider correlation matrix")
    parser.add_argument("--limit",           type=int,  default=None,
                        help="Row limit per query (default: all rows)")
    parser.add_argument("--output-dir",      type=str,  default="reports/figures")
    parser.add_argument("--billing-project", type=str,  default=BILLING_PROJECT)
    parser.add_argument("--skip-contacts",    action="store_true")
    parser.add_argument("--skip-churn",       action="store_true")
    parser.add_argument("--churn-snapshot",   action="store_true",
                        help="Use fast single-pass churn snapshot instead of full weekly table")
    args = parser.parse_args()

    proj = args.billing_project
    lim  = args.limit

    # 1. KPI
    kpi_raw = fetch(load_sql(FEATURES_SQL_DIR / "rider_weekly_kpis.sql", lim), proj, "KPI")
    kpi_raw = normalise_week(kpi_raw)
    kpi     = build_kpi_rider_week(kpi_raw)

    # 2. Contacts
    contacts = None
    if not args.skip_contacts:
        contacts_raw = fetch(load_sql(FEATURES_SQL_DIR / "rider_weekly_contacts.sql", lim), proj, "Contacts")
        contacts_raw = normalise_week(contacts_raw)
        contacts = build_contacts_rider_week(contacts_raw)

    # 3. Churn
    churn = None
    use_snapshot = args.churn_snapshot
    if not args.skip_churn:
        if use_snapshot:
            churn_raw = fetch(load_sql(CHURN_SQL_DIR / "churn_snapshot_current.sql", lim), proj, "Churn (snapshot)")
            churn = build_churn_snapshot(churn_raw)
        else:
            churn_raw = fetch(load_sql(CHURN_SQL_DIR / "churn_rider_weekly_poland.sql", lim), proj, "Churn (weekly)")
            week_col  = "week" if "week" in churn_raw.columns else "week_start"
            churn_raw = normalise_week(churn_raw, col=week_col)
            churn     = build_churn_rider_week(churn_raw)

    # 4. Merge
    merged = merge_all(kpi, contacts, churn, churn_snapshot=use_snapshot)
    print(f"Merged: {len(merged):,} rows x {len(merged.columns)} cols")

    feature_cols = get_numeric_feature_cols(merged)
    labels       = make_label_map(merged)

    numeric_df = merged[feature_cols].apply(pd.to_numeric, errors="coerce")
    corr       = numeric_df.corr(method="pearson")

    out = args.output_dir

    # 5. Full heatmap
    plot_full_heatmap(corr, labels, f"{out}/correlation_matrix.png")

    # 6. Churn bar chart
    if not args.skip_churn:
        plot_churn_correlation(merged, feature_cols, labels, f"{out}/correlation_to_churn.png")


if __name__ == "__main__":
    main()
