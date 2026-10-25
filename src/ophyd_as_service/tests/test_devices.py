import json
from pathlib import Path

from pydantic import TypeAdapter

from ophyd_as_service.devices import ConfigFile, DeviceConfig, load_devices


def test_device_config_name_is_container_scoped():
    config = DeviceConfig(prefix="XF32ID1{NESTED}")
    assert config.prefix == "XF32ID1{NESTED}"
    assert not hasattr(config, "name")

    parsed = ConfigFile.model_validate({'devices':{"Fake": {"prefix": "XF32ID1{NESTED}"}}})
    assert parsed.devices["Fake"].prefix == "XF32ID1{NESTED}"


def test_device_loads():
    work_dir = Path.cwd() / "src" / "ophyd_as_service" / "tests" / "sample_config.yaml"
    devs = load_devices("ophyd_as_service.tests.sample_devices", work_dir)
    devices_by_name = {d.registry_key: d for d in devs}

    assert set(devices_by_name) == {"Nested", "Fake","AsyncSensor"}
    assert devices_by_name["Nested"].alias == "Matroshka"
    assert devices_by_name["Nested"].prefix == "XF32ID1{NESTED}"
    assert devices_by_name["Fake"].prefix == "XF32ID1{NESTED}"


if __name__ == "__main__":
    test_device_loads()
