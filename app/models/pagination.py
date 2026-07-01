from typing import Annotated

from fastapi import Query
from pydantic import BaseModel, Field


class PaginationParams(BaseModel):
    limit: int = Field(100, gt=0, le=100)
    offset: int = Field(0, ge=0)

PaginationQuery = Annotated[PaginationParams, Query()]