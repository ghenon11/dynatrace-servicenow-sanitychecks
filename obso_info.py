
#!/usr/bin/env python3
"""
Dynatrace DQL Query Runner – Consolidated dict output (no columns list)

Features:
- Executes DQL queries via Dynatrace Query APIs:
    * Default: Storage Execute API (/platform/storage/query/v1/query:execute)
    * Also compatible with Platform Query API (/platform/query/v2) response shape
- Supports both 'Api-Token' and 'Bearer' authentication modes
- Resilient JSON handling (diagnostics for empty/non-JSON responses)
- Retries with exponential backoff on 429/5xx
- Paging via nextToken for large result sets (supports top-level and result.nextToken)
- Consolidates results as:
    {
        "records": [ {field: value, ...}, ... ],
        "raw_first_page": { ...exact first API JSON... }
    }
  (No separate columns list.)
- Default outputs (activated automatically):
    * Save raw API JSON responses (first page + each paged response) to ./out/api_responses
    * Save records (list of dicts) as CSV to ./out/records.csv
    * Save records (list of dicts) as XLSX to ./out/records.xlsx
- CLI-configurable:
    * DQL query (inline or from file; supports .txt/.dql)
    * Timeframe (e.g., 'now()-24h' or '2025-01-01T00:00:00Z to now()')
    * Page size & server-side request timeout
    * Consolidated export (--output csv/json + --output-path) if needed
    * Override defaults:
        - --save-raw-json <dir>
        - --save-records-csv <path>
        - --save-records-xlsx <path>
- Logging to file and console with debug mode

Usage examples:
    # Using defaults (auto-save raw JSON + records CSV + records XLSX)
    python dynatrace_dql_runner.py --debug

    # Inline DQL and override CSV/XLSX paths
    python dynatrace_dql_runner.py --dql "fetch events | limit 50" \
        --save-records-csv ./out/events.csv \
        --save-records-xlsx ./out/events.xlsx

    # Load DQL from a text file
    python dynatrace_dql_runner.py --dql-file ./queries/my_query.txt --timeframe "now()-6h"

    # Optional consolidated export (records + raw_first_page) to JSON
    python dynatrace_dql_runner.py --output json --output-path ./out/consolidated.json

Config precedence:
    CLI > INI > Environment

INI example (dynatrace_sanity_checks.ini):
    [DYNATRACE]
    APP_URL = https://<tenant>.live.dynatrace.com
    TOKEN_PLATFORM_READ = <token>
    AUTH_MODE = api-token    # or bearer
"""

import os
import sys
import json
import time
import typing as t
import logging
import argparse
import configparser
import requests

# ---------------------------
# Defaults / constants
# ---------------------------
DEFAULT_DQL = "fetch logs | limit 10"
DEFAULT_TIMEFRAME = "now()-24h"
DEFAULT_PAGE_SIZE = 200
DEFAULT_TIMEOUT_MS = 60000
DEFAULT_CONFIG = "dynatrace_sanity_checks.ini"

# Default outputs (activated by default)
DEFAULT_SAVE_RAW_JSON_DIR = os.path.abspath("./data/api_responses")
DEFAULT_SAVE_RECORDS_CSV = os.path.abspath("./data/records.csv")
DEFAULT_SAVE_RECORDS_XLSX = os.path.abspath("./data/records.xlsx")


# ---------------------------
# Logging setup (file + console INFO)
# ---------------------------
def setup_logging(debug: bool) -> None:
    """
    Configure logging to write to a file and to the console.
    - File handler: DEBUG if --debug, else INFO
    - Console handler: always INFO (as requested)
    """
    file_level = logging.DEBUG if debug else logging.INFO
    console_level = logging.INFO

    # File handler
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        log_path = os.path.splitext(os.path.join(base_dir, os.path.basename(__file__)))[0] + ".log"
        fh = logging.FileHandler(log_path, mode="w", encoding="utf-8")
        fh.setLevel(file_level)
        fh.setFormatter(logging.Formatter('%(asctime)s::%(levelname)s::%(message)s'))
    except Exception:
        fh = None
        # If file logging fails, we still keep console logging
        sys.stderr.write("WARNING: failed to init file logging; continuing with console only.\n")

    # Console handler (INFO only)
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(console_level)
    ch.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))

    root = logging.getLogger()
    root.handlers = []
    # Root logger level should be the lowest we need to capture;
    # set to DEBUG so file handler can record debug    # set to DEBUG so file handler can record debug when enabled.
    root.setLevel(logging.DEBUG)

    if fh:
        root.addHandler(fh)


# ---------------------------
# Configuration
# ---------------------------
def load_config(path: str) -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    if os.path.isfile(path):
        cfg.read(path)
        logging.debug("Loaded config sections: %s", cfg.sections())
    else:
        logging.warning("Config file [%s] not found; falling back to environment/CLI.", path)
    return cfg

def resolve_settings(cfg: configparser.ConfigParser, args: argparse.Namespace) -> dict:
    # Use APP_URL (per your INI) → fallback to env var or CLI --url
    base_url = (
        args.url
        or cfg.get("DYNATRACE", "APP_URL", fallback=None)
        or os.environ.get("DYNATRACE_URL")
        or ""
    ).rstrip("/")

    token = (
        args.token
        or cfg.get("DYNATRACE", "TOKEN_PLATFORM_READ", fallback=None)
        or os.environ.get("DYNATRACE_TOKEN")
        or ""
    )

    auth_mode = (
        (args.auth_mode or
         cfg.get("DYNATRACE", "AUTH_MODE", fallback=None) or
         os.environ.get("DYNATRACE_AUTH_MODE") or
         "bearer")
    ).strip().lower()

    if auth_mode not in ("api-token", "bearer"):
        logging.warning("Unknown auth_mode '%s'; defaulting to 'api-token'", auth_mode)
        auth_mode = "api-token"

    # DQL source
    dql = args.dql or DEFAULT_DQL
    if args.dql_file:
        with open(args.dql_file, "r", encoding="utf-8") as f:
            dql = f.read().strip()

    # Basic validation
    missing = []
    if not base_url:
        missing.append("DYNATRACE_URL/APP_URL")
    if not token:
        missing.append("DYNATRACE_TOKEN/TOKEN_PLATFORM_READ")
    if missing:
        logging.error("Missing required configuration: %s", ", ".join(missing))
        sys.exit(1)

    # Defaults activated unless overridden
    save_raw_json_dir = args.save_raw_json or DEFAULT_SAVE_RAW_JSON_DIR
    save_records_csv = args.save_records_csv or DEFAULT_SAVE_RECORDS_CSV
    save_records_xlsx = args.save_records_xlsx or DEFAULT_SAVE_RECORDS_XLSX

    settings = {
        "base_url": base_url,
        "token": token,
        "auth_mode": auth_mode,
        "dql": dql,
        "timeframe": args.timeframe or DEFAULT_TIMEFRAME,
        "page_size": int(args.page_size if args.page_size else DEFAULT_PAGE_SIZE),
        "request_timeout_ms": int(args.timeout_ms if args.timeout_ms else DEFAULT_TIMEOUT_MS),
        "output": (args.output or "").lower(),
        "output_path": args.output_path or "",
        "print_rows": int(args.print_rows if args.print_rows else 50),
        "save_raw_json_dir": save_raw_json_dir,
        "save_records_csv": save_records_csv,
        "save_records_xlsx": save_records_xlsx,
    }
    return settings

# ---------------------------
# HTTP helpers
# ---------------------------
def build_headers(token: str, auth_mode: str) -> dict:
    if auth_mode == "bearer":
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
    return {
        "Authorization": f"Api-Token {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

def post_with_retries(
    url: str,
    headers: dict,
    payload: dict,
    timeout: t.Tuple[int, int] = (30, 120),
    max_retries: int = 5
) -> requests.Response:
    """
    POST with exponential backoff on 429/5xx. Returns the final response (may be error).
    """
    attempt = 0
    backoff = 0.75
    while True:
        try:
            resp = requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=timeout,
                allow_redirects=False
            )
            if resp.status_code in (429, 500, 502, 503, 504):
                attempt += 1
                if attempt > max_retries:
                    return resp
                sleep_for = backoff * (2 ** (attempt - 1))
                logging.warning(
                    "HTTP %s; retrying in %.1fs (attempt %d/%d)",
                    resp.status_code, sleep_for, attempt, max_retries
                )
                time.sleep(sleep_for)
                continue
            return resp
        except requests.RequestException as e:
            attempt += 1
            if attempt > max_retries:
                raise
            sleep_for = backoff * (2 ** (attempt - 1))
            logging.warning(
                "Request exception: %s; retrying in %.1fs (attempt %d/%d)",
                e, sleep_for, attempt, max_retries
            )
            time.sleep(sleep_for)

# ---------------------------
# Core query & normalization
# ---------------------------
def ensure_json_response(resp: requests.Response, context: str) -> dict:
    """
    Guard against empty/non-JSON bodies. Raises with useful diagnostics.
    """
    ct = (resp.headers.get("Content-Type") or "").lower()
    body_text = resp.text or ""
    preview = body_text[:1000]

    if not resp.ok:
        logging.error(
            "%s failed: HTTP %s\nContent-Type: %s\nHeaders: %s\nBody (first 1000 chars):\n%s",
            context, resp.status_code, ct, dict(resp.headers), preview
        )
        raise RuntimeError(f"{context} failed: HTTP {resp.status_code}: {preview}")

    if not body_text.strip():
        logging.error(
            "%s succeeded (HTTP %s) but body is empty. Content-Type: %s",
            context, resp.status_code, ct
        )
        raise RuntimeError(f"{context}: empty response body.")

    if "application/json" not in ct:
        logging.error(
            "%s expected JSON, got Content-Type: %s\nBody preview:\n%s",
            context, ct, preview
        )
        raise RuntimeError(f"{context}: non-JSON response.")

    try:
        logging.debug(f"Response: {resp.json()}")
        return resp.json()
    except json.JSONDecodeError:
        logging.error(
            "%s JSON parsing failed. Content-Type: %s\nBody:\n%s",
            context, ct, preview
        )
        raise

def save_raw_json(obj: dict, out_dir: str, basename: str) -> None:
    """
    Saves a JSON object to out_dir/basename.json (creates dir if needed).
    """
    if not out_dir:
        return
    try:
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, f"{basename}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        logging.info("Saved raw JSON response: %s", path)
    except Exception as e:
        logging.warning("Failed to save raw JSON to %s: %s", out_dir, e)

def normalize_records_to_dicts(parsed: dict) -> t.Tuple[t.List[str], t.List[dict]]:
    """
    Normalize Dynatrace responses into a list of dictionaries:
      - Platform Query: use 'results[*].columns' to build field names and map each row.
      - Grail Storage Execute: use 'result.records' which are already dicts.

    Returns:
      (field_names, records_as_dicts)
    """
    # Platform Query style
    if isinstance(parsed.get("results"), list) and parsed["results"]:
        first = parsed["results"][0]
        columns = first.get("columns", []) or []
        field_names = [c.get("name", "") for c in columns]
        records_as_dicts: t.List[dict] = []
        for rset in parsed.get("results", []):
            recs = rset.get("records", []) or []
            for row in recs:
                if isinstance(row, list):
                    rec_dict = {fn: (row[i] if i < len(row) else None) for i, fn in enumerate(field_names)}
                else:
                    rec_dict = {fn: None for fn in field_names}
                records_as_dicts.append(rec_dict)
        return field_names, records_as_dicts

    # Grail Storage Execute style
    if isinstance(parsed.get("result"), dict) and isinstance(parsed["result"].get("records"), list):
        obj_records: t.List[dict] = parsed["result"]["records"]
        if not obj_records:
            return [], []
        field_names = list(obj_records[0].keys())
        return field_names, obj_records

    # Fallback
    return [], []

def run_dql_query(
    base_url: str,
    token: str,
    auth_mode: str,
    dql: str,
    timeframe: str,
    request_timeout_ms: int,
    page_size: int,
    save_raw_json_dir: str = "",
) -> dict:
    # Default to Grail Storage Execute endpoint (aligns with observed response shape)
    endpoint = f"{base_url}/platform/storage/query/v1/query:execute"
    headers = build_headers(token, auth_mode)

    # First page
    body = {
        "query": dql,
        "timeframe": timeframe,
        "requestTimeoutMilliseconds": request_timeout_ms,
        "resultSetLimits": {"recordsPerResultSet": page_size},
    }
    logging.debug("POST %s payload=%s", endpoint, json.dumps(body))
    resp = post_with_retries(endpoint, headers, body)
    parsed = ensure_json_response(resp, context="Query")

    # Save raw first page JSON
    save_raw_json(parsed, save_raw_json_dir, "page_0")

    field_names, records_dicts = normalize_records_to_dicts(parsed)

    # nextToken may be top-level or under "result"
    next_token = parsed.get("nextToken") or (parsed.get("result", {}) or {}).get("nextToken")

    # Paging
    page_index = 1
    while next_token:
        next_body = {
            "nextToken": next_token,
            "requestTimeoutMilliseconds": request_timeout_ms,
        }
        logging.debug("Paging with nextToken...")
        follow = post_with_retries(endpoint, headers, next_body)
        follow_parsed = ensure_json_response(follow, context="Paging")

        # Save raw JSON for this page
        save_raw_json(follow_parsed, save_raw_json_dir, f"page_{page_index}")
        page_index += 1

        f2, r2 = normalize_records_to_dicts(follow_parsed)

        # If platform query columns change across pages, reconcile to first page field_names
        if f2 and field_names and f2 != field_names:
            logging.warning("Field names changed across pages; reconciling to initial set.")
            remapped = []
            for rec in r2:
                remapped.append({fn: rec.get(fn) for fn in field_names})
            r2 = remapped

        records_dicts.extend(r2)

        next_token = follow_parsed.get("nextToken") or (follow_parsed.get("result", {}) or {}).get("nextToken")
        time.sleep(0.2)  # gentle pacing

    consolidated = {
        "records": records_dicts,        # list of dicts
        "raw_first_page": parsed,        # exact JSON of first page for troubleshooting
    }
    return consolidated

# ---------------------------
# Output helpers
# ---------------------------
def pretty_print_table(consolidated: dict, max_rows: int = 40):
    records = consolidated.get("records", [])
    if not records:
        print("(no records)")
        return

    # Use keys from the first record for header
    col_names = list(records[0].keys())
    header = " | ".join(col_names)
    separator = "-" * (len(header) + 2)

    print(header)
    print(separator)
    for rec in records[:max_rows]:
        parts = ["" if rec.get(k) is None else str(rec.get(k)) for k in col_names]
        print(" | ".join(parts))
    if len(records) > max_rows:
        print(f"... ({len(records) - max_rows} more rows)")

def export_results(consolidated: dict, output: str, path: str):
    """
    Optional consolidated export via --output/--output-path:
    - JSON: writes {'records': [...], 'raw_first_page': {...}}
    - CSV: writes records list as rows (list-of-dicts)
    """
    if not output:
        return
    output = output.lower()
    if not path:
        logging.warning("Output requested but no --output-path provided; skipping export.")
        return
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)

    if output == "json":
        with open(path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "records": consolidated.get("records", []),
                    "raw_first_page": consolidated.get("raw_first_page", {}),
                },
                f,
                ensure_ascii=False,
                indent=2,
            )
        logging.info("Exported JSON to %s", path)
    elif output == "csv":
        save_records_list_csv(consolidated.get("records", []), path)
    else:
        logging.warning("Unknown output format '%s' (supported: csv, json)", output)

def save_records_list_csv(records: t.List[dict], path: str) -> None:
    """
    Save the list of dict records to CSV (no pandas).
    """
    if not path:
        return
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)

    if not records:
        logging.warning("No records to save at %s", path)
        # still create an empty file with no rows/headers
        with open(path, "w", newline="", encoding="utf-8") as f:
            pass
        return

    import csv
    col_names = list(records[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(col_names)
        for rec in records:
            row = []
            for k in col_names:
                v = rec.get(k)
                if v is None:
                    row.append("")
                elif isinstance(v, (str, int, float, bool)):
                    row.append(v)
                else:
                    # Nested/list/dict values → JSON-encode for CSV safety
                    row.append(json.dumps(v, ensure_ascii=False))
            w.writerow(row)
    logging.info("Saved records list CSV to %s", path)

def save_records_list_xlsx(records: t.List[dict], path: str) -> None:
    """
    Save the list of dict records to an Excel .xlsx file (no pandas).
    """
    if not path:
        return
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)

    try:
        from openpyxl import Workbook
    except Exception as e:
        logging.error("openpyxl is required to save XLSX: %s", e)
        return

    wb = Workbook()
    ws = wb.active
    ws.title = "records"

    if not records:
        logging.warning("No records to save at %s", path)
        wb.save(path)
        logging.info("Saved empty XLSX to %s", path)
        return

    # Header from first record keys
    col_names = list(records[0].keys())
    ws.append(col_names)

    # Rows
    for rec in records:
        row = []
        for k in col_names:
            v = rec.get(k)
            if v is None:
                row.append("")
            elif isinstance(v, (str, int, float, bool)):
                row.append(v)
            else:
                # JSON-encode nested structures for Excel cell
                row.append(json.dumps(v, ensure_ascii=False))
        ws.append(row)

    wb.save(path)
    logging.info("Saved records list XLSX to %s", path)

# ---------------------------
# CLI
# ---------------------------
def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Run Dynatrace DQL; consolidated results as list of dicts. Auto-save raw JSON, records CSV, and records XLSX.")
    ap.add_argument("-d", "--debug", action="store_true", help="Enable debug logging")
    ap.add_argument("--config", default=DEFAULT_CONFIG, help="INI config file path")
    ap.add_argument("--url", help="Dynatrace base URL (overrides config/env)")
    ap.add_argument("--token", help="API/Bearer token (overrides config/env)")
    ap.add_argument("--auth-mode", choices=["api-token", "bearer"], help="Auth mode")
    ap.add_argument("--dql", help="Inline DQL query string")
    ap.add_argument("--dql-file", help="Path to text file containing DQL (e.g., ./queries/query.txt)")
    ap.add_argument("--timeframe", default=DEFAULT_TIMEFRAME, help="Timeframe (e.g., 'now()-24h' or '2025-01-01T00:00:00Z to now()')")
    ap.add_argument("--page-size", type=int, default=DEFAULT_PAGE_SIZE, help="Records per result set")
    ap.add_argument("--timeout-ms", type=int, default=DEFAULT_TIMEOUT_MS, help="Server-side request timeout in ms")
    ap.add_argument("--print-rows", type=int, default=50, help="Rows to print in table preview")

    # Optional consolidated export
    ap.add_argument("--output", choices=["csv", "json"], help="Export consolidated output")
    ap.add_argument("--output-path", help="Output file path for consolidated export")

    # Activated-by-default outputs (override paths if needed)
    ap.add_argument("--save-raw-json", help=f"Directory to save raw JSON API responses (default: {DEFAULT_SAVE_RAW_JSON_DIR})")
    ap.add_argument("--save-records-csv", help=f"Path to save the records list as CSV (default: {DEFAULT_SAVE_RECORDS_CSV})")
    ap.add_argument("--save-records-xlsx", help=f"Path to save the records list as XLSX (default: {DEFAULT_SAVE_RECORDS_XLSX})")
    return ap.parse_args()


def extract_ci_id_app_from_tags(tags) -> t.Optional[str]:
    """
    Extracts the CI_ID_APP value from the 'tags' field of a record.
    Supports several common tag shapes:
      - List[str]: ["key:value", "k2:v2", ...] or ["CI_ID_APP:foo", ...]
      - List[dict]: [{"key":"CI_ID_APP","value":"foo"}, {"name":"k2","value":"v2"}, ...]
      - Dict[str,str]: {"CI_ID_APP":"foo", ...}
      - Presence-only tag: "CI_ID_APP" (returns "true")
    Returns the first matching value or None if not found.
    """
    if tags is None:
        return None

    # dict form: {"CI_ID_APP": "abc", ...}
    if isinstance(tags, dict):
        # normalize keys to strings and check direct
        for k, v in tags.items():
            if str(k) == "CI_ID_APP":
                return str(v) if v is not None else ""
        return None

    # list form
    if isinstance(tags, list):
        for item in tags:
            # string form: "key:value" or "CI_ID_APP:abc" or presence-only "CI_ID_APP"
            if isinstance(item, str):
                if item == "CI_ID_APP":
                    return "true"
                if item.startswith("CI_ID_APP:"):
                    return item.split(":", 1)[1]
            # dict form: {"key":"CI_ID_APP","value":"abc"} or {"name":"CI_ID_APP","value":"abc"}
            elif isinstance(item, dict):
                key = item.get("key") or item.get("name") or item.get("tag") or item.get("id")
                if key == "CI_ID_APP":
                    # prefer "value"; fallback to other common properties
                    val = item.get("value")
                    if val is None:
                        val = item.get("val") or item.get("text") or item.get("valueText")        
                    return str(val) if val is not None else ""


# ---------------------------
# Entrypoint
# ---------------------------


def main():
    args = parse_args()
    setup_logging(args.debug)
    cfg = load_config(args.config)
    s = resolve_settings(cfg, args)

    logging.info("Querying Dynatrace at: %s (auth=%s)", s["base_url"], s["auth_mode"])

    consolidated = run_dql_query(
        base_url=s["base_url"],
        token=s["token"],
        auth_mode=s["auth_mode"],
        dql=s["dql"],
        timeframe=s["timeframe"],
        request_timeout_ms=s["request_timeout_ms"],
        page_size=s["page_size"],
        save_raw_json_dir=s["save_raw_json_dir"],
    )

    # --- Build DataFrame and add CI_ID_APP ---
    try:
        import pandas as pd
    except Exception as e:
        logging.error("Pandas import failed; cannot create/save DataFrame. Error: %s", e)
        pd = None

    records = consolidated.get("records", [])

    if pd is not None:
        df = pd.DataFrame(records)

        # Ensure CI_ID_APP column exists
        if "Tags" in df.columns:
            df["CI_ID_APP"] = df["Tags"].apply(extract_ci_id_app_from_tags)
        else:
            df["CI_ID_APP"] = None

        # Create directories
        if s["save_records_csv"]:
            os.makedirs(os.path.dirname(os.path.abspath(s["save_records_csv"])), exist_ok=True)
        if s["save_records_xlsx"]:
            os.makedirs(os.path.dirname(os.path.abspath(s["save_records_xlsx"])), exist_ok=True)

        # Save DataFrame to CSV
        if s["save_records_csv"]:
            df.to_csv(s["save_records_csv"], index=False)
            logging.info("Saved DataFrame CSV to %s (shape=%s)", s["save_records_csv"], df.shape)

        # Save DataFrame to XLSX (requires openpyxl)
        if s["save_records_xlsx"]:
            try:
                df.to_excel(s["save_records_xlsx"], index=False, engine="openpyxl")
                logging.info("Saved DataFrame XLSX to %s (shape=%s)", s["save_records_xlsx"], df.shape)
            except Exception as e:
                logging.error("Failed to save XLSX (openpyxl required). Error: %s", e)
    else:
        logging.warning("Skipping DataFrame save; pandas not available.")

    # --- Optional consolidated export (unchanged) ---
    if s["output"]:
        export_results(consolidated, s["output"], s["output_path"])

    # Note: We no longer call save_records_list_csv/XLSX (records list). The    # Note: We no longer call save_records_list_csv/XLSX (records list). The DataFrame is the canonical output.



if __name__ == "__main__":
    main()