
import importlib
from dataclasses import dataclass
from types import ModuleType
from typing import Any

import yaml
from ophyd import Device
from pydantic import BaseModel


@dataclass
class DeviceConfig:
    name: str
    prefix: str
    alias: str | None = None
    read_only: bool = False

@dataclass
class DeviceDescriptor:
    object: Device | type[Device]
    name: str | None = None
    init_params: dict[str, Any] | None = None
    meta_structure: dict[str, Any] | None = None


@dataclass
class LoadedDevice:
    registry_key: str
    prefix: str
    alias: str
    read_only: bool
    instance: Device
    meta_structure: dict[str, Any] | None = None


class ConfigFile(BaseModel):
    devices: list[DeviceConfig]


def _resolve_device_registry(module: ModuleType) -> dict[str, Any]:
    if hasattr(module, "DEVICES"):
        registry = module.DEVICES
    elif hasattr(module, "ophyd") and hasattr(module.ophyd, "DEVICES"):
        registry = module.ophyd.DEVICES
    else:
        raise ValueError("Deployment library must expose DEVICES or ophyd.DEVICES")

    if not isinstance(registry, dict):
        raise ValueError("DEVICES must be a dict-like mapping of names to descriptors")
    return registry


def _create_device_descriptor(raw_descriptor: Any) -> DeviceDescriptor:
    if isinstance(raw_descriptor, dict):
        return DeviceDescriptor(
            object=raw_descriptor["object"],
            name=raw_descriptor.get("name"),
            init_params=raw_descriptor.get("init_params"),
            meta_structure=raw_descriptor.get("meta_structure"),
        )

    if issubclass(raw_descriptor, Device):
        return DeviceDescriptor(object=raw_descriptor)

    raise ValueError(f"Unsupported device descriptor type: {type(raw_descriptor)!r}")


def _initialize_device(config: DeviceConfig, descriptor: DeviceDescriptor) -> Device:
    alias = config.alias or descriptor.name or config.name
    init_params = descriptor.init_params or {}

    if isinstance(descriptor.object, Device):
        return descriptor.object

    if isinstance(descriptor.object, type) and issubclass(descriptor.object, Device):
        return descriptor.object(config.prefix, name=alias, **init_params)

    raise ValueError(f"Device descriptor object is invalid for {config.name}")


def load_devices(library, config_path):
    lib = importlib.import_module(library)
    device_registry = _resolve_device_registry(lib)

    with open(config_path) as file:
        raw = yaml.safe_load(file) or {}
    device_config = ConfigFile.model_validate(raw)

    loaded_devices: list[LoadedDevice] = []
    for d_config in device_config.devices:
        if d_config.name not in device_registry:
            raise ValueError(f"Device {d_config.name} not found in deployment library")

        descriptor = _create_device_descriptor(device_registry[d_config.name])
        instance = _initialize_device(d_config, descriptor)
        loaded_devices.append(
            LoadedDevice(
                registry_key=d_config.name,
                prefix=d_config.prefix,
                alias=d_config.alias or descriptor.name or d_config.name,
                read_only=d_config.read_only,
                instance=instance,
                meta_structure=descriptor.meta_structure,
            )
        )

    return loaded_devices




