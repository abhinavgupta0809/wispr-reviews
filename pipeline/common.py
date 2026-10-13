import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
import tempfile
import time

from . import config


class ScrapeError(Exception):
    """Safe error message: never attach store response bodies or reviewer objects."""


class RetryableError(ScrapeError):
    pass


def iso_utc(value):
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise ScrapeError("Invalid review timestamp") from None
        if value.tzinfo is None:
            raise ScrapeError("Timestamp string must have an explicit timezone")
    if not isinstance(value, datetime):
        raise ScrapeError("Review timestamp must be a datetime or ISO string")
    # Play's pinned library uses datetime.fromtimestamp(), so naive datetimes
    # represent system-local time. astimezone converts that time correctly.
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def dt(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def in_window(row, run_time):
    return dt(run_time) - timedelta(days=config.WINDOW_DAYS) <= dt(row["timestamp"]) <= dt(run_time)


@contextmanager
def atomic_text(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp = tempfile.mkstemp(prefix="." + path.name, dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            yield handle
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def write_json(path, payload):
    with atomic_text(path) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (ValueError, OSError):
        raise ScrapeError(f"Cannot read valid checkpoint: {Path(path).name}") from None


def arguments(description):
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--data-dir", type=Path, default=config.DATA_DIR)
    parser.add_argument("--run-time", help="UTC ISO timestamp; defaults to now on a new run")
    return parser.parse_args()


def ensure_run(data_dir, requested=None):
    path = data_dir / "run.json"
    settings = {
        "window_days": config.WINDOW_DAYS, "max_rows": config.MAX_ROWS,
        "seed": config.SEED, "play_langs": list(config.PLAY_LANGS),
        "play_country": config.PLAY_COUNTRY,
        "appstore_countries": list(config.APPSTORE_COUNTRIES),
        "play_app_id": config.PLAY_APP_ID, "appstore_id": config.APPSTORE_ID,
    }
    if path.exists():
        manifest = read_json(path)
        if manifest.get("settings") != settings:
            raise ScrapeError("Run configuration changed; use a fresh --data-dir")
        if requested and iso_utc(requested) != manifest["run_time_utc"]:
            raise ScrapeError("Run time changed; use a fresh --data-dir")
        return manifest["run_time_utc"]
    run_time = iso_utc(requested or datetime.now(timezone.utc).replace(microsecond=0))
    write_json(path, {"run_time_utc": run_time, "settings": settings})
    return run_time


def retry(operation, label, sleep=time.sleep):
    for attempt in range(config.RETRIES):
        try:
            return operation()
        except RetryableError as error:
            if attempt + 1 == config.RETRIES:
                raise ScrapeError(f"{label}: {error} after {config.RETRIES} attempts") from None
            delay = 2 ** (attempt + 1)
            print(f"{label}: retry {attempt + 1}, waiting {delay}s", flush=True)
            sleep(delay)


def integer(value, field, minimum=0, maximum=None):
    try:
        number = int(value)
        if isinstance(value, bool) or str(number) != str(value):
            raise ValueError
        if number < minimum or (maximum is not None and number > maximum):
            raise ValueError
        return number
    except (TypeError, ValueError):
        raise ScrapeError(f"Invalid {field}") from None


def text(value, field, optional=False):
    if value is None and optional:
        return ""
    if not isinstance(value, str):
        raise ScrapeError(f"Invalid {field}")
    return value


def validate_row(row):
    if set(row) != set(config.COLUMNS):
        raise ScrapeError("Unexpected sanitized review columns")
    for field in ("review_id", "country", "store_lang", "title", "review_text", "app_version"):
        text(row[field], field)
    if row["platform"] not in ("android", "ios"):
        raise ScrapeError("Invalid platform")
    prefix = "play_" if row["platform"] == "android" else "ios_"
    if not row["review_id"].startswith(prefix) or len(row["review_id"]) <= len(prefix):
        raise ScrapeError("Invalid review id")
    if row["platform"] == "android":
        if row["country"] != "" or not row["store_lang"].strip():
            raise ScrapeError("Android requires empty country and non-empty store_lang")
    elif (len(row["country"]) != 2 or not row["country"].isascii()
          or not row["country"].isalpha() or not row["country"].islower()
          or row["store_lang"] != ""):
        raise ScrapeError("iOS requires a two-letter country and empty store_lang")
    if iso_utc(row["timestamp"]) != row["timestamp"] or row["date_utc"] != row["timestamp"][:10]:
        raise ScrapeError("Invalid normalized date")
    integer(row["rating"], "rating", 1, 5)
    integer(row["thumbs_up"], "thumbs_up")
    if row["has_dev_reply"] not in ("TRUE", "FALSE"):
        raise ScrapeError("Invalid developer reply flag")


def publish_source(data_dir, source, rows, streams, run_time):
    unique = {}
    for row in rows:
        validate_row(row)
        unique.setdefault(row["review_id"], row)
    if not unique:
        raise ScrapeError(f"{source}: zero nonempty reviews in the window; output not published")
    target = data_dir / "interim" / f"{source}.jsonl"
    with atomic_text(target) as handle:
        for row in unique.values():
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    write_json(target.with_suffix(".meta.json"), {
        "complete": True, "run_time_utc": run_time,
        "rows": len(unique), "streams": streams,
    })
    print(f"{source}: wrote {len(unique)} unique reviews to {target}", flush=True)


def cli(main):
    try:
        main()
    except ScrapeError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1) from None
    except KeyboardInterrupt:
        print("Interrupted; completed page checkpoints are resumable", file=sys.stderr)
        raise SystemExit(130) from None
