"""Narrow bridge to the app-owned macOS Keychain helper."""

import json
import os
from pathlib import Path
import subprocess

from .state import APIError, clean_env


PROVIDERS = frozenset(("hf-download", "hf-upload", "modelscope-download"))
OPERATIONS = frozenset(("get", "set", "status", "delete"))
MAX_MESSAGE_BYTES = 16 * 1024
MAX_SECRET_BYTES = 8 * 1024


class Credentials:
    def __init__(self, helper=None):
        configured = helper if helper is not None else os.environ.get("TFM_KEYCHAIN_HELPER", "")
        self.helper = Path(configured).expanduser() if configured else None

    def _validated_helper(self):
        helper = self.helper
        if helper is None or not helper.is_absolute() or not helper.is_file() or not os.access(helper, os.X_OK):
            raise APIError("The app credential helper is unavailable", "credential_helper_unavailable", 409)
        return helper.resolve()

    @staticmethod
    def _validate_provider(provider):
        if provider not in PROVIDERS:
            raise APIError("Unsupported credential provider")
        return provider

    def _call(self, operation, provider, token=None):
        if operation not in OPERATIONS:
            raise APIError("Unsupported credential operation")
        provider = self._validate_provider(provider)
        request = {"operation": operation, "provider": provider}
        if operation == "set":
            if not isinstance(token, str) or not token or any(ord(character) < 32 or ord(character) == 127 for character in token):
                raise APIError("Credential token is required")
            if len(token.encode("utf-8")) > MAX_SECRET_BYTES:
                raise APIError("Credential token exceeds 8192 bytes")
            request["token"] = token
        elif token is not None:
            raise APIError("Credential token is only accepted by set")
        encoded = json.dumps(request, separators=(",", ":"), ensure_ascii=False)
        if len(encoded.encode("utf-8")) > MAX_MESSAGE_BYTES:
            raise APIError("Credential request is too large")
        try:
            completed = subprocess.run(
                [str(self._validated_helper())],
                input=encoded,
                text=True,
                capture_output=True,
                timeout=10,
                env=clean_env(),
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            raise APIError("The app credential helper failed", "credential_helper_failed", 409)
        if completed.returncode != 0 or len(completed.stdout.encode("utf-8")) > MAX_MESSAGE_BYTES:
            raise APIError("The app credential helper failed", "credential_helper_failed", 409)
        try:
            response = json.loads(completed.stdout)
        except (TypeError, ValueError):
            raise APIError("The app credential helper returned an invalid response", "credential_helper_failed", 409)
        allowed = {"configured", "token"} if operation == "get" else {"configured"}
        if (
            not isinstance(response, dict)
            or set(response) - allowed
            or set(response) < {"configured"}
            or not isinstance(response["configured"], bool)
            or (operation != "get" and "token" in response)
        ):
            raise APIError("The app credential helper returned an invalid response", "credential_helper_failed", 409)
        if operation == "get" and response["configured"]:
            secret = response.get("token")
            if (
                set(response) != {"configured", "token"}
                or not isinstance(secret, str)
                or not secret
                or any(ord(character) < 32 or ord(character) == 127 for character in secret)
                or len(secret.encode("utf-8")) > MAX_SECRET_BYTES
            ):
                raise APIError("The app credential helper returned an invalid response", "credential_helper_failed", 409)
        elif operation == "get" and set(response) != {"configured"}:
            raise APIError("The app credential helper returned an invalid response", "credential_helper_failed", 409)
        return response

    def status(self, provider):
        response = self._call("status", provider)
        return {"provider": provider, "configured": response["configured"]}

    def set(self, provider, token):
        response = self._call("set", provider, token)
        return {"provider": provider, "configured": response["configured"]}

    def get(self, provider):
        response = self._call("get", provider)
        if not response["configured"]:
            raise APIError("Credential is not configured", "credential_missing", 409)
        return response["token"]

    def delete(self, provider):
        response = self._call("delete", provider)
        return {"provider": provider, "configured": response["configured"]}
