import argparse
from dataclasses import dataclass
from typing import Any

import yaml
from fastapi import Depends, FastAPI
from pydantic import BaseModel

from .api import deploy_device, generate_endpoints
from .auth import AuthUnit, auth
from .devices import LoadedDevice, load_devices


class DeploymentConfig(BaseModel):
    library: str
    device_config: str
    admin_token: str
    single_process: bool = True
    host: str = "0.0.0.0"
    port: int = 8000


def load_deployment_config(config_path: str) -> DeploymentConfig:
    with open(config_path) as file:
        raw = yaml.safe_load(file) or {}
    return DeploymentConfig.model_validate(raw)


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
    endpoint_maps = [generate_endpoints(device, service, auth=auth_unit, lock=lock) for device in devices]
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
    deployment_config_path: str,
    single_process_mode: bool = True,
) -> FastAPI:
    # Startup-only registration: devices are loaded once from deployment config.
    devices = load_devices(library, device_config_path)
    lock = EndpointLockState()

    service = FastAPI()
    auth_unit = auth(deployment_config_path)

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
    config = load_deployment_config(deployment_config_path)
    single_process_mode = config.single_process if single_process_override is None else single_process_override
    service = build_service(
        library=config.library,
        device_config_path=config.device_config,
        deployment_config_path=deployment_config_path,
        single_process_mode=single_process_mode,
    )
    return service, config


def deploy():
    parser = argparse.ArgumentParser()
    parser.add_argument("--deployment-config", type=str, required=True)
    parser.add_argument(
        "--single-process",
        action="store_true",
        default=None,
        help="Override deployment-config single_process=true",
    )
    parser.add_argument(
        "--per-device-process",
        action="store_true",
        help="Override deployment-config single_process=false",
    )
    parser.add_argument("--host", type=str, default=None)
    parser.add_argument("--port", type=int, default=None)

    args = parser.parse_args()

    if args.single_process and args.per_device_process:
        raise ValueError("Choose at most one override: --single-process or --per-device-process")

    single_process_override = None
    if args.single_process:
        single_process_override = True
    elif args.per_device_process:
        single_process_override = False

    service, config = build_service_from_deployment_config(
        deployment_config_path=args.deployment_config,
        single_process_override=single_process_override,
    )

    import uvicorn

    host = args.host if args.host is not None else config.host
    port = args.port if args.port is not None else config.port
    uvicorn.run(service, host=host, port=port)


if __name__ == "__main__":
    deploy()



