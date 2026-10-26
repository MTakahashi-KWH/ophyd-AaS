import inspect
from enum import StrEnum
from typing import Any, Protocol

from fastapi import Body, HTTPException


class HTTPVerb(StrEnum):
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"
    PATCH = "PATCH"


class Handler(Protocol):
    verb: HTTPVerb


async def _resolve(result):
    if inspect.isawaitable(result):
        result = await result
    return result


def _validate_input_type(value, struct):
    # Best-effort dtype validation based on describe() metadata.
    dtype = None
    if isinstance(struct, dict):
        dtype = struct.get("dtype")

    if dtype in {"number", "integer"} and not isinstance(value, (int, float)):
        raise HTTPException(status_code=422, detail=f"Expected numeric value for dtype={dtype}")
    if dtype == "integer" and not isinstance(value, int):
        raise HTTPException(status_code=422, detail="Expected integer value")
    if dtype == "string" and not isinstance(value, str):
        raise HTTPException(status_code=422, detail="Expected string value")


def _describe_struct(obj: Any) -> dict[str, Any] | None:
    try:
        describe = obj.describe()
    except (AttributeError, TypeError):
        return None
    if not isinstance(describe, dict):
        return None
    for meta in describe.values():
        if isinstance(meta, dict):
            return meta
    return None


def make_get_handler(method):
    async def get_handler():
        return await _resolve(method())

    get_handler.verb = HTTPVerb.GET
    get_handler.target = getattr(method, "__self__", None)
    return get_handler


def make_put_handler(device, method, struct: Any, lock=None):
    async def put_handler(payload: dict[str, Any] = Body(...)):
        if getattr(device, "read_only", False):
            raise HTTPException(status_code=403, detail="Device is read-only")
        if lock is not None and lock.is_active():
            raise HTTPException(status_code=423, detail="Global mutation lock is enabled")
        if "value" not in payload:
            raise HTTPException(status_code=422, detail="PUT payload must include a 'value' key")

        value = payload["value"]
        _validate_input_type(value, struct)
        return await _resolve(method(value))

    put_handler.verb = HTTPVerb.PUT
    put_handler.target = getattr(method, "__self__", None)
    return put_handler


def make_info_handler(device):
    async def info_handler():
        return {
            "registry_key": device.registry_key,
            "alias": device.alias,
            "prefix": device.prefix,
            "read_only": device.read_only,
        }

    info_handler.verb = HTTPVerb.GET
    return info_handler

def make_spec_handler(callstack):
    async def spec_handler():
        return set(callstack.keys())
    spec_handler.verb = HTTPVerb.GET
    return spec_handler
