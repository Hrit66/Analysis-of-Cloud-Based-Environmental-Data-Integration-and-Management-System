from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field
from bson import ObjectId


class PyObjectId(ObjectId):
    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v):
        if not ObjectId.is_valid(v):
            raise ValueError("Invalid ObjectId")
        return ObjectId(v)

    @classmethod
    def __get_pydantic_json_schema__(cls, field_schema):
        field_schema.update(type="string")


class AQIResult(BaseModel):
    id: PyObjectId = Field(default_factory=PyObjectId, alias="_id")
    dataset_id: str
    timestamp: datetime
    location: str
    aqi: float
    aqi_category: str
    dominant_pollutant: str
    pollutant_values: dict
    sub_indices: dict

    class Config:
        populate_by_name = True
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str, datetime: lambda v: v.isoformat()}


class AnomalyResult(BaseModel):
    id: PyObjectId = Field(default_factory=PyObjectId, alias="_id")
    dataset_id: str
    timestamp: datetime
    location: str
    parameter: str
    value: float
    is_anomaly: bool
    anomaly_score: float

    class Config:
        populate_by_name = True
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str, datetime: lambda v: v.isoformat()}


class ForecastPoint(BaseModel):
    timestamp: datetime
    predicted_value: float
    lower_bound: Optional[float] = None
    upper_bound: Optional[float] = None


class ForecastResult(BaseModel):
    id: PyObjectId = Field(default_factory=PyObjectId, alias="_id")
    dataset_id: str
    location: str
    parameter: str
    model_used: str
    forecast_horizon: int
    predictions: List[ForecastPoint]
    metrics: dict
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        populate_by_name = True
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str, datetime: lambda v: v.isoformat()}