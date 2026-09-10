"""Create a private production env from a transferred local configuration."""

from __future__ import annotations

import argparse
import os
import secrets
from pathlib import Path

from dotenv import dotenv_values, set_key


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--domain")
    args = parser.parse_args()
    if args.target.exists():
        raise SystemExit("TARGET_ALREADY_EXISTS")
    values = dotenv_values(args.source)
    required = [
        "S3_ACCESS_KEY", "S3_SECRET_KEY", "S3_BUCKET", "S3_ENDPOINT_URL",
        "OPENAI_COMPATIBLE_API_KEY", "OPENAI_COMPATIBLE_BASE_URL",
        "VOLCENGINE_API_KEY", "BOOTSTRAP_OWNER_EMAIL", "BOOTSTRAP_OWNER_PASSWORD",
    ]
    missing = [name for name in required if not values.get(name)]
    if missing:
        raise SystemExit("MISSING_CONFIG:" + ",".join(missing))
    password = secrets.token_hex(24)
    values.update({
        "APP_ENV": "production",
        "API_ACCESS_KEY": secrets.token_hex(32),
        "AUTH_TOKEN_SECRET": secrets.token_hex(48),
        "POSTGRES_PASSWORD": password,
        "DATABASE_URL": f"postgresql+psycopg://lifereel:{password}@postgres:5432/lifereel",
        "REDIS_URL": "redis://redis:6379/0",
        "STORAGE_BACKEND": "s3",
        "OSS_DIRECT_UPLOAD_ENABLED": "true",
        "AUTO_CREATE_SCHEMA": "false",
        "EXECUTE_MOCK_JOBS_INLINE": "false",
        "REGISTRATION_ENABLED": "false",
        "AUTH_COOKIE_SECURE": "false",
        "WHISPER_MODEL_PATH": "/models/whisper-small",
        "WHISPER_DEVICE": "cpu",
        "WHISPER_COMPUTE_TYPE": "int8",
        "MANUAL_WECHAT_QR_PATH": "/data/payments/wechat-qr.png",
        "VITE_DEV_API_TARGET": "http://127.0.0.1:8000",
    })
    if args.domain:
        values.update({
            "AUTH_COOKIE_SECURE": "true",
            "API_CORS_ORIGINS": f"https://{args.domain}",
        })
    os.umask(0o077)
    args.target.touch(mode=0o600, exist_ok=False)
    for key, value in values.items():
        if value is not None:
            set_key(str(args.target), key, value, quote_mode="always")
    args.target.chmod(0o600)
    print("PRODUCTION_ENV_CREATED: no secrets printed")


if __name__ == "__main__":
    main()
