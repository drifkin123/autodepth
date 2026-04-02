"""Pydantic schemas for admin API endpoints."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class ScrapeResult(BaseModel):
    results: dict[str, tuple[int, int]]
    message: str


class ScrapeLogOut(BaseModel):
    id: uuid.UUID
    source: str
    started_at: datetime
    finished_at: datetime | None
    records_found: int
    records_inserted: int
    error: str | None

    model_config = {"from_attributes": True}


class ScraperStatus(BaseModel):
    is_running: bool
    effective_secret_hint: str


class BatUrlEntry(BaseModel):
    key: str
    label: str
    path: str


class CarsComUrlEntry(BaseModel):
    key: str
    label: str
    make: str
    model: str


class TriggerRequest(BaseModel):
    bat_selected_keys: list[str] | None = None
    cars_com_selected_keys: list[str] | None = None


class SaleOut(BaseModel):
    id: uuid.UUID
    car_make: str
    car_model: str
    car_trim: str
    source: str
    source_url: str
    sale_type: str
    year: int
    mileage: int | None
    color: str | None
    asking_price: int
    sold_price: int | None
    is_sold: bool
    listed_at: datetime
    sold_at: datetime | None

    model_config = {"from_attributes": True}


class PaginatedSales(BaseModel):
    items: list[SaleOut]
    total: int
    page: int
    page_size: int
