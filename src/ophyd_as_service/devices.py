
import importlib
from dataclasses import dataclass
from types import ModuleType
from typing import Any

import yaml
from ophyd import Device
from pydantic import BaseModel


@dataclass
class DeviceConfig:             # the device configuration given to OaaS
    prefix: str
    alias: str | None = None
    read_only: bool = False

@dataclass
class DeviceDescriptor:         # the device descriptor given by the library supplying devices
    object: Device | type[Device]
    name: str | None = None
    init_params: dict[str, Any] | None = None
    meta_structure: dict[str, Any] | None = None


@dataclass
class LoadedDevice:             # a combined runtime description of the device resolving from config and descriptor
    registry_key: str
    prefix: str
    alias: str
    read_only: bool
    instance: Device
    meta_structure: dict[str, Any] | None = None


class ConfigFile(BaseModel):
    devices: dict[str, DeviceConfig]
    # @classmethod
    # def model_validate_mapping(cls, raw: Any) -> "ConfigFile":
    #     raw = (raw or {}).get("devices", raw or {})
    #     if isinstance(raw, list):
    #         raw = {e["name"]: {k: v for k, v in e.items() if k != "name"} for e in raw}
    #     if not isinstance(raw, dict):
    #         raise ValueError("Device config file must contain a dictionary of device settings")
    #     return cls(devices={k: DeviceConfig(**v) if isinstance(v, dict) else v for k, v in raw.items()})


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


def _initialize_device(config: DeviceConfig, descriptor: DeviceDescriptor, registry_key: str | None = None) -> Device:
    alias = config.alias or descriptor.name or registry_key
    init_params = descriptor.init_params or {}

    if isinstance(descriptor.object, Device):
        return descriptor.object

    if isinstance(descriptor.object, type) and issubclass(descriptor.object, Device):
        return descriptor.object(config.prefix, name=alias, **init_params)

    raise ValueError(f"Device descriptor object is invalid for {registry_key}")


def load_devices(library, config_path):
    lib = importlib.import_module(library)
    device_registry = _resolve_device_registry(lib)

    with open(config_path) as file:
        raw = yaml.safe_load(file) or {}
    device_config = ConfigFile.model_validate(raw)

    loaded_devices: list[LoadedDevice] = []
    for registry_key, d_config in device_config.devices.items():
        if registry_key not in device_registry:
            raise ValueError(f"Device {registry_key} not found in deployment library")

        descriptor = _create_device_descriptor(device_registry[registry_key])
        instance = _initialize_device(d_config, descriptor, registry_key)
        loaded_devices.append(
            LoadedDevice(
                registry_key=registry_key,
                prefix=d_config.prefix,
                alias=d_config.alias or descriptor.name or registry_key,
                read_only=d_config.read_only,
                instance=instance,
                meta_structure=descriptor.meta_structure,
            )
        )

    return loaded_devices




