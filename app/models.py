"""JSON API 的 Pydantic 请求模型。"""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class PlotIn(BaseModel):
    farmer_id: int
    plot_type: str = Field(pattern="^(orchard|tea_garden|vegetable_field)$")
    name: str = Field(min_length=1, max_length=60)
    location: str = Field(min_length=1, max_length=120)
    area_mu: float = Field(gt=0)
    capacity: int = Field(gt=0)
    description: str = ""


class BatchIn(BaseModel):
    plot_id: int
    produce_name: str = Field(min_length=1, max_length=60)
    unit: str = Field(min_length=1, max_length=20)
    total_units: float = Field(gt=0)
    price_per_unit: float = Field(gt=0)
    season_start: date
    season_end: date


class AdoptionIn(BaseModel):
    batch_id: int
    customer_name: str = Field(min_length=1, max_length=40)
    customer_phone: str = Field(min_length=6, max_length=20)
    units: float = Field(gt=0)
    pickup_date: date
    delivery: str = Field(pattern="^(self_pick|express|logistics)$")
    address: str = ""


class ResolveIn(BaseModel):
    resolution: str = Field(pattern="^(reschedule|refund|transfer)$")
    new_pickup_date: date | None = None
    new_batch_id: int | None = None


class WeatherIn(BaseModel):
    batch_id: int
    event_date: date
    kind: str = Field(pattern="^(frost|drought|rain|storm|heat)$")
    impact: str = Field(min_length=1, max_length=120)
    yield_loss_pct: int = Field(gt=0, le=100)
    description: str = ""


class AfterSaleIn(BaseModel):
    adoption_id: int
    kind: str = Field(pattern="^(quality|shortage|delay|other)$")
    description: str = Field(min_length=1, max_length=500)


class AfterSaleUpdate(BaseModel):
    status: str = Field(pattern="^(open|processing|resolved)$")
    reply: str | None = None
