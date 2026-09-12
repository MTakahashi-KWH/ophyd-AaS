from collections import OrderedDict
from pathlib import Path

from bluesky import protocols as bp
from fastapi import FastAPI, HTTPException


def _validate_input_type(value, struct):
    #should do something with the struct['dtype'] and ['shape'] component to make sure its correct
    ...

def generate_endpoints(device,service,auth = None,lock=None):
    # should probably go from the bluesky protocol interface and travearse all standard blueksy actions
    structure = device.describe()

    def traverse(struct,device,path = None):
        if not path:
            path = Path()
        yield path / 'describe' , device.describe, None
        yield path / 'read', device.read, None
        yield path / 'put', device.write, struct
        if isinstance(device, bp.Triggerable):
            yield path / 'trigger', device, True
        for name, subelement in struct.items():
            if isinstance(subelement,OrderedDict):
                yield from traverse(subelement,getattr(subelement,name),path=path/name)

    #perhaps this should be inverted to a function call so that the different bluesky primitives can be exposed
    #like wrap(path,element,struct,call_type)
    #but i like the reduction of the tree structure as:
    # - flatten to iterable and preserve structure with the endpoint path
    calls = {}
    for path, element, struct in traverse(structure,device,Path(device.prefix)/device.alias):
        if struct:
            if isinstance(struct, dict):
                @service.put(path)
                def set(value):
                    _validate_input_type(value,struct)
                    if not lock.is_active():
                        element(value)
                calls[path] = set
            else:
                @service.put()
                def trigger():
                    if not lock.is_active():
                        element()
        else:
            @service.get(path)
            def fetch():
                return element()

            calls[path] = fetch

    #finally something to do with device meta_structure where any non protocol commands are defined for endpoint
    #generatiom, there are a lot of ophyd extensions like "do_flyscan_with_FOE(...) meta functions to support"



def deploy_device(device,manager_service,auth = None,lock=None):
    device_app = FastAPI()
    endpoints= generate_endpoints(device,device_app,auth=auth,lock=lock)
