from typing import Any

from ninja import Schema


class Message(Schema):
    message: str


class Error(Schema):
    detail: str


class StatusResponse(Schema):
    status: str
    message: str = ""


class PaginatedResponse(Schema):
    data: list[Any]
    total: int
    page: int
    page_size: int
