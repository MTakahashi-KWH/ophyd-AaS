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

async def no_auth() -> None:
    # FastAPI dependency that allows the request through
    return None

def auth(config: AuthConfig | str | None ):
    if config is None:
        return AuthUnit(admin_token="Carr-Purcell-Meiboom-Gill",require_admin=no_auth)

    # this is very open ended and i have left this so it can be improved with DI/ composition
    if isinstance(config,str):
        with open(config) as file:
            raw = yaml.safe_load(file) or {}
        auth_config = AuthConfig.model_validate(raw)
    else:
        auth_config = config

    async def require_admin(x_admin_token: Annotated[str | None, Header(alias="X-Admin-Token")] = None):
        if x_admin_token != auth_config.admin_token:
            raise HTTPException(status_code=401, detail="Invalid or missing admin token")

    return AuthUnit(admin_token=auth_config.admin_token, require_admin=require_admin)
