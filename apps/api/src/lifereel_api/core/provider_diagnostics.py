"""Public provider diagnostics: allowlisted metadata only, never exception text/body."""

import re


def provider_error_context(exc: BaseException) -> dict:
    current: BaseException | None = exc
    for _ in range(8):
        if current is None:
            break
        diagnostic = getattr(current, "diagnostic", None)
        if isinstance(diagnostic, dict):
            context = {}
            status = diagnostic.get("http_status")
            if type(status) is int and 100 <= status <= 599:
                context["provider_http_status"] = status
            phase = diagnostic.get("phase")
            if phase in ("connect", "read", "write", "pool"):
                context["provider_timeout_phase"] = phase
            request_id = diagnostic.get("request_id")
            if (isinstance(request_id, str)
                    and re.fullmatch(r"[A-Za-z0-9_.:-]{1,200}", request_id)):
                context["provider_request_id"] = request_id
            if context:
                return context
        current = current.__cause__
    return {}
