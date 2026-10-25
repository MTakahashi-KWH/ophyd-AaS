from pathlib import Path
from pprint import pprint

import pytest

from ophyd_as_service.api import generate_catalogue
from ophyd_as_service.devices import load_devices


def cat():
    work_dir = Path.cwd() / "src" / "ophyd_as_service" / "tests" / "sample_config.yaml"
    return load_devices("ophyd_as_service.tests.sample_devices", work_dir)

@pytest.fixture()
def catalog():
    return cat()

def test_sample_catalog_generates_endpoints(catalog):
    for device in catalog:
        endpoint_catalogue = generate_catalogue(device)
        pprint(list(endpoint_catalogue.keys()))


if __name__ == "__main__":
    test_sample_catalog_generates_endpoints(cat())
