
from datetime import datetime, timezone
import os
import sys
import time
import csv
import yaml
import logging
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

def load_config(p):
    """
    Load YAML configuration file and expand environment variables in values.
    """
    with open(p) as f:
        import yaml as y
        cfg = y.safe_load(f)
    def exp(v):
        if isinstance(v, str):
            return os.path.expandvars(v)
        elif isinstance(v, dict):
            return {k: exp(x) for k, x in v.items()}
        elif isinstance(v, list):
            return [exp(x) for x in v]
        else:
            return v
    return exp(cfg)

def setup_logger(name="edge", level=logging.INFO, logfile=None):
    """
    Set up a logger with UTC timestamps, stream output, and optional file logging.
    logfile: If provided, logs will also be written to this file.
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)
    formatter = logging.Formatter("%(asctime)sZ [%(levelname)s] %(message)s", datefmt="%Y-%m-%dT%H:%M:%S")
    # Console handler
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)
    # File handler
    if logfile:
        file_handler = logging.FileHandler(logfile)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    logging.Formatter.converter = time.gmtime
    return logger

def ensure_dir(p: Path):
    """
    Ensure a directory exists, creating it if necessary.
    """
    p.mkdir(parents=True, exist_ok=True)

def csv_writer(root: Path, device_id: str, header):
    """
    Open a CSV file for appending, write header if new, and return file handle and writer.
    """
    date_str = datetime.now(timezone.utc).date().isoformat()
    fpath = root / f"{date_str}_{device_id}.csv"
    is_new = not fpath.exists()
    f = open(fpath, "a", newline="")
    w = csv.writer(f)
    if is_new:
        w.writerow(header)
        f.flush()
        os.fsync(f.fileno())
    return f, w, fpath

def apply_calibration(vals: dict, cal: dict | None):
    """
    Apply calibration (scale and offset) to ADC values if calibration is provided.
    """
    if not cal:
        return vals
    out = {}
    for k, v in vals.items():
        c = cal.get(k)
        out[k] = v * float(c.get("scale", 1.0)) + float(c.get("offset", 0.0)) if c else v
    return out