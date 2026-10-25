from pathlib import Path
from typing import Any

from bluesky import protocols as bp
from fastapi import FastAPI
from ophyd import Device

from .devices import LoadedDevice
from .handlers import handler, make_get_handler, make_info_handler, make_spec_handler


def _normalize_path(pth: Path):
    raw = str(pth).replace("\\", "/").strip("/")
    return f"/{raw}"

def generate_catalogue(
    device: LoadedDevice,
    auth=None,
    lock=None,
    base_path: Path | None = None,
) -> dict[str, handler]:
    # procedurally tags on endpoints to the provided service based on the device given
    # Build core protocol endpoints only for MVP: describe/read/put.
    base_path = Path(device.alias) if base_path is None else base_path

    def get_components(obj):
        if isinstance(obj,Device):
            components = getattr(obj, "component_names", ())
            return (getattr(obj, comp) for comp in components)
        elif hasattr(obj,'children'):
            return obj.children() or ()
        return ()

    def register_endpoints_recursive(obj: Any, path: Path, override: bool = False):
        name, obj = obj if isinstance(obj,tuple) else (obj.name, obj)
        element_path = path if override else path / name

        if isinstance(obj, bp.Readable):
            describe_path = _normalize_path(element_path/ "describe")
            calls[describe_path] = make_get_handler(obj.describe)
            print(f"describing {name}:",type(obj.describe()))

            read_path = _normalize_path(element_path/ "read")
            calls[read_path] = make_get_handler(obj.read)
            print(f"reading {name}", type(obj.read()))

        for component in get_components(obj):
            print(type(obj),"->",type(component),component)
            register_endpoints_recursive(component,element_path)


    calls: dict[str, str] = {}
    register_endpoints_recursive(device.instance,base_path,override=True)

    info_path = _normalize_path(base_path/"info")
    calls[info_path] = make_info_handler(device)

    spec_path = _normalize_path(base_path/'spec')
    calls[spec_path] = make_spec_handler(calls)

    return calls

def deploy_device(device: LoadedDevice, manager_service: FastAPI, auth=None, lock=None):
    device_app = FastAPI()
    endpoint_catalogue = generate_catalogue(device, auth=auth, lock=lock,base_path=Path())

    for endpoint, handle in endpoint_catalogue.items():
        device_app.add_api_route(endpoint, handle, methods=[handle.verb])


    manager_service.mount(_normalize_path(Path(device.alias)), device_app)
    return endpoint_catalogue
