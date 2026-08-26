from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class PresignedUpload:
    method: str
    url: str
    headers: dict[str, str]
    object_key: str
    expires_in: int


class LocalArtifactStorage:
    backend = "filesystem"

    def __init__(self, root: str):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, key, content, content_type):
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(content, indent=2) if isinstance(content, (dict, list)) else str(content), encoding="utf-8")
        return str(path)

    def local_path(self, key): return self.root / key
    def get(self, key): return self.local_path(key).read_bytes()
    def delete(self, key): self.local_path(key).unlink(missing_ok=True)
    def ping(self): return self.root.exists()


class R2ArtifactStorage:
    """Cloudflare R2 implementation of the S3-compatible artifact boundary."""
    backend = "r2"

    def __init__(self, client, bucket: str, max_bytes: int = 1024**3, presign_client=None):
        self.client, self.presign_client, self.bucket, self.max_bytes = client, presign_client or client, bucket, max_bytes

    @classmethod
    def from_environment(cls):
        import os
        import boto3
        required = ("R2_ENDPOINT_URL", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET")
        missing = [name for name in required if not os.getenv(name)]
        if missing: raise RuntimeError(f"missing R2 configuration: {', '.join(missing)}")
        client = boto3.client("s3", endpoint_url=os.environ["R2_ENDPOINT_URL"], aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"], aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"], region_name="auto")
        public_endpoint = os.getenv("R2_PUBLIC_ENDPOINT_URL")
        presign_client = boto3.client("s3", endpoint_url=public_endpoint, aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"], aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"], region_name="auto") if public_endpoint else client
        return cls(client, os.environ["R2_BUCKET"], presign_client=presign_client)

    def put(self, key, content, content_type):
        body = json.dumps(content, indent=2).encode() if isinstance(content, (dict, list)) else str(content).encode()
        if len(body) > 25 * 1024**2: raise ValueError("objects larger than 25 MB require a presigned upload")
        self.client.put_object(Bucket=self.bucket, Key=key, Body=body, ContentType=content_type)
        return key

    def delete(self, key): self.client.delete_object(Bucket=self.bucket, Key=key)
    def get(self, key): return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()
    def ping(self): self.client.head_bucket(Bucket=self.bucket); return True

    def presign_download(self, key, expires_in=900):
        return self.presign_client.generate_presigned_url("get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=expires_in)

    def presign_upload(self, workspace_id: str, session_id: str, artifact_id: str, size: int, content_type: str, expires_in: int = 900) -> PresignedUpload:
        if size <= 25 * 1024**2: raise ValueError("presigned uploads are reserved for objects larger than 25 MB")
        if size > self.max_bytes: raise ValueError("object exceeds the 1 GB upload limit")
        key = f"{workspace_id}/{session_id}/{artifact_id}"
        params = {"Bucket": self.bucket, "Key": key, "ContentType": content_type}
        url = self.presign_client.generate_presigned_url("put_object", Params=params, ExpiresIn=expires_in)
        return PresignedUpload("PUT", url, {"Content-Type": content_type}, key, expires_in)

    def create_multipart(self, key, content_type):
        result = self.client.create_multipart_upload(Bucket=self.bucket, Key=key, ContentType=content_type)
        return result["UploadId"]

    def presign_part(self, key, upload_id, part_number, expires_in=900):
        return self.presign_client.generate_presigned_url("upload_part", Params={"Bucket": self.bucket, "Key": key, "UploadId": upload_id, "PartNumber": part_number}, ExpiresIn=expires_in)

    def complete_multipart(self, key, upload_id, parts):
        return self.client.complete_multipart_upload(Bucket=self.bucket, Key=key, UploadId=upload_id, MultipartUpload={"Parts": parts})

    def size(self, key):
        return int(self.client.head_object(Bucket=self.bucket, Key=key)["ContentLength"])

    @staticmethod
    def response(upload): return asdict(upload)


def artifact_storage_from_environment(root="data/artifacts"):
    import os
    return R2ArtifactStorage.from_environment() if os.getenv("ARTIFACT_STORAGE", "local") == "r2" else LocalArtifactStorage(root)
