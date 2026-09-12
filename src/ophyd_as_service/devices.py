
# from dataclasses import dataclass
import importlib
from collections.abc import Callable, Iterable

import yaml
from ophyd import Device
from pydantic import BaseModel, dataclasses


@dataclasses.dataclass
class DeviceConfig:
    name: str
    prefix: str
    alias: str | None = None
    read_only: bool = False

@dataclasses.dataclass
class DeviceDescriptor:
    object: Device | type[Device]
    name: str = None
    init_params: dict[str,any] | None = None
    meta_structure: dict[str,any] | None = None

class ConfigFile(BaseModel):
    devices: list[DeviceConfig]

OphydObject = DeviceConfig | DeviceDescriptor

def load_devices(library, config_path):
    lib = importlib.import_module(library)
    device_enum = lib.ophyd.DEVICES

    with open(config_path) as file:
        device_config = ConfigFile(yaml.safe_load(file))

    DeviceList = []
    for d_config in device_config:
        dev = device_enum[d_config.name]
        if isinstance(dev, Device):
            device = dev(d_config.prefix,name=d_config.alias or d_config.name)
            desc = DeviceDescriptor(device)
        elif isinstance(dev, dict):
            desc = DeviceDescriptor(**dev)
            desc.object = desc.object(dev.prefix,**desc.init_params,name= d_config.alias or desc.name)

        DeviceList.append(OphydObject(**(d_config | desc)))

    return DeviceList




