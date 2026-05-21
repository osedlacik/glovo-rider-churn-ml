from pathlib import Path
from google.cloud import bigquery

ROOT = Path(__file__).resolve().parents[1]
EXPORT_DIR = ROOT / "data" / "exports"
EXPORT_DIR.mkdir(parents=True, exist_ok=True)

JOBS = [
    (
        ROOT / "sql" / "churn" / "churn_riders_snapshot_count_poland.sql",
        EXPORT_DIR / "churn_riders_snapshot_count_poland_2026_to_today.csv",
    ),
    (
        ROOT / "sql" / "churn" / "churn_riders_snapshot_poland.sql",
        EXPORT_DIR / "churn_riders_snapshot_poland_2026_to_today.csv",
    ),
    (
        ROOT / "sql" / "churn" / "churn_riders_features_8w_poland.sql",
        EXPORT_DIR / "churn_riders_features_8w_poland_2026_to_today.csv",
    ),
]


def main() -> None:
    client = bigquery.Client()

    for sql_path, out_path in JOBS:
        sql = sql_path.read_text(encoding="utf-8")
        print(f"Running: {sql_path.name}")
        df = client.query(sql).to_dataframe()
        df.to_csv(out_path, index=False)
        print(f"Wrote {len(df):,} rows -> {out_path}")


if __name__ == "__main__":
    main()
