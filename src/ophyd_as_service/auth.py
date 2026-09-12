
from collections.abc import Callable, Hashable
from typing import Annotated

import yaml

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel
from dataclasses import dataclass


class AuthConfig(BaseModel):
    secrets: str
    even_more_secrets: str
    actually_secret_secrets: str
    hashy: Hashable

@dataclass
class AuthUnit:
    dependent: OAuth2PasswordBearer
    validator: Callable


def auth(service, config_path):

    security = OAuth2PasswordBearer(tokenUrl="token")

    with open(config_path) as file:
        auth_config = AuthConfig(yaml.safe_load(file))

    @service.post("/token")
    async def login(form_data: Annotated[OAuth2PasswordRequestForm, Depends()]):

        return {"access_token": ..., "token_type": "bearer"}

    return ...


def generate_managment_endpoints(service,auth):
    ...