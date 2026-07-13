"""Operator identity from Identity-Aware Proxy."""

from pydantic import BaseModel, EmailStr


class OperatorIdentity(BaseModel):
    email: EmailStr
