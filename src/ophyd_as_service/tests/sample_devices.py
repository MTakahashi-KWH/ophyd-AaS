'''
This is a sample file to place an enum into to test out the import lib behavior for loading device descriptors
from enums.

'''


from ophyd import Component, Device, Signal
from ophyd_async.sim import SimPointDetector


class FakeDevice(Device):
    def __init__(self, prefix: str, *, name: str, **kwargs):
        super().__init__(prefix=prefix, name=name, **kwargs)
        self._value = 0

    def describe(self):
        return {self.name: {"dtype": "integer", "shape": []}}

    def read(self):
        return {self.name: {"value": self._value, "timestamp": 0.0}}

    def put(self, value):
        self._value = value
        return {"status": "ok", "value": self._value}


class NestedChild(Device):
    leaf = Component(Signal, value=7)


class NestedDevice(Device):
    child = Component(NestedChild, "CHILD:")
    scalar = Component(Signal, value=3)


DEVICES = {
    "Fake": FakeDevice,
    "Child": NestedChild,
    "Nested": NestedDevice,
    "AsyncSensor": SimPointDetector,
}
