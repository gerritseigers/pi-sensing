
from datetime import datetime, timezone
import os
import sys
import time
import csv
import uuid
import yaml
import logging
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# -----------------------------
# load the configuration from a YAML file, with environment variable expansion
# -----------------------------
def load_config(p):
    """
    @brief Load YAML configuration file with environment variable expansion.
    @param p Path to YAML configuration file
    @return Parsed configuration dictionary with environment variables expanded
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

# -----------------------------
# Setup the logger for terminal and file output with UTC timestamps
# -----------------------------
def setup_logger(name = "edge", level = logging.INFO, logfile = None):
    """
    @brief Set up logger with UTC timestamps, console and optional file output.
    @param name Logger name (default "edge")
    @param level Logging level (default logging.INFO)
    @param logfile Optional path to log file; if provided, logs are written there too
    @return Configured logger instance
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

# -----------------------------
# Check if directory is there, otherwise create it
# -----------------------------
def ensure_dir(p: Path):
    """
    @brief Create directory recursively if it does not exist.
    @param p Path object for directory to ensure
    """
    p.mkdir(parents=True, exist_ok=True)


def resolve_storage_root(preferred: Path, fallback: Path | None = None, logger=None) -> Path:
    """
    @brief Resolve writable storage root, trying preferred then fallback.
    @param preferred Preferred storage path
    @param fallback Fallback path if preferred unavailable (default ~/usb-data)
    @param logger Optional logger instance
    @return Path to first writable directory found
    @throws PermissionError if no writable directory found
    """
    log = logger or logging.getLogger("storage")
    fb = fallback or (Path.home() / "usb-data")

    candidates = []
    for c in (preferred, fb):
        if c not in candidates:
            candidates.append(c)

    last_error = None
    for path in candidates:
        try:
            path.mkdir(parents=True, exist_ok=True)
            probe = path / f".write_test_{uuid.uuid4().hex}"
            with open(probe, "w", encoding="utf-8") as fh:
                fh.write("ok")
            probe.unlink(missing_ok=True)
            if path == preferred:
                log.info("Using data directory: %s", path)
            else:
                log.warning("Primary data directory unavailable; using fallback: %s", path)
            return path
        except Exception as exc:
            last_error = exc
            log.warning("Data directory not writable: %s (%s)", path, exc)

    raise PermissionError(
        f"No writable data directory found. Tried: {preferred} and {fb}. Last error: {last_error}"
    )


def is_writable_directory(path: Path) -> bool:
    """
    @brief Test whether a directory is writable.
    @param path Directory path to test
    @return True if directory can be created/written, False otherwise
    """
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / f".write_test_{uuid.uuid4().hex}"
        with open(probe, "w", encoding="utf-8") as fh:
            fh.write("ok")
        probe.unlink(missing_ok=True)
        return True
    except Exception:
        return False


def discover_usb_mount(logger=None) -> Path | None:
    """
    @brief Auto-discover removable media mount points on the system.
    @param logger Optional logger instance
    @return Path to first writable USB mount found, or None if none found
    """
    log = logger or logging.getLogger("storage")
    user = os.environ.get("USER", "")
    roots = []
    if user:
        roots.extend([Path("/media") / user, Path("/run/media") / user])
    roots.extend([Path("/media"), Path("/run/media")])

    seen = set()
    for root in roots:
        if root in seen:
            continue
        seen.add(root)
        if not root.exists() or not root.is_dir():
            continue

        try:
            for candidate in sorted(root.iterdir()):
                if candidate.is_dir() and is_writable_directory(candidate):
                    log.info("Auto-detected mounted USB data directory: %s", candidate)
                    return candidate
        except Exception:
            continue
    return None


def pick_storage_target(preferred: Path, fallback: Path, logger=None) -> Path:
    """
    @brief Choose best available storage target in priority order.
    @param preferred Preferred mount point
    @param fallback Fallback mount point if preferred unavailable
    @param logger Optional logger instance
    @return Path to chosen writable storage target
    @throws PermissionError if no writable target found
    
    Tries in order: preferred mount, auto-detected USB, fallback mount.
    """
    log = logger or logging.getLogger("storage")
    if is_writable_directory(preferred):
        return preferred

    detected = discover_usb_mount(logger=log)
    if detected is not None:
        return detected

    if is_writable_directory(fallback):
        return fallback

    raise PermissionError(
        f"No writable data directory found. Tried preferred={preferred}, fallback={fallback}, and auto-discovery roots."
    )

# -----------------------------
# Create a csv writer for the given device and header, returning file handle, writer, and path
# -----------------------------
def csv_writer(root: Path, device_id: str, header):
    """
    @brief Open or create dated CSV file and prepare for writing.
    @param root Root directory for CSV file
    @param device_id Device identifier (used in filename)
    @param header List of column names for CSV header
    @return Tuple (file_handle, csv_writer, Path) for writing CSV data
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

# -----------------------------
# Convert given voltages to calibrated values using provided calibration data
# -----------------------------
def apply_calibration(vals: dict, cal: dict | None):
    """
    @brief Apply calibration (scale and offset) to ADC measurement values.
    @param vals Dictionary of measured values {channel: voltage}
    @param cal Calibration dictionary {channel: {"scale": float, "offset": float}}
    @return Dictionary of calibrated values with same keys as input
    
    Channels with None values or missing calibration pass through unchanged.
    Formula: calibrated = (raw * scale) + offset
    """
    if not cal:
        return vals
    out = {}
    for k, v in vals.items():
        if v is None:
            out[k] = None
            continue
        c = cal.get(k)
        if c:
            scale = float(c.get("scale", 1.0))
            offset = float(c.get("offset", 0.0))
            out[k] = v * scale + offset
        else:
            out[k] = v
    return out