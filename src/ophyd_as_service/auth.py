from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any

import yaml
from fastapi import Header, HTTPException
from pydantic import BaseModel


class AuthConfig(BaseModel):
    admin_token: str


@dataclass
class AuthUnit:
    admin_token: str
    require_admin: Callable[..., Any]


def auth(config_path):
    # this is very open ended and i have left this so it can be improved with DI/ composition
    with open(config_path) as file:
        raw = yaml.safe_load(file) or {}

    auth_config = AuthConfig.model_validate(raw)

    async def require_admin(x_admin_token: Annotated[str | None, Header(alias="X-Admin-Token")] = None):
        if x_admin_token != auth_config.admin_token:
            raise HTTPException(status_code=401, detail="Invalid or missing admin token")

    return AuthUnit(admin_token=auth_config.admin_token, require_admin=require_admin)
