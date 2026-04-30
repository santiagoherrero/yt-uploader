import logging
import time
from pathlib import Path
from typing import Callable, Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

log = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
RETRYABLE_STATUS = {500, 502, 503, 504}


class AuthError(RuntimeError):
    pass


class YouTubeUploader:
    def __init__(
        self,
        token_path: Path,
        chunk_size_bytes: int,
        max_retries: int,
    ) -> None:
        self._token_path = token_path
        self._chunk_size = chunk_size_bytes
        self._max_retries = max_retries
        self._service = self._build_service()

    def _build_service(self):
        if not self._token_path.exists():
            raise AuthError(
                f"OAuth token not found at {self._token_path}. "
                "Run yt-uploader-auth to generate it."
            )
        creds = Credentials.from_authorized_user_file(str(self._token_path), SCOPES)
        if not creds.valid:
            if creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except Exception as e:
                    raise AuthError(f"Token refresh failed: {e}") from e
                self._token_path.write_text(creds.to_json())
            else:
                raise AuthError("OAuth token is invalid and cannot be refreshed.")
        return build("youtube", "v3", credentials=creds, cache_discovery=False)

    def upload(
        self,
        file_path: Path,
        title: str,
        description: str,
        privacy: str,
        category_id: str,
        made_for_kids: bool,
        on_progress: Optional[Callable[[int], None]] = None,
    ) -> str:
        body = {
            "snippet": {
                "title": title,
                "description": description,
                "categoryId": category_id,
            },
            "status": {
                "privacyStatus": privacy,
                "selfDeclaredMadeForKids": made_for_kids,
            },
        }
        media = MediaFileUpload(
            str(file_path),
            chunksize=self._chunk_size,
            resumable=True,
            mimetype="video/*",
        )
        request = self._service.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media,
        )

        response = None
        attempt = 0
        while response is None:
            try:
                status, response = request.next_chunk()
                if status and on_progress:
                    on_progress(int(status.progress() * 100))
                attempt = 0
            except HttpError as e:
                if e.resp.status in RETRYABLE_STATUS and attempt < self._max_retries:
                    backoff = 2**attempt
                    log.warning(
                        "Upload chunk failed (%s), retrying in %ss",
                        e.resp.status,
                        backoff,
                    )
                    time.sleep(backoff)
                    attempt += 1
                    continue
                raise

        if on_progress:
            on_progress(100)
        return response["id"]
