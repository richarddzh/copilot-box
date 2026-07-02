from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from azure.core.exceptions import HttpResponseError, ResourceExistsError, ResourceModifiedError
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobLeaseClient, BlobServiceClient, ContentSettings

from copilot_box.config import StorageSettings


@dataclass(frozen=True)
class RequestBlob:
    name: str
    etag: str


class ClaimedBlob(Protocol):
    name: str
    etag: str

    def read_text(self) -> str:
        pass

    def complete(self) -> None:
        pass

    def abandon(self) -> None:
        pass


class BlobStorage(Protocol):
    def list_requests(self, *, prefix: str, limit: int) -> list[RequestBlob]:
        pass

    def try_claim_request(self, blob: RequestBlob) -> ClaimedBlob | None:
        pass

    def write_response_json(self, blob_name: str, payload: str) -> None:
        pass

    def write_dead_letter_json(self, blob_name: str, payload: str) -> None:
        pass


class AzureClaimedBlob:
    def __init__(self, blob_client, lease: BlobLeaseClient, blob: RequestBlob) -> None:
        self._blob_client = blob_client
        self._lease = lease
        self.name = blob.name
        self.etag = blob.etag

    def read_text(self) -> str:
        downloader = self._blob_client.download_blob(lease=self._lease)
        return downloader.readall().decode("utf-8")

    def complete(self) -> None:
        self._lease.release()

    def abandon(self) -> None:
        self._lease.release()


class AzureBlobStorage:
    def __init__(self, settings: StorageSettings) -> None:
        if not settings.account_url:
            raise ValueError("storage.account_url is required for Azure Blob Storage")
        credential = DefaultAzureCredential()
        self._settings = settings
        self._client = BlobServiceClient(account_url=settings.account_url, credential=credential)
        self._requests = self._client.get_container_client(settings.request_container)
        self._responses = self._client.get_container_client(settings.response_container)
        self._dead_letter = self._client.get_container_client(settings.dead_letter_container)

    def list_requests(self, *, prefix: str, limit: int) -> list[RequestBlob]:
        blobs: list[RequestBlob] = []
        for blob in self._requests.list_blobs(name_starts_with=prefix or None):
            if len(blobs) >= limit:
                break
            if not blob.name.endswith(".json"):
                continue
            blobs.append(RequestBlob(name=blob.name, etag=str(blob.etag or "")))
        return blobs

    def try_claim_request(self, blob: RequestBlob) -> AzureClaimedBlob | None:
        blob_client = self._requests.get_blob_client(blob.name)
        lease = BlobLeaseClient(blob_client)
        try:
            lease.acquire(lease_duration=60)
        except (ResourceExistsError, ResourceModifiedError):
            return None
        except HttpResponseError as exc:
            if exc.status_code in {409, 412}:
                return None
            raise
        return AzureClaimedBlob(blob_client, lease, blob)

    def write_response_json(self, blob_name: str, payload: str) -> None:
        self._responses.upload_blob(
            blob_name,
            payload.encode("utf-8"),
            overwrite=True,
            content_settings=ContentSettings(content_type="application/json; charset=utf-8"),
        )

    def write_dead_letter_json(self, blob_name: str, payload: str) -> None:
        self._dead_letter.upload_blob(
            blob_name,
            payload.encode("utf-8"),
            overwrite=True,
            content_settings=ContentSettings(content_type="application/json; charset=utf-8"),
        )
