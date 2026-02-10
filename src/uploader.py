
import os
import sys
import time
import argparse
from pathlib import Path
from datetime import datetime, timezone

from utils import setup_logger, load_config
from dotenv import load_dotenv
from azure.storage.blob import BlobServiceClient
logger = setup_logger("uploader", logfile="uploader.log")

# Load environment variables from .env file
ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=ROOT_DIR / ".env")

# Configuration from environment variables
CONFIG_PATH = os.environ.get("EDGE_CONFIG", "/home/gerrit/Projects/pi-sensing/config.yaml")
USB_MOUNT = Path(os.environ.get("USB_MOUNT", "/mnt/usb-data"))
CONTAINER = os.environ.get("AZURE_BLOB_CONTAINER", "stable-sensing")

# These are resolved at runtime from config/environment
ACTIVE_PREFIX = os.environ.get("AZURE_BLOB_PREFIX", "").strip("/")
ACTIVE_DEVICE_ID = os.environ.get("DEVICE_ID", "pi-node-01")

def _client():
    """
    Create and return an Azure BlobServiceClient using connection string or account URL + SAS token.
    """
    conn_str = os.environ.get("AZURE_STORAGE_CONNECTION_STRING", "")
    acct_url = os.environ.get("AZURE_STORAGE_ACCOUNT_URL", "")
    sas = os.environ.get("AZURE_STORAGE_SAS_TOKEN", "")
    if conn_str:
        logger.debug("Using connection string auth")
        return BlobServiceClient.from_connection_string(conn_str)
    if acct_url and sas:
        logger.debug("Using account URL + SAS auth")
        return BlobServiceClient(account_url=acct_url, credential=sas)
    raise RuntimeError("No Azure credentials given.")

def list_candidates():
    """
    List all CSV files in the USB mount directory.
    """
    files = sorted(USB_MOUNT.glob("*.csv"))
    logger.info("Found %d csv candidates in %s", len(files), USB_MOUNT)
    return files

def target_blob_path(local):
    """
    Build the blob path in Azure using prefix, device ID, and local filename.
    Adds UTC timestamp into the blob filename to keep each upload unique.
    """
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    # Insert timestamp before suffix, e.g. data.csv -> data_20260210T092529Z.csv
    stamped = f"{local.stem}_{ts}{local.suffix}"
    parts = [p for p in [ACTIVE_PREFIX, ACTIVE_DEVICE_ID] if p]
    return "/".join(parts + [stamped])

def upload_once():
    """
    Upload all new CSV files to Azure Blob Storage and mark them as uploaded with a .ok file.
    """
    cli = _client()
    cont = cli.get_container_client(CONTAINER)
    try:
        cont.create_container()
    except Exception:
        pass  # Container may already exist
    uploaded = 0
    for f in list_candidates():
        ok = f.with_suffix(f.suffix + ".ok")
        # If marker exists, re-upload only if file changed since marker was written
        if ok.exists():
            try:
                if f.stat().st_mtime <= ok.stat().st_mtime:
                    logger.debug("Skip %s (ok marker newer or same mtime)", f)
                    continue
                else:
                    logger.info("Re-uploading %s (file newer than ok)", f)
            except FileNotFoundError:
                # If one of them disappeared in between, just proceed to upload
                logger.debug("Stat race for %s or %s; proceeding to upload", f, ok)
        target = target_blob_path(f)
        logger.info("Uploading %s -> %s", f, target)
        with open(f, "rb") as fh:
            cont.upload_blob(name=target, data=fh, overwrite=True)
        ok.write_text(datetime.now(timezone.utc).isoformat())
        uploaded += 1
        logger.info(f"Uploaded {f} to Azure as {target}")
    if uploaded:
        logger.info(f"Total files uploaded: {uploaded}")
    return uploaded

def main():
    """
    Main entry point. If --once is given, upload once and exit. Otherwise, run in a loop based on config upload_minutes.
    """
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args()
    cfg = {}
    try:
        cfg = load_config(CONFIG_PATH)
    except Exception as e:
        logger.warning(f"Could not load config {CONFIG_PATH}: {e}; using defaults")
    device_cfg = cfg.get("device", {}) if isinstance(cfg, dict) else {}
    site = str(device_cfg.get("site", "")).strip()
    location = str(device_cfg.get("location", "")).strip()
    cfg_device_id = str(device_cfg.get("id", "")).strip() or None

    # Resolve prefix: env overrides, else site/location from config
    global ACTIVE_PREFIX, ACTIVE_DEVICE_ID
    if os.environ.get("AZURE_BLOB_PREFIX"):
        ACTIVE_PREFIX = os.environ.get("AZURE_BLOB_PREFIX", "").strip("/")
    else:
        parts = [p for p in [site, location] if p]
        ACTIVE_PREFIX = "/".join(parts)

    ACTIVE_DEVICE_ID = os.environ.get("DEVICE_ID", cfg_device_id or "pi-node-01")

    upload_minutes = int(cfg.get("upload_minutes", 5)) if isinstance(cfg, dict) else 5
    if upload_minutes <= 0:
        upload_minutes = 5

    if args.once:
        uploaded = upload_once()
        print(f"Uploaded {uploaded} files.")
        logger.info(f"Uploader ran once, uploaded {uploaded} files.")
        return
    logger.info(
        "Starting continuous upload loop, interval=%d minutes, prefix=%s, device_id=%s",
        upload_minutes,
        ACTIVE_PREFIX or "(none)",
        ACTIVE_DEVICE_ID,
    )
    while True:
        loop_started = time.time()
        try:
            upload_once()
        except Exception as e:
            logger.error(f"Upload error: {e}")
            print(f"Upload error: {e}", file=sys.stderr)
        elapsed = time.time() - loop_started
        sleep_sec = max(0, upload_minutes * 60 - elapsed)
        time.sleep(sleep_sec)

if __name__ == '__main__':
    main()