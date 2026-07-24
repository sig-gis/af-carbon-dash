import os
import tempfile
import uuid
from datetime import timedelta
from pathlib import Path

import google.auth
import google.auth.transport.requests
from google.cloud import storage


def get_site_upload_bucket_name() -> str | None:
    """Return the bucket used for temporary Site Selection uploads.

    Prefer a dedicated temporary upload bucket. Fall back to MODEL_STORE_BUCKET so
    deployments can test this flow without introducing a second bucket.
    """

    return os.environ.get("SITE_UPLOAD_BUCKET") or os.environ.get("MODEL_STORE_BUCKET")


def make_site_upload_object_name(filename: str = "site_selection_upload.zip") -> str:
    """Create a collision-resistant temporary object path for an upload."""

    safe_name = Path(filename).name or "site_selection_upload.zip"
    if not safe_name.lower().endswith(".zip"):
        safe_name = f"{safe_name}.zip"

    return f"tmp/site-selection/{uuid.uuid4().hex}/{safe_name}"


def create_signed_upload_url(
    object_name: str,
    content_type: str = "application/zip",
    minutes_valid: int = 30,
) -> tuple[str, str]:
    """Create a short-lived signed URL for browser direct upload to GCS."""

    bucket_name = get_site_upload_bucket_name()
    if not bucket_name:
        raise RuntimeError(
            "SITE_UPLOAD_BUCKET or MODEL_STORE_BUCKET must be set to use large uploads."
        )

    client = storage.Client(project=os.environ.get("GCP_PROJECT"))
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(object_name)

    signing_kwargs = {}
    credentials, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )

    # Locally, service-account key credentials can sign directly. On Cloud Run,
    # Application Default Credentials usually do not have a private key, so use
    # IAM Credentials API signing via the runtime service account instead.
    if not hasattr(credentials, "sign_bytes"):
        auth_request = google.auth.transport.requests.Request()
        credentials.refresh(auth_request)
        service_account_email = os.environ.get(
            "GOOGLE_SERVICE_ACCOUNT_EMAIL"
        ) or getattr(credentials, "service_account_email", None)

        if not service_account_email:
            raise RuntimeError(
                "Could not determine service account email for GCS signed URL generation. "
                "Set GOOGLE_SERVICE_ACCOUNT_EMAIL to the Cloud Run service account email."
            )

        signing_kwargs = {
            "service_account_email": service_account_email,
            "access_token": credentials.token,
        }

    signed_url = blob.generate_signed_url(
        version="v4",
        expiration=timedelta(minutes=minutes_valid),
        method="PUT",
        content_type=content_type,
        **signing_kwargs,
    )

    return signed_url, f"gs://{bucket_name}/{object_name}"


def download_gcs_object_to_tempfile(gcs_uri: str, suffix: str = ".zip") -> str:
    """Download a gs:// object to a local tempfile and return the local path."""

    if not gcs_uri.startswith("gs://"):
        raise ValueError(f"Expected gs:// URI, got: {gcs_uri}")

    bucket_name, object_name = gcs_uri[5:].split("/", 1)
    client = storage.Client(project=os.environ.get("GCP_PROJECT"))
    blob = client.bucket(bucket_name).blob(object_name)

    fd, local_path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    blob.download_to_filename(local_path)
    return local_path


def delete_gcs_object(gcs_uri: str) -> None:
    """Delete a temporary gs:// object if it exists."""

    if not gcs_uri.startswith("gs://"):
        return

    bucket_name, object_name = gcs_uri[5:].split("/", 1)
    client = storage.Client(project=os.environ.get("GCP_PROJECT"))
    blob = client.bucket(bucket_name).blob(object_name)
    blob.delete(if_generation_match=None)