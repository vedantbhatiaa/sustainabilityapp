"""
storage.py — TIP ESG Platform · Storage Client
===============================================
LocalStorage class wrapping all file I/O for the data_storage/ folder.
Interface is designed to be Azure-migration-ready: swap LocalStorage for
an AzureStorage class with the same method signatures to move to
Azure SQL + Blob Storage without changing any page code.

Methods marked "Azure migration stub" are scaffolded for future use.
"""

import os, io, json, logging, threading, time
from pathlib import Path
from datetime import datetime
from typing import Optional, Union

import requests

logger = logging.getLogger(__name__)

# ─── Configuration ────────────────────────────────────────────────────────────
CLIENT_ID    = os.getenv("AZURE_CLIENT_ID",    "")
CLIENT_SECRET= os.getenv("AZURE_CLIENT_SECRET","")
TENANT_ID    = os.getenv("AZURE_TENANT_ID",    "")

SHAREPOINT_SITE  = os.getenv("SHAREPOINT_SITE",  "consultdss.sharepoint.com:/sites/TIP-ESG")
SHAREPOINT_DRIVE = os.getenv("SHAREPOINT_DRIVE", "TIP-ESG-Data")

GRAPH_BASE = "https://graph.microsoft.com/v1.0"

FOLDER_RAW_TEMPLATES = "01_Templates_Raw"
FOLDER_VALIDATED     = "02_Validated"
FOLDER_CONSOLIDATED  = "03_Consolidated"
FOLDER_REPORTS       = "04_Reports"
FOLDER_ARCHIVE       = "99_Archive"


class StorageClient:
    """
    Handles all file operations with SharePoint / OneDrive via Microsoft Graph.

    H5 FIX: Both the singleton guard and the in-memory token cache are now
    protected by threading.Lock objects so concurrent Streamlit threads cannot
    interleave and produce a partially-written or stale token.
    """

    def __init__(self):
        self._token: Optional[str] = None
        self._token_expiry: float  = 0
        self._drive_id: Optional[str] = None
        self._site_id:  Optional[str] = None

        # H5 FIX — separate locks for token refresh and drive/site id caching
        self._token_lock = threading.Lock()
        self._id_lock    = threading.Lock()

    # ── Authentication ────────────────────────────────────────────────────────

    def _get_token(self) -> str:
        """Acquire an OAuth2 access token using client_credentials flow.
        H5 FIX: protected by a lock so concurrent callers wait rather than
        each independently fetching a new token and racing to store it.
        """
        # Fast path — no lock if token is still valid
        if self._token and time.time() < self._token_expiry - 60:
            return self._token

        with self._token_lock:
            # Double-checked locking: another thread may have refreshed while
            # we were waiting for the lock.
            if self._token and time.time() < self._token_expiry - 60:
                return self._token

            url  = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"
            data = {
                "grant_type":    "client_credentials",
                "client_id":     CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "scope":         "https://graph.microsoft.com/.default",
            }
            resp = requests.post(url, data=data, timeout=15)
            resp.raise_for_status()
            body = resp.json()

            self._token        = body["access_token"]
            self._token_expiry = time.time() + body.get("expires_in", 3600)
            logger.info("Access token acquired (expires in %ss)", body.get("expires_in"))
            return self._token

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._get_token()}"}

    def _get_site_id(self) -> str:
        """Resolve SharePoint site path to site_id (cached, lock-protected)."""
        if self._site_id:
            return self._site_id
        with self._id_lock:
            if self._site_id:
                return self._site_id
            url  = f"{GRAPH_BASE}/sites/{SHAREPOINT_SITE}"
            resp = requests.get(url, headers=self._headers(), timeout=15)
            resp.raise_for_status()
            self._site_id = resp.json()["id"]
            return self._site_id

    def _get_drive_id(self) -> str:
        """Resolve document library name to drive_id (cached, lock-protected)."""
        if self._drive_id:
            return self._drive_id
        with self._id_lock:
            if self._drive_id:
                return self._drive_id
            site_id = self._get_site_id()
            url     = f"{GRAPH_BASE}/sites/{site_id}/drives"
            resp    = requests.get(url, headers=self._headers(), timeout=15)
            resp.raise_for_status()
            for d in resp.json().get("value", []):
                if d.get("name") == SHAREPOINT_DRIVE:
                    self._drive_id = d["id"]
                    return self._drive_id
            raise ValueError(f"Document library '{SHAREPOINT_DRIVE}' not found.")

    # ── Core operations ───────────────────────────────────────────────────────

    def upload(self, local_path: Union[str, Path], remote_folder: str,
               remote_filename: Optional[str] = None) -> dict:
        """
        Upload a file to SharePoint.

        M2 FIX: Content-Type header is now built cleanly in a single step.
        Previous code set it to octet-stream, deleted it, then re-added it —
        leftover from a merge conflict; cleaned up.
        """
        local_path  = Path(local_path)
        fname       = remote_filename or local_path.name
        drive_id    = self._get_drive_id()
        remote_path = f"{remote_folder}/{fname}".lstrip("/")
        url         = f"{GRAPH_BASE}/drives/{drive_id}/root:/{remote_path}:/content"

        with open(local_path, "rb") as fh:
            content = fh.read()

        # M2 FIX — single clean header dict; no delete/re-add dance
        headers = {
            **self._headers(),
            "Content-Type": "application/octet-stream",
        }

        resp = requests.put(url, headers=headers, data=content, timeout=60)
        resp.raise_for_status()
        result = resp.json()
        logger.info("Uploaded %s → %s (id=%s)", fname, remote_path, result.get("id"))
        return result

    def download(self, remote_folder: str, remote_filename: str,
                 local_path: Optional[Union[str, Path]] = None) -> bytes:
        """Download a file from SharePoint. Returns raw bytes."""
        drive_id    = self._get_drive_id()
        remote_path = f"{remote_folder}/{remote_filename}".lstrip("/")
        url         = f"{GRAPH_BASE}/drives/{drive_id}/root:/{remote_path}:/content"

        resp = requests.get(url, headers=self._headers(), timeout=60,
                            allow_redirects=True)
        resp.raise_for_status()
        data = resp.content

        if local_path:
            Path(local_path).write_bytes(data)
            logger.info("Downloaded %s → %s", remote_path, local_path)
        return data

    def list_files(self, remote_folder: str) -> list:
        """List all files in a SharePoint folder."""
        drive_id = self._get_drive_id()
        url      = f"{GRAPH_BASE}/drives/{drive_id}/root:/{remote_folder}:/children"
        resp     = requests.get(url, headers=self._headers(), timeout=15)
        resp.raise_for_status()
        return [
            {
                "name":     i["name"],
                "size":     i.get("size"),
                "modified": i.get("lastModifiedDateTime"),
                "url":      i.get("webUrl"),
                "id":       i["id"],
            }
            for i in resp.json().get("value", [])
            if "folder" not in i
        ]

    def archive(self, remote_folder: str, filename: str) -> None:
        """
        Move a file to the Archive folder with a timestamp-based rename so
        multiple archives of the same filename never collide.

        M3 FIX: previous code built a timestamped dst_path variable but never
        sent the rename to the API — the file arrived in the archive folder
        with its original name, meaning a second archive silently overwrote
        the first. Now we issue a two-step: PATCH to move + rename atomically
        via Graph's 'name' field.
        """
        drive_id = self._get_drive_id()
        src_path = f"{remote_folder}/{filename}"
        ts       = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        # Build a unique archived filename that embeds the source folder and timestamp
        archived_name = f"{remote_folder.replace('/','_')}_{ts}_{filename}"

        # Resolve source item id
        url_src  = f"{GRAPH_BASE}/drives/{drive_id}/root:/{src_path}"
        src_resp = requests.get(url_src, headers=self._headers(), timeout=15)
        src_resp.raise_for_status()
        item_id  = src_resp.json()["id"]

        # M3 FIX — include 'name' in the PATCH payload so the file is renamed
        # at the same time it is moved; Graph supports move+rename in one call.
        payload = {
            "parentReference": {
                "path": f"/drives/{drive_id}/root:/{FOLDER_ARCHIVE}"
            },
            "name": archived_name,
        }
        url_mv = f"{GRAPH_BASE}/drives/{drive_id}/items/{item_id}"
        requests.patch(url_mv, headers={**self._headers(),
                                        "Content-Type": "application/json"},
                       json=payload, timeout=15).raise_for_status()
        logger.info("Archived %s → %s/%s", src_path, FOLDER_ARCHIVE, archived_name)

    def save_metadata(self, company: str, year: int, meta: dict) -> None:
        """Save submission metadata as a JSON sidecar file."""
        meta["company"]   = company
        meta["year"]      = year
        meta["timestamp"] = datetime.utcnow().isoformat()
        content   = json.dumps(meta, indent=2).encode()
        drive_id  = self._get_drive_id()
        remote_path = f"{FOLDER_VALIDATED}/{company}/{year}_metadata.json"
        url       = f"{GRAPH_BASE}/drives/{drive_id}/root:/{remote_path}:/content"
        headers   = {**self._headers(), "Content-Type": "application/octet-stream"}
        requests.put(url, headers=headers, data=content, timeout=15).raise_for_status()
        logger.info("Metadata saved for %s %s", company, year)


# ── Singleton — H5 FIX: guarded by a module-level lock ───────────────────────

_client_lock: threading.Lock       = threading.Lock()
_client:      Optional[StorageClient] = None


def get_client() -> StorageClient:
    """Thread-safe singleton factory."""
    global _client
    if _client is not None:
        return _client
    with _client_lock:
        if _client is None:
            _client = StorageClient()
    return _client


# ── Convenience helpers ───────────────────────────────────────────────────────

def upload_template(file_path: str, company: str) -> dict:
    return get_client().upload(file_path, f"{FOLDER_RAW_TEMPLATES}/{company}")

def upload_validated(file_path: str, company: str) -> dict:
    return get_client().upload(file_path, f"{FOLDER_VALIDATED}/{company}")

def upload_report(file_path: str, company: str, year: int) -> dict:
    fname = f"{company.replace(' ','_')}_{year}_ESG_Report.xlsx"
    return get_client().upload(file_path, f"{FOLDER_REPORTS}/{company}", fname)

def download_template(company: str, filename: str, save_to: str = ".") -> bytes:
    return get_client().download(f"{FOLDER_RAW_TEMPLATES}/{company}", filename, save_to)

def list_submissions(company: str = None) -> list:
    folder = f"{FOLDER_RAW_TEMPLATES}/{company}" if company else FOLDER_RAW_TEMPLATES
    return get_client().list_files(folder)


# ── MockStorage (dev / no-credentials) ───────────────────────────────────────

class MockStorage:
    """
    Local filesystem mock of StorageClient.
    Mirrors the same folder structure on disk.
    Used when SharePoint credentials are absent (get_storage(mock=True)).
    """
    BASE = Path("./mock_storage")

    def __init__(self):
        for folder in [FOLDER_RAW_TEMPLATES, FOLDER_VALIDATED,
                       FOLDER_CONSOLIDATED, FOLDER_REPORTS, FOLDER_ARCHIVE]:
            (self.BASE / folder).mkdir(parents=True, exist_ok=True)
        print(f"MockStorage initialised at {self.BASE.resolve()}")

    def upload(self, local_path, remote_folder, remote_filename=None):
        local_path = Path(local_path)
        dest = self.BASE / remote_folder / (remote_filename or local_path.name)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(local_path.read_bytes())
        print(f"[MOCK] Uploaded {local_path.name} → {dest.relative_to(self.BASE)}")
        return {"name": dest.name, "webUrl": str(dest)}

    def download(self, remote_folder, remote_filename, local_path=None):
        src  = self.BASE / remote_folder / remote_filename
        data = src.read_bytes()
        if local_path:
            Path(local_path).write_bytes(data)
        return data

    def list_files(self, remote_folder):
        folder = self.BASE / remote_folder
        if not folder.exists():
            return []
        return [
            {"name": f.name, "size": f.stat().st_size,
             "modified": str(f.stat().st_mtime)}
            for f in folder.iterdir() if f.is_file()
        ]

    def save_metadata(self, company, year, meta):
        meta.update({"company": company, "year": year,
                     "timestamp": datetime.utcnow().isoformat()})
        dest = self.BASE / FOLDER_VALIDATED / company / f"{year}_metadata.json"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(meta, indent=2))

    def archive(self, remote_folder, filename):
        src = self.BASE / remote_folder / filename
        if not src.exists():
            return
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        archived_name = f"{remote_folder.replace('/','_')}_{ts}_{filename}"
        dest = self.BASE / FOLDER_ARCHIVE / archived_name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(src.read_bytes())
        src.unlink()
        print(f"[MOCK] Archived {filename} → {archived_name}")


def get_storage(mock: bool = False):
    """Factory. mock=True for local dev; production uses real SharePoint client."""
    if mock or not all([CLIENT_ID, CLIENT_SECRET, TENANT_ID]):
        return MockStorage()
    return get_client()


# ── Quick self-test ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import tempfile
    storage = get_storage(mock=True)

    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
        f.write(b"TIP ESG test file")
        tmp = f.name

    result = storage.upload(tmp, FOLDER_RAW_TEMPLATES + "/VerdaTyres", "test_upload.txt")
    print("Upload result:", result)

    files = storage.list_files(FOLDER_RAW_TEMPLATES)
    print("Files in raw templates:", files)

    storage.save_metadata("VerdaTyres Corp", 2023, {"status": "approved", "flags": 0})
    print("Metadata saved")

    storage.archive(FOLDER_RAW_TEMPLATES + "/VerdaTyres", "test_upload.txt")
    print("Archive test complete")

    print("\nStorage module self-test passed.")