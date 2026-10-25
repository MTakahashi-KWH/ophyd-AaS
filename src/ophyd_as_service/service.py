import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import uvicorn
import yaml
from fastapi import Depends, FastAPI
from pydantic import BaseModel

from .api import deploy_device, generate_catalogue
from .auth import AuthConfig, AuthUnit, auth
from .devices import LoadedDevice, load_devices


class DeploymentConfig(BaseModel):
    library: str
    device_config: str
    auth: AuthConfig | str | None = None
    single_process: bool| None = True
    host: str = "0.0.0.0"
    port: int = 8000

class ConfigurationError(ValueError):
    ...

@dataclass
class EndpointLockState:
    active: bool = False

    def enable(self) -> None:
        self.active = True

    def disable(self) -> None:
        self.active = False

    def is_active(self) -> bool:
        return self.active


def _register_management_endpoints(
    service: FastAPI,
    auth_unit: AuthUnit,
    lock: EndpointLockState,
    devices: list[LoadedDevice],
) -> None:
    @service.get("/admin/lock/status")
    def lock_status():
        return {"active": lock.is_active()}

    @service.post("/admin/lock/enable", dependencies=[Depends(auth_unit.require_admin)])
    def enable_lock():
        lock.enable()
        return {"active": lock.is_active()}

    @service.post("/admin/lock/disable", dependencies=[Depends(auth_unit.require_admin)])
    def disable_lock():
        lock.disable()
        return {"active": lock.is_active()}

    @service.get("/admin/devices", dependencies=[Depends(auth_unit.require_admin)])
    def list_devices():
        return {
            "devices": [
                {
                    "name": d.registry_key,
                    "alias": d.alias,
                    "prefix": d.prefix,
                    "read_only": d.read_only,
                }
                for d in devices
            ]
        }


def single_process(devices: list[LoadedDevice], service: FastAPI, auth_unit: AuthUnit | None = None, lock=None):
    endpoint_maps = [generate_catalogue(device, auth=auth_unit, lock=lock) for device in devices]
    for device_catalogue in endpoint_maps:
        for endpoint, handle in device_catalogue.items():
            service.add_api_route(endpoint, handle, methods=[handle.verb])
    return endpoint_maps


def per_device_process(
    devices: list[LoadedDevice],
    service: FastAPI,
    auth_unit: AuthUnit | None = None,
    lock=None,
):
    mounted = [deploy_device(device, service, auth=auth_unit, lock=lock) for device in devices]
    return mounted


def build_service(
    library: str,
    device_config_path: str,
    auth_config: str| None = None,
    single_process_mode: bool = True,
) -> FastAPI:
    # Startup-only registration: devices are loaded once from deployment config.
    devices = load_devices(library, device_config_path)
    lock = EndpointLockState()

    service = FastAPI()
    auth_unit = auth(auth_config)

    _register_management_endpoints(service, auth_unit, lock, devices)
    if single_process_mode:
        single_process(devices, service, auth_unit=auth_unit, lock=lock)
    else:
        per_device_process(devices, service, auth_unit=auth_unit, lock=lock)

    @service.get("/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "devices": len(devices), "single_process": single_process_mode}

    return service


def build_service_from_deployment_config(
    deployment_config_path: str,
    single_process_override: bool | None = None,
) -> tuple[FastAPI, DeploymentConfig]:
    with open(deployment_config_path) as file:
        raw = yaml.safe_load(file) or {}
    config = DeploymentConfig.model_validate(raw)
    single_process_mode = config.single_process if single_process_override is None else single_process_override
    service = build_service(
        library=config.library,
        device_config_path=config.device_config,
        auth_config=config.auth,
        single_process_mode=single_process_mode,
    )
    return service, config


def deploy():
    #this is core function of this framwork with it being the entrance from CLI
    parser = argparse.ArgumentParser()
    parser.add_argument("--deployment-config", type=str, default=None)
    parser.add_argument(
        "--single-process",
        type=bool,
        default=True,
        help="Override deployment-config single_process=true",
    )
    parser.add_argument("--host", type=str, default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--lib", type=str, default=None)
    parser.add_argument("--devices", type=str,default=None)

    args = parser.parse_args()
    if config_file := args.deployment_config:
        service, config = build_service_from_deployment_config(
            deployment_config_path=config_file,
            single_process_override=args.single_process,
        )
        host = args.host if args.host is not None else config.host
        port = args.port if args.port is not None else config.port
    else:
        if not all(args.lib,args.devices,args.host,args.port):
            raise ConfigurationError('''Host library, Device Configuration, Host address,
            and Host port must be defined for a command line deployment''')
        service = build_service(
            library=args.lib,
            device_config_path=args.devices,
            single_process_mode=args.single_process
        )
        host = args.host
        port = args.port

    uvicorn.run(service, host=host, port=port)


if __name__ == "__main__":
    deploy()



