"""Explicit bucket setup commands; never run at application startup."""

from __future__ import annotations

import argparse
from urllib.parse import urlsplit

from botocore.exceptions import BotoCoreError, ClientError

from lifereel_api.modules.evidence.direct_uploads import STAGING_PREFIX, upload_endpoint
from lifereel_api.modules.evidence.storage import S3PrivateStorage


def configure_cors(origins: list[str]) -> None:
    upload_endpoint()
    for origin in origins:
        parsed = urlsplit(origin)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.path:
            raise ValueError("OSS_CORS_ORIGIN_INVALID")
    storage = S3PrivateStorage()
    try:
        rules = storage.client.get_bucket_cors(Bucket=storage.bucket)["CORSRules"]
    except ClientError as exc:
        if exc.response["Error"]["Code"] not in {"NoSuchCORSConfiguration", "NoSuchCORS"}:
            raise
        rules = []
    rule_id = "lifereel-browser-upload"
    rules = [rule for rule in rules if rule.get("ID") != rule_id]
    upload_rule = {
        "AllowedOrigins": sorted(set(origins)),
        "AllowedMethods": ["POST"],
        "AllowedHeaders": ["Content-Type"],
        "ExposeHeaders": ["ETag", "x-oss-request-id"],
        "MaxAgeSeconds": 600,
    }
    # OSS omits S3 CORS IDs on readback; avoid duplicate rules on repeated setup.
    if not any(
        set(rule.get("AllowedOrigins", [])) == set(origins)
        and rule.get("AllowedMethods") == ["POST"]
        for rule in rules
    ):
        rules.append(upload_rule)
    storage.client.put_bucket_cors(Bucket=storage.bucket, CORSConfiguration={"CORSRules": rules})
    print("OSS_CORS_CONFIGURED")


def configure_lifecycle() -> None:
    upload_endpoint()
    storage = S3PrivateStorage()
    try:
        rules = storage.client.get_bucket_lifecycle_configuration(Bucket=storage.bucket)["Rules"]
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "NoSuchLifecycleConfiguration":
            raise
        rules = []
    rule_id = "lifereel-upload-staging-expiry"
    rules = [rule for rule in rules if rule.get("ID") != rule_id]
    rules.append(
        {
            "ID": rule_id,
            "Status": "Enabled",
            "Prefix": STAGING_PREFIX,
            "Expiration": {"Days": 1},
        }
    )
    storage.client.put_bucket_lifecycle_configuration(
        Bucket=storage.bucket,
        LifecycleConfiguration={"Rules": rules},
    )
    print("OSS_STAGING_LIFECYCLE_CONFIGURED")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["configure-cors", "configure-lifecycle"])
    parser.add_argument("--origin", action="append", default=[])
    args = parser.parse_args()
    try:
        if args.command == "configure-cors":
            if not args.origin:
                parser.error("At least one --origin is required")
            configure_cors(args.origin)
        else:
            configure_lifecycle()
    except ClientError as exc:
        raise SystemExit(f"OSS_SETUP_FAILED:{exc.response['Error']['Code']}") from None
    except BotoCoreError:
        raise SystemExit("OSS_SETUP_NETWORK_FAILED") from None


if __name__ == "__main__":
    main()
