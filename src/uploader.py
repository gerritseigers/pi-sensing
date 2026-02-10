
import os
import sys
import time
import argparse
from pathlib import Path
from datetime import datetime, timezone

from utils import setup_logger
from dotenv import load_dotenv
from azure.storage.blob import BlobServiceClient
logger = setup_logger("uploader", logfile="uploader.log")

# Load environment variables from .env file
load_dotenv()

# Configuration from environment variables
USB_MOUNT = Path(os.environ.get("USB_MOUNT", "/mnt/usb-data"))
CONN_STR = os.environ.get("AZURE_STORAGE_CONNECTION_STRING", "")
ACCOUNT_URL = os.environ.get("AZURE_STORAGE_ACCOUNT_URL", "")
SAS_TOKEN = os.environ.get("AZURE_STORAGE_SAS_TOKEN", "")
CONTAINER = os.environ.get("AZURE_BLOB_CONTAINER", "stable-sensing")
PREFIX = os.environ.get("AZURE_BLOB_PREFIX", "").strip("/")
DEVICE_ID = os.environ.get("DEVICE_ID", "pi-node-01")

def _client():
    """
    Create and return an Azure BlobServiceClient using connection string or account URL + SAS token.
    """
    if CONN_STR:
        return BlobServiceClient.from_connection_string(CONN_STR)
    if ACCOUNT_URL and SAS_TOKEN:
        return BlobServiceClient(account_url=ACCOUNT_URL, credential=SAS_TOKEN)
    raise RuntimeError("No Azure credentials given.")

def list_candidates():
    """
    List all CSV files in the USB mount directory.
    """
    return sorted(USB_MOUNT.glob("*.csv"))

def target_blob_path(local):
    """
    Build the blob path in Azure using prefix, device ID, and local filename.
    """
    parts = [p for p in [PREFIX, DEVICE_ID] if p]
    return "/".join(parts + [local.name])

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
        if ok.exists():
            continue  # Skip files already marked as uploaded
        with open(f, "rb") as fh:
            cont.upload_blob(name=target_blob_path(f), data=fh, overwrite=True)
        ok.write_text(datetime.now(timezone.utc).isoformat())
        uploaded += 1
        logger.info(f"Uploaded {f} to Azure as {target_blob_path(f)}")
    if uploaded:
        logger.info(f"Total files uploaded: {uploaded}")
    return uploaded

def main():
    """
    Main entry point. If --once is given, upload once and exit. Otherwise, run in a loop every 5 minutes.
    """
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args()
    if args.once:
        uploaded = upload_once()
        print(f"Uploaded {uploaded} files.")
        logger.info(f"Uploader ran once, uploaded {uploaded} files.")
        return
    while True:
        try:
            upload_once()
        except Exception as e:
            logger.error(f"Upload error: {e}")
            print(f"Upload error: {e}", file=sys.stderr)
        time.sleep(300)

if __name__ == '__main__':
    main()