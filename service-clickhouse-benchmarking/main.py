#!/usr/bin/env python3
import os
import re
import json
import time
import random
import logging
import statistics
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime

import pandas as pd
import requests
from requests.auth import HTTPBasicAuth
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BenchmarkConfig:
    clickhouse_host: str = os.getenv("CLICKHOUSE_HOST", "localhost")
    clickhouse_port: int = int(os.getenv("CLICKHOUSE_PORT", "8123"))
    clickhouse_user: str = os.getenv("CLICKHOUSE_USER", "default")
    clickhouse_password: str = os.getenv("CLICKHOUSE_PASSWORD", "")
    clickhouse_database: str = os.getenv("CLICKHOUSE_DATABASE", "clients_transactions")

    table_pattern: str = r"^clients_transactions\.transactions_(slow|fast)_.*$"
    scripts_dir: Path = Path("analytics-scripts")
    results_dir: Path = Path("analytics-results")
    csvs_dir: Path = Path("analytics-results/csvs")

    query_limit: int = 5
    repetitions: int = 40
    warmup_runs: int = 3


@dataclass
class QueryRun:
    execution_time_ms: float
    rows_read: int
    bytes_read: int


@dataclass
class QueryResult:
    query_name: str
    table_name: str
    runs: List[QueryRun] = field(default_factory=list)
    result_df: pd.DataFrame = field(default_factory=pd.DataFrame)
    error: Optional[str] = None

    @property
    def client_times(self) -> List[float]:
        return [r.execution_time_ms for r in self.runs]

    @property
    def mean_time(self) -> float:
        return statistics.mean(self.client_times) if self.client_times else 0.0

    @property
    def median_time(self) -> float:
        return statistics.median(self.client_times) if self.client_times else 0.0

    @property
    def p90_time(self) -> float:
        if not self.client_times:
            return 0.0
        return float(np.percentile(self.client_times, 90))

    @property
    def p95_time(self) -> float:
        if not self.client_times:
            return 0.0
        return float(np.percentile(self.client_times, 95))

    @property
    def stdev_time(self) -> float:
        return statistics.stdev(self.client_times) if len(self.client_times) > 1 else 0.0

    @property
    def ci95_low(self) -> float:
        if len(self.client_times) < 2:
            return self.mean_time
        sem = self.stdev_time / (len(self.client_times) ** 0.5)
        return self.mean_time - 1.96 * sem

    @property
    def ci95_high(self) -> float:
        if len(self.client_times) < 2:
            return self.mean_time
        sem = self.stdev_time / (len(self.client_times) ** 0.5)
        return self.mean_time + 1.96 * sem

    @property
    def median_rows_read(self) -> int:
        if not self.runs:
            return 0
        return int(statistics.median([r.rows_read for r in self.runs]))

    @property
    def median_bytes_read(self) -> int:
        if not self.runs:
            return 0
        return int(statistics.median([r.bytes_read for r in self.runs]))


@dataclass
class TableReport:
    table_name: str
    table_schema: str
    results: List[QueryResult] = field(default_factory=list)


class ClickHouseHttpClient:
    def __init__(self, host: str, port: int, user: str, password: str, database: str):
        self.base_url = f"http://{host}:{port}"
        self.auth = HTTPBasicAuth(user, password) if user else None
        self.database = database
        self.session = requests.Session()

    def execute(self, query: str, params: Optional[Dict] = None) -> List[tuple]:
        response = self.session.post(
            self.base_url,
            auth=self.auth,
            params={"database": self.database, **(params or {})},
            data=query.encode("utf-8"),
            timeout=300,
        )
        response.raise_for_status()
        text = response.text.strip()
        if not text:
            return []
        return [tuple(line.split("\t")) for line in text.split("\n")]

    def execute_with_stats(self, query: str) -> Tuple[List[tuple], Dict[str, Any]]:
        response = self.session.post(
            self.base_url,
            auth=self.auth,
            params={"database": self.database, "default_format": "TSV"},
            data=query.encode("utf-8"),
            timeout=300,
        )
        response.raise_for_status()
        text = response.text.strip()
        rows = []
        if text:
            rows = [tuple(line.split("\t")) for line in text.split("\n")]

        summary_header = response.headers.get("X-ClickHouse-Summary", "{}")
        try:
            stats = json.loads(summary_header)
        except json.JSONDecodeError:
            stats = {}

        return rows, {
            "rows_read": int(stats.get("read_rows", 0)),
            "bytes_read": int(stats.get("read_bytes", 0)),
        }

    def execute_with_names(self, query: str) -> Tuple[List[tuple], List[str]]:
        response = self.session.post(
            self.base_url,
            auth=self.auth,
            params={
                "database": self.database,
                "default_format": "TSVWithNamesAndTypes",
            },
            data=query.encode("utf-8"),
            timeout=300,
        )
        response.raise_for_status()
        text = response.text.strip()
        if not text:
            return [], []

        lines = text.split("\n")
        if len(lines) < 2:
            return [], []

        col_names = lines[0].split("\t")
        rows = []
        for line in lines[2:]:
            if line.strip():
                rows.append(tuple(line.split("\t")))
        return rows, col_names

    def ping(self) -> bool:
        try:
            response = self.session.get(self.base_url, auth=self.auth, timeout=5)
            return response.status_code == 200
        except requests.RequestException:
            return False


def discover_tables(client: ClickHouseHttpClient, pattern: str) -> List[str]:
    tables_raw = client.execute("SHOW TABLES FROM clients_transactions")
    table_names = [f"clients_transactions.{row[0]}" for row in tables_raw]
    regex = re.compile(pattern)
    matched = [t for t in table_names if regex.match(t)]
    logger.info(f"Found {len(matched)} tables: {', '.join(matched)}")
    return matched


def get_table_schema(client: ClickHouseHttpClient, table_name: str) -> str:
    try:
        result = client.execute(f"SHOW CREATE TABLE {table_name}")
        if result:
            return result[0][0]
    except Exception as e:
        logger.warning(f"Could not get schema for {table_name}: {e}")
    return "Schema unavailable"


def load_query_scripts(scripts_dir: Path) -> Dict[str, str]:
    scripts = {}
    for sql_file in sorted(scripts_dir.glob("*.sql")):
        content = sql_file.read_text(encoding="utf-8").strip()
        scripts[sql_file.stem] = content
    logger.info(f"Loaded {len(scripts)} query scripts")
    return scripts


def wait_for_data(
    client: ClickHouseHttpClient,
    tables: List[str],
    max_wait: int = 300,
    poll_interval: int = 5,
    stable_rounds: int = 3,
) -> bool:
    """Wait until Kafka data is fully replicated into all destination tables.

    Previous implementation queried a non-existent ``lag`` column of
    ``system.kafka_consumers`` and ignored the ``tables`` argument, so it
    either returned immediately on an empty ``kafka_consumers`` snapshot
    (zero rows ingested yet) or always hit the timeout.

    New logic polls ``SELECT count()`` on the destination MergeTree tables
    (the ``tables`` discovered for benchmarking, filled via Kafka Engine +
    Materialized View) and returns only when:
      * every table holds > 0 rows,
      * counts are equal across tables (each consumer group read the topic fully),
      * counts are stable for ``stable_rounds`` consecutive polls.
    """
    if not tables:
        logger.warning("wait_for_data: no tables to wait for, skipping")
        return False

    logger.info(f"Waiting for Kafka data in {len(tables)} tables: {', '.join(tables)}...")
    start_time = time.time()
    stable_polls = 0
    last_counts: Dict[str, int] = {}

    while time.time() - start_time < max_wait:
        elapsed = time.time() - start_time
        try:
            counts: Dict[str, int] = {}
            for table_name in tables:
                rows = client.execute(f"SELECT count() FROM {table_name}")
                counts[table_name] = int(rows[0][0]) if rows else 0

            counts_str = ", ".join(f"{t}={c}" for t, c in counts.items())
            logger.info(f"  [{elapsed:.0f}s] rows: {counts_str}")

            values = list(counts.values())
            if all(v > 0 for v in values) and len(set(values)) == 1:
                if last_counts == counts:
                    stable_polls += 1
                else:
                    stable_polls = 1
                last_counts = counts
                if stable_polls >= stable_rounds:
                    logger.info(
                        f"All Kafka messages consumed: "
                        f"each table holds {values[0]} rows "
                        f"(stable for {stable_polls} polls)"
                    )
                    return True
            else:
                stable_polls = 0
                last_counts = counts
        except Exception as e:
            logger.info(f"  [{elapsed:.0f}s] tables not ready yet: {e}")
            stable_polls = 0

        time.sleep(poll_interval)

    logger.warning(
        f"Timeout waiting for Kafka consumption after {max_wait}s "
        f"(last counts: {last_counts})"
    )
    return False


def run_benchmarks(
    client: ClickHouseHttpClient,
    tables: List[str],
    scripts: Dict[str, str],
    cfg: BenchmarkConfig,
) -> List[TableReport]:
    """Run interleaved benchmarks with randomized table order per round."""
    rng = random.Random(42)

    wait_for_data(client, tables)

    table_reports: List[TableReport] = []
    for table_name in tables:
        schema = get_table_schema(client, table_name)
        table_reports.append(TableReport(table_name=table_name, table_schema=schema))

    for table_name in tables:
        count = client.execute(f"SELECT count() FROM {table_name}")
        logger.info(f"Table {table_name}: {count[0][0]} rows")

    for query_name, query_sql in scripts.items():
        logger.info(f"\nBenchmarking query: {query_name}")

        # Warmup
        logger.info(f"  Warming up ({cfg.warmup_runs} runs per table)...")
        for table_name in tables:
            formatted = query_sql.replace("PLACEHOLDER", table_name)
            for _ in range(cfg.warmup_runs):
                try:
                    client.execute_with_stats(formatted)
                except Exception:
                    pass

        # Collect runs
        runs_by_table: Dict[str, List[QueryRun]] = {t: [] for t in tables}

        for rep in range(cfg.repetitions):
            round_tables = tables.copy()
            rng.shuffle(round_tables)

            for table_name in round_tables:
                formatted = query_sql.replace("PLACEHOLDER", table_name)

                start = time.perf_counter()
                try:
                    _, stats = client.execute_with_stats(formatted)
                    elapsed = (time.perf_counter() - start) * 1000
                except Exception as e:
                    logger.error(f"  {table_name} run {rep+1} failed: {e}")
                    continue

                runs_by_table[table_name].append(QueryRun(
                    execution_time_ms=round(elapsed, 2),
                    rows_read=stats["rows_read"],
                    bytes_read=stats["bytes_read"],
                ))
                logger.info(f"  {table_name} run {rep+1}/{cfg.repetitions}: {elapsed:.1f} ms")

        # Build QueryResult objects for this query
        for table_report in table_reports:
            table_name = table_report.table_name
            runs = runs_by_table.get(table_name, [])

            formatted = query_sql.replace("PLACEHOLDER", table_name)
            try:
                preview_data, col_names = client.execute_with_names(f"{formatted} LIMIT {cfg.query_limit}")
                result_df = pd.DataFrame(preview_data, columns=col_names) if preview_data and col_names else pd.DataFrame()
            except Exception:
                result_df = pd.DataFrame()

            if runs:
                table_report.results.append(QueryResult(
                    query_name=query_name,
                    table_name=table_name,
                    runs=runs,
                    result_df=result_df,
                ))

    return table_reports


def save_csv_result(result: QueryResult, csvs_dir: Path) -> Path:
    safe_table = result.table_name.replace(".", "_")
    filepath = csvs_dir / f"{safe_table}_{result.query_name}.csv"
    result.result_df.to_csv(filepath, index=False)
    return filepath


def generate_scatter_plots(
    table_reports: List[TableReport],
    repetitions: int,
    results_dir: Path,
) -> List[Path]:
    generated = []

    all_queries = sorted({
        r.query_name
        for report in table_reports
        for r in report.results
    })

    for query_name in all_queries:
        results_for_query = [
            r
            for report in table_reports
            for r in report.results
            if r.query_name == query_name and r.error is None and r.runs
        ]
        if not results_for_query:
            continue

        labels = [r.table_name.split(".")[-1] for r in results_for_query]
        x_positions = np.arange(len(labels))
        colors = plt.cm.Set2(range(len(labels)))

        fig, ax = plt.subplots(figsize=(12, 7))

        for idx, result in enumerate(results_for_query):
            times = result.client_times
            color = colors[idx]

            jitter = np.random.uniform(-0.12, 0.12, size=len(times))
            ax.scatter(
                x_positions[idx] + jitter,
                times,
                alpha=0.7,
                s=70,
                color=color,
                edgecolors="white",
                linewidth=0.5,
                zorder=3,
            )

            ax.scatter(
                x_positions[idx],
                result.mean_time,
                s=200,
                color=color,
                marker="D",
                edgecolors="black",
                linewidth=1.5,
                zorder=4,
            )

            ax.hlines(
                result.median_time,
                x_positions[idx] - 0.25,
                x_positions[idx] + 0.25,
                colors="black",
                linestyles="--",
                linewidth=2,
                zorder=5,
            )

            ax.vlines(
                x_positions[idx],
                result.ci95_low,
                result.ci95_high,
                colors="black",
                linewidth=1.5,
                alpha=0.6,
                zorder=2,
            )
            for y in (result.ci95_low, result.ci95_high):
                ax.hlines(
                    y,
                    x_positions[idx] - 0.1,
                    x_positions[idx] + 0.1,
                    colors="black",
                    linewidth=1.5,
                    alpha=0.6,
                    zorder=2,
                )

        ax.legend(
            handles=[
                plt.Line2D([0], [0], marker="D", color="w", markerfacecolor="gray",
                           markeredgecolor="black", markersize=10, label="Mean"),
                plt.Line2D([0], [0], color="black", linestyle="--", linewidth=2, label="Median"),
                plt.Line2D([0], [0], color="black", linewidth=1.5, alpha=0.6, label="95% CI"),
            ],
            loc="upper left",
            fontsize=9,
        )
        ax.set_xlabel("Table", fontsize=11)
        ax.set_ylabel("Execution Time (ms)", fontsize=11)
        ax.set_title(
            f"Query: {query_name} ({repetitions} runs per table)\n"
            "Diamond = Mean, Dashed = Median, Vertical bar = 95% CI",
            fontsize=12,
            fontweight="bold",
        )
        ax.set_xticks(x_positions)
        ax.set_xticklabels(labels, rotation=30, ha="right")
        ax.grid(axis="y", alpha=0.3)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

        plt.tight_layout()
        plot_path = results_dir / f"benchmark_query_{query_name}.png"
        plt.savefig(plot_path, dpi=150, bbox_inches="tight")
        plt.close()

        logger.info(f"Plot saved: {plot_path.name}")
        generated.append(plot_path)

    return generated


def generate_markdown_report(
    table_reports: List[TableReport],
    chart_paths: List[Path],
    repetitions: int,
    results_dir: Path,
) -> Path:
    report_path = results_dir / "benchmark_report.md"

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("# ClickHouse Analytical Queries Benchmark Report\n\n")
        f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Repetitions per query: {repetitions}\n\n---\n\n")

        for report in table_reports:
            f.write(f"## Table: `{report.table_name}`\n\n")
            f.write("```sql\n")
            f.write(report.table_schema.strip())
            f.write("\n```\n\n")

            for result in report.results:
                f.write(f"### `{result.query_name}`\n\n")
                if result.error:
                    f.write(f"ERROR: {result.error}\n\n")
                    continue

                f.write(
                    f"- Runs: {len(result.runs)}\n"
                    f"- Mean: {result.mean_time:.2f} ms\n"
                    f"- Median: {result.median_time:.2f} ms\n"
                    f"- P90: {result.p90_time:.2f} ms\n"
                    f"- P95: {result.p95_time:.2f} ms\n"
                    f"- Std Dev: {result.stdev_time:.2f} ms\n"
                    f"- 95% CI: [{result.ci95_low:.2f}, {result.ci95_high:.2f}] ms\n"
                    f"- Min: {min(result.client_times):.2f} ms\n"
                    f"- Max: {max(result.client_times):.2f} ms\n"
                    f"- Rows Read (median): {result.median_rows_read}\n"
                    f"- Bytes Read (median): {result.median_bytes_read}\n\n"
                )

                if not result.result_df.empty:
                    f.write(result.result_df.to_markdown(index=False))
                    f.write("\n\n")

            f.write("---\n\n")

        f.write("## Summary (median ms)\n\n")
        summary_data = []
        for report in table_reports:
            row = {"Table": report.table_name.split(".")[-1]}
            for result in report.results:
                if result.error:
                    row[result.query_name] = "ERROR"
                else:
                    row[result.query_name] = (
                        f"{result.median_time:.2f} "
                        f"[{result.ci95_low:.2f}, {result.ci95_high:.2f}]"
                    )
            summary_data.append(row)

        if summary_data:
            f.write(pd.DataFrame(summary_data).to_markdown(index=False))
            f.write("\n\n")

        if chart_paths:
            f.write("## Charts\n\n")
            for p in chart_paths:
                f.write(f"### {p.name}\n\n![{p.name}]({p.name})\n\n")

    logger.info(f"Report saved: {report_path.name}")
    return report_path


def main():
    cfg = BenchmarkConfig()

    cfg.csvs_dir.mkdir(parents=True, exist_ok=True)
    cfg.results_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"Connecting to ClickHouse at {cfg.clickhouse_host}:{cfg.clickhouse_port}")

    try:
        client = ClickHouseHttpClient(
            host=cfg.clickhouse_host,
            port=cfg.clickhouse_port,
            user=cfg.clickhouse_user,
            password=cfg.clickhouse_password,
            database=cfg.clickhouse_database,
        )
        if not client.ping():
            raise ConnectionError("ClickHouse ping failed")
        logger.info("Connected")
    except Exception as e:
        logger.error(f"Connection failed: {e}")
        return 1

    tables = discover_tables(client, cfg.table_pattern)
    if not tables:
        logger.error("No tables found")
        return 1

    scripts = load_query_scripts(cfg.scripts_dir)
    if not scripts:
        logger.error("No SQL scripts found")
        return 1

    table_reports = run_benchmarks(client, tables, scripts, cfg)

    for result in [r for tr in table_reports for r in tr.results]:
        save_csv_result(result, cfg.csvs_dir)

    chart_paths = generate_scatter_plots(table_reports, cfg.repetitions, cfg.results_dir)
    generate_markdown_report(table_reports, chart_paths, cfg.repetitions, cfg.results_dir)

    logger.info("\nDone")
    return 0


if __name__ == "__main__":
    exit(main())
