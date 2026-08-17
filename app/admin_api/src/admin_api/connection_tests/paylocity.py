"""Live Paylocity connection test via SFTP probe.

Paylocity integrations use SFTP (port 22) with password or key-file auth.
Habeas stores host/username/auth material in Secret Manager and probes by
opening an SFTP session and optionally listing the configured directory.
"""

from __future__ import annotations

import asyncio
import logging
from io import StringIO
from typing import Any

logger = logging.getLogger(__name__)

_SYSTEM = "paylocity"
_DEFAULT_PORT = 22
_CONNECT_TIMEOUT_SECONDS = 10.0


def _safe_triage(**fields: Any) -> dict[str, Any]:
    return {key: value for key, value in fields.items() if value is not None}


def _probe_sftp_sync(credentials: dict[str, str]) -> tuple[bool, str, dict[str, Any]]:
    """Blocking SFTP probe — run via ``asyncio.to_thread``."""
    try:
        import paramiko
    except ImportError:  # pragma: no cover — dependency declared on admin-api
        logger.info(
            "connection_test_sftp system=%s step=import error_kind=missing_dependency detail=unknown_error",
            _SYSTEM,
        )
        return False, "unknown_error", _safe_triage(step="import", detail="unknown_error")

    host = credentials["host"]
    username = credentials["username"]
    auth_method = credentials["auth_method"]
    directory = credentials.get("directory") or ""
    port_raw = credentials.get("port") or str(_DEFAULT_PORT)
    try:
        port = int(port_raw)
    except ValueError:
        return False, "invalid_config", _safe_triage(step="parse_port", detail="invalid_config")
    if port != _DEFAULT_PORT:
        return False, "invalid_config", _safe_triage(
            step="parse_port",
            detail="invalid_config",
            port=port,
        )

    client = paramiko.SSHClient()
    # Onboarding probe accepts the presented host key for this session only
    # (not persisted). Never log key material or passwords.
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    connect_kwargs: dict[str, Any] = {
        "hostname": host,
        "port": port,
        "username": username,
        "timeout": _CONNECT_TIMEOUT_SECONDS,
        "allow_agent": False,
        "look_for_keys": False,
    }
    step = "sftp_connect"
    if auth_method == "password":
        connect_kwargs["password"] = credentials["password"]
    else:
        try:
            pkey = paramiko.RSAKey.from_private_key(StringIO(credentials["private_key"]))
        except Exception:
            try:
                pkey = paramiko.Ed25519Key.from_private_key(StringIO(credentials["private_key"]))
            except Exception:
                logger.info(
                    "connection_test_sftp system=%s step=parse_key error_kind=invalid_key detail=invalid_credentials",
                    _SYSTEM,
                )
                return False, "invalid_credentials", _safe_triage(
                    step="parse_key",
                    detail="invalid_credentials",
                    error_kind="invalid_key",
                )
        connect_kwargs["pkey"] = pkey

    try:
        client.connect(**connect_kwargs)
        step = "sftp_open"
        sftp = client.open_sftp()
        try:
            if directory:
                step = "sftp_chdir"
                sftp.chdir(directory)
            step = "sftp_listdir"
            sftp.listdir(".")
        finally:
            sftp.close()
    except paramiko.AuthenticationException:
        logger.info(
            "connection_test_sftp system=%s step=%s error_kind=auth detail=auth_failed",
            _SYSTEM,
            step,
        )
        return False, "auth_failed", _safe_triage(
            step=step,
            detail="auth_failed",
            error_kind="auth",
        )
    except TimeoutError:
        logger.info(
            "connection_test_sftp system=%s step=%s error_kind=timeout detail=timeout",
            _SYSTEM,
            step,
        )
        return False, "timeout", _safe_triage(step=step, detail="timeout", error_kind="timeout")
    except OSError as exc:
        # Includes socket.timeout on some platforms, connection refused, DNS.
        errno_name = type(exc).__name__
        if "timeout" in str(exc).casefold() or errno_name == "timeout":
            logger.info(
                "connection_test_sftp system=%s step=%s error_kind=timeout detail=timeout",
                _SYSTEM,
                step,
            )
            return False, "timeout", _safe_triage(step=step, detail="timeout", error_kind="timeout")
        logger.info(
            "connection_test_sftp system=%s step=%s error_kind=connect_error detail=unreachable",
            _SYSTEM,
            step,
        )
        return False, "unreachable", _safe_triage(
            step=step,
            detail="unreachable",
            error_kind="connect_error",
        )
    except Exception:
        logger.info(
            "connection_test_sftp system=%s step=%s error_kind=unknown detail=unknown_error",
            _SYSTEM,
            step,
        )
        return False, "unknown_error", _safe_triage(
            step=step,
            detail="unknown_error",
            error_kind="unknown",
        )
    finally:
        client.close()

    logger.info(
        "connection_test_sftp system=%s step=sftp_listdir error_kind=ok detail=paylocity_ok",
        _SYSTEM,
    )
    return True, "paylocity_ok", _safe_triage(step="sftp_listdir", detail="paylocity_ok")


async def test_paylocity(credentials: dict[str, str]) -> tuple[bool, str, dict]:
    return await asyncio.to_thread(_probe_sftp_sync, credentials)


# Not a pytest test — called by connection_testers dispatcher.
test_paylocity.__test__ = False
