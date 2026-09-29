from __future__ import annotations

from typing import Final, Literal

ServiceName = Literal[
    "edge", "identity", "model_gateway", "interview", "memory", "script",
    "media", "billing", "notification", "worker", "tasks", "storage",
]

SERVICE_CATALOG: Final[dict[ServiceName, dict[str, object]]] = {
    "edge": {
        "description": "Web Nginx API gateway and static frontend",
        "modules": ("web", "mini-program"),
        "runtime": "nginx",
    },
    "identity": {
        "description": "Accounts, tenants, people, roles and mini-program login",
        "modules": ("auth", "identity", "governance"),
        "runtime": "identity",
    },
    "model_gateway": {
        "description": "Provider registry, model routing, quotas and usage policy",
        "modules": ("providers",),
        "runtime": "model-gateway",
    },
    "interview": {
        "description": "Text interview, realtime voice and turn workflows",
        "modules": ("interview", "orchestration"),
        "runtime": "interview + worker-interview",
    },
    "memory": {
        "description": "Claims, entities, timeline, conflicts and biography synthesis",
        "modules": ("memory",),
        "runtime": "memory",
    },
    "script": {
        "description": "Projects, scenes, shots, references and versions",
        "modules": ("script",),
        "runtime": "script",
    },
    "media": {
        "description": "Evidence, image restoration and video production",
        "modules": ("evidence", "restoration", "production", "publication"),
        "runtime": "media + worker-media",
    },
    "billing": {
        "description": "Wallet ledger, reservations, usage and recharge orders",
        "modules": ("billing",),
        "runtime": "billing",
    },
    "notification": {
        "description": "SMS and future task notifications",
        "modules": ("auth.sms",),
        "runtime": "identity",
    },
    "worker": {
        "description": "Lease-based asynchronous execution plane",
        "modules": ("jobs",),
        "runtime": "worker-interview + worker-media",
    },
    "tasks": {
        "description": "Job API, durable event publication and cluster readiness",
        "modules": ("jobs",),
        "runtime": "tasks",
    },
    "storage": {
        "description": "Private OSS/S3 objects and signed media access",
        "modules": ("evidence.storage",),
        "runtime": "external OSS/S3",
    },
}
