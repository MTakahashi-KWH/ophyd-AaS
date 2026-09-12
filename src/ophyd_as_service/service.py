import argparse
from multiprocessing import Lock

from api import deploy_device, generate_endpoints
from auth import auth
from devices import load_devices
from fastapi import FastAPI

def single_process(devices,service,auth=None,lock=None):
    endpoints = [generate_endpoints(device,service,auth = auth,lock=lock) for device in devices]

def per_device_process(devices,service,auth=None,lock=None):
    services = [deploy_device(device,service,auth = auth,lock=lock) for device in devices]

def deploy():
    parser = argparse.ArgumentParser()
    parser.add_argument("--library", type=str, required=True)
    parser.add_argument("--device-config", type=str, required=True)
    parser.add_argument("--deployment-config",type=str,required=True)
    parser.add_argument("--single-process", type=bool,default=True)

    args= parser.parse_args()

    devices = load_devices(args.library, args.device_config)
    device_lock = Lock()

    service = FastAPI()
    auth_element = auth(service, args.deployment_config)
    if args.single_process:
        single_process(devices,service,auth=auth_element,lock=device_lock)
    else:
        per_device_process(devices,service,auth=auth_element,lock=device_lock)



