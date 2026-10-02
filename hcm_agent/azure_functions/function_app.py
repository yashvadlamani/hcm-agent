"""Azure Function: place a Clara test call when a call-request JSON file is uploaded.

Upload to the `call-requests` container under `incoming/`, for example
`incoming/yash-test.json`:

    {"to": "+15551234567", "name": "Yash", "for": "diabetes management",
     "risk_drivers": ["HbA1c above 7.5%"]}

Each file places at most one call. The file is then moved to `processed/` (with the
call connection ID) or `failed/` (with the reason). Only numbers in ALLOWED_CALL_NUMBERS
are called, and at most MAX_CALLS_PER_HOUR calls are placed per hour.

`incoming/README.txt` keeps the folder visible between uploads (blob storage has no real
folders). It's never processed, and is put back if it goes missing.
"""

import datetime
import json
import logging
import os
from pathlib import Path

import azure.functions as func
from azure.core.exceptions import HttpResponseError, ResourceExistsError, ResourceNotFoundError
from azure.storage.blob import BlobClient, BlobServiceClient, ContainerClient

from hcm_agent import config
from hcm_agent.telephony.call_requests import InvalidCallRequest, parse_call_request
from hcm_agent.telephony.outbound import CallNotAllowed, place_call

app = func.FunctionApp()

CONTAINER = "call-requests"
STORAGE_SETTING = "CallRequestsStorage"
LEASE_SECONDS = 60
PLACEHOLDER = "incoming/README.txt"
PLACEHOLDER_SOURCE = Path(__file__).with_name("incoming_README.txt")
logger = logging.getLogger("clara.call_requests")


@app.blob_trigger(arg_name="blob", path=f"{CONTAINER}/incoming/{{name}}", connection=STORAGE_SETTING,
                  source=func.BlobSource.EVENT_GRID)
def call_request(blob: func.InputStream) -> None:
    blob_path = blob.name.split("/", 1)[1]  # "incoming/<file>" (blob.name includes the container)
    if not is_call_request(blob_path):
        logger.info("Ignoring %s: not a call request", blob_path)
        return
    container = BlobServiceClient.from_connection_string(os.environ[STORAGE_SETTING]).get_container_client(CONTAINER)
    incoming = container.get_blob_client(blob_path)

    # Claim the file so a duplicate event can't place a second call for it.
    try:
        lease = incoming.acquire_lease(lease_duration=LEASE_SECONDS)
    except (ResourceExistsError, ResourceNotFoundError, HttpResponseError):
        logger.info("Skipping %s: already being processed or gone", blob_path)
        return

    raw = blob.read()
    try:
        outcome, result = _handle(raw, container)
    except Exception as e:  # never raise: a retry could ring someone twice
        logger.exception("Unexpected error for %s", blob_path)
        outcome, result = "failed", {"error": f"unexpected error: {type(e).__name__}"}
    _file_result(container, incoming, lease, raw, outcome, result)
    _ensure_placeholder(container)


def is_call_request(blob_path: str) -> bool:
    """Only .json files directly in incoming/ are requests (not the README, not subfolders)."""
    name = blob_path.removeprefix("incoming/")
    return blob_path.startswith("incoming/") and "/" not in name and name.lower().endswith(".json")


def _ensure_placeholder(container: ContainerClient) -> None:
    """Keep incoming/ visible: put the README back if it's missing. Never fails the request."""
    try:
        container.upload_blob(PLACEHOLDER, PLACEHOLDER_SOURCE.read_bytes(), overwrite=False)
    except ResourceExistsError:
        pass
    except Exception:
        logger.warning("Couldn't restore %s", PLACEHOLDER, exc_info=True)


def _handle(raw: bytes, container: ContainerClient) -> tuple[str, dict]:
    settings = config.load()
    problems = config.call_request_problems(settings)
    if problems:
        return "failed", {"error": "function is not configured", "details": problems}

    try:
        request = parse_call_request(raw)
    except InvalidCallRequest as e:
        return "failed", {"error": f"invalid request: {e}"}

    if _calls_in_last_hour(container) >= settings.max_calls_per_hour:
        return "failed", {"error": f"rate limit: {settings.max_calls_per_hour} calls per hour"}

    try:
        sid = place_call(settings, settings.clara_base_url, request.to, request.name, request.risk_drivers,
                         reason=request.reason)
    except CallNotAllowed as e:
        return "failed", {"error": str(e)}
    except TimeoutError as e:
        return "failed", {"error": f"Clara server didn't wake up: {e}"}
    except Exception as e:  # ACS errors: record the message, don't retry
        return "failed", {"error": f"Azure Communication Services refused the call: {e}"}

    logger.info("Placed call %s to number ending %s", sid, request.to[-4:])
    return "processed", {"call_connection_id": sid}


def _calls_in_last_hour(container: ContainerClient) -> int:
    since = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1)
    return sum(1 for b in container.list_blobs(name_starts_with="processed/") if b.last_modified >= since)


def _file_result(container: ContainerClient, incoming: BlobClient, lease, raw: bytes,
                 outcome: str, result: dict) -> None:
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    file_name = incoming.blob_name.split("/", 1)[1]
    try:
        request = json.loads(raw.decode("utf-8-sig"))
    except ValueError:
        request = raw.decode("utf-8", "replace")
    record = {"outcome": outcome, "at": stamp, "request": request, "result": result}
    container.upload_blob(f"{outcome}/{stamp}-{file_name}", json.dumps(record, indent=2), overwrite=True)
    incoming.delete_blob(lease=lease)
    logger.info("%s -> %s/%s-%s", incoming.blob_name, outcome, stamp, file_name)
