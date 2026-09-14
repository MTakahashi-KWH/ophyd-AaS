from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException

from .devices import LoadedDevice


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


def _route_path(base: Path, suffix: str) -> str:
    raw = str(base / suffix).replace("\\", "/").strip("/")
    return f"/{raw}" if raw else f"/{suffix}"


def generate_endpoints(
    device: LoadedDevice,
    service: FastAPI,
    auth=None,
    lock=None,
    base_path: Path | None = None,
) -> dict[str, str]:
    # procedurally tags on endpoints to the provided service based on the device given
    # Build core protocol endpoints only for MVP: describe/read/put.
    base_path = Path(device.alias) if base_path is None else base_path
    structure = device.instance.describe()

    def get_handler(method):
        return lambda: method()

    def make_put_handler(method, struct: Any):
        def put_handler(payload: dict[str, Any] = Body(...)):
            if device.read_only:
                raise HTTPException(status_code=403, detail="Device is read-only")
            if lock is not None and lock.is_active():
                raise HTTPException(status_code=423, detail="Global mutation lock is enabled")

            if "value" not in payload:
                raise HTTPException(status_code=422, detail="PUT payload must include a 'value' key")

            value = payload["value"]
            _validate_input_type(value, struct)
            return method(value)

        return put_handler

    def register_nested_get_endpoints(obj: Any, path: Path) -> None:
        #for any recursive structure
        for component_name in getattr(obj, "component_names", ()):
            child = getattr(obj, component_name, None)
            if child is None:
                continue

            child_path = path / component_name
            if hasattr(child, "describe"):
                describe_path = _route_path(child_path, "describe")
                service.add_api_route(describe_path, get_handler(child.describe), methods=["GET"])
                calls[describe_path] = "GET"

            if hasattr(child, "read"):
                read_path = _route_path(child_path, "read")
                service.add_api_route(read_path, get_handler(child.read), methods=["GET"])
                calls[read_path] = "GET"

            if getattr(child, "component_names", ()):
                register_nested_get_endpoints(child, child_path)

    # Future path for full ophyd tree generation:
    #
    # def traverse_components(struct, obj, path: Path):
    #     yield path / "describe", obj.describe, None
    #     yield path / "read", obj.read, None
    #     if hasattr(obj, "put"):
    #         yield path / "put", obj.put, struct
    #     for component_name, component_struct in struct.items():
    #         child = getattr(obj, component_name, None)
    #         if child is None or not hasattr(child, "describe"):
    #             continue
    #         child_path = path / component_name
    #         yield from traverse_components(component_struct, child, child_path)
    #
    # for path, method, struct in traverse_components(structure, device.instance, base_path):
    #     if path.name == "put":
    #         service.add_api_route(str(path), make_put_handler(method, struct), methods=["PUT"])
    #     else:
    #         service.add_api_route(str(path), lambda: method(), methods=["GET"])
    #
    # Nested read/describe registration is enabled below for MVP structure, while
    # nested put/trigger/configure are still intentionally deferred.

    calls: dict[str, str] = {}
    describe_path = _route_path(base_path, "describe")
    service.add_api_route(describe_path, get_handler(device.instance.describe), methods=["GET"])
    calls[describe_path] = "GET"

    read_path = _route_path(base_path, "read")
    service.add_api_route(read_path, get_handler(device.instance.read), methods=["GET"])
    calls[read_path] = "GET"

    register_nested_get_endpoints(device.instance, base_path)

    info_path = _route_path(base_path, "info")
    service.add_api_route(
        info_path,
        lambda: {
            "registry_key": device.registry_key,
            "alias": device.alias,
            "prefix": device.prefix,
            "read_only": device.read_only,
        },
        methods=["GET"],
    )
    calls[info_path] = "GET"

    capabilities_path = _route_path(base_path, "capabilities")
    service.add_api_route(
        capabilities_path,
        lambda: {
            "describe": True,
            "read": True,
            "put": hasattr(device.instance, "put"),
            "trigger": False,
        },
        methods=["GET"],
    )
    calls[capabilities_path] = "GET"

    # If describe() returns exactly one field, use its metadata for PUT validation.
    if hasattr(device.instance, "put"):
        put_struct = None
        if isinstance(structure, dict) and len(structure) == 1:
            put_struct = next(iter(structure.values()))
        put_path = _route_path(base_path, "put")
        service.add_api_route(put_path, make_put_handler(device.instance.put, put_struct), methods=["PUT"])
        calls[put_path] = "PUT"

    return calls


def deploy_device(device: LoadedDevice, manager_service: FastAPI, auth=None, lock=None):
    device_app = FastAPI()
    endpoints = generate_endpoints(device, device_app, auth=auth, lock=lock, base_path=Path())
    manager_service.mount(_route_path(Path(device.alias), ""), device_app)
    return endpoints
