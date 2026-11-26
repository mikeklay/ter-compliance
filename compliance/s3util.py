# s3util.py
import io
from typing import Optional
import boto3
from flask import current_app


def _client():
    """
    Build an S3 client using config/env set in your Flask app.
    Expected config keys (already supported by your config.py):
      - AWS_REGION
      - AWS_ACCESS_KEY_ID
      - AWS_SECRET_ACCESS_KEY
      - AWS_S3_BUCKET
    """
    region = current_app.config.get("AWS_REGION") or "us-east-1"
    aws_access_key_id = current_app.config.get("AWS_ACCESS_KEY_ID")
    aws_secret_access_key = current_app.config.get("AWS_SECRET_ACCESS_KEY")

    # If you run on AWS (ECS/EC2/Lambda) with an IAM role, you can omit keys
    # and boto3 will use the role automatically.
    kwargs = {"region_name": region}
    if aws_access_key_id and aws_secret_access_key:
        kwargs["aws_access_key_id"] = aws_access_key_id
        kwargs["aws_secret_access_key"] = aws_secret_access_key

    return boto3.client("s3", **kwargs)


def _bucket() -> str:
    bucket = current_app.config.get("AWS_S3_BUCKET")
    if not bucket:
        raise ValueError("AWS_S3_BUCKET is not configured")
    return bucket


def s3_upload_bytes(
    key: str,
    data: bytes,
    content_type: str = "application/octet-stream",
    acl: Optional[str] = None,
) -> str:
    """
    Upload a bytes buffer to S3 at the given key.
    Returns an s3:// URL string.
    """
    extra = {"ContentType": content_type}
    if acl:
        extra["ACL"] = acl

    _client().put_object(Bucket=_bucket(), Key=key, Body=data, **extra)
    return f"s3://{_bucket()}/{key}"


def s3_upload_fileobj(
    key: str,
    fileobj,
    content_type: Optional[str] = None,
    acl: Optional[str] = None,
) -> str:
    """
    Upload a file-like object to S3 (e.g., from Flask's request.files['file']).
    """
    # If caller didn’t pass content_type, try to guess from file object meta
    ct = content_type
    if not ct and hasattr(fileobj, "mimetype"):
        ct = fileobj.mimetype or "application/octet-stream"
    elif not ct:
        ct = "application/octet-stream"

    data = fileobj.read()
    if hasattr(fileobj, "seek"):
        fileobj.seek(0)  # rewind so caller can re-read if needed
    return s3_upload_bytes(key, data, content_type=ct, acl=acl)


def s3_presign_get(key: str, expires_in: int = 300) -> str:
    """
    Create a time-limited HTTPS URL to download the object.
    """
    return _client().generate_presigned_url(
        "get_object",
        Params={"Bucket": _bucket(), "Key": key},
        ExpiresIn=expires_in,
    )


def s3_delete(key: str) -> None:
    """
    Delete an object (handy for tests or admin cleanup).
    """
    _client().delete_object(Bucket=_bucket(), Key=key)
