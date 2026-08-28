from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
from bson import ObjectId

from app.models.dataset import PyObjectId


class AirQualityBase(BaseModel):
    timestamp: datetime
    location: str
    pm25: Optional[float] = None
    pm10: Optional[float] = None
    no2: Optional[float] = None
    so2: Optional[float] = None
    co: Optional[float] = None
    o3: Optional[float] = None
    dataset_id: str
    dataset_type: str = "air_quality"


class AirQualityCreate(AirQualityBase):
    pass


class AirQualityRecord(AirQualityBase):
    id: PyObjectId = Field(default_factory=PyObjectId, alias="_id")
    aqi: Optional[float] = None
    aqi_category: Optional[str] = None
    dominant_pollutant: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    model_config = {
        "populate_by_name": True,
        "arbitrary_types_allowed": True,
        "json_encoders": {ObjectId: str, datetime: lambda v: v.isoformat()},
    }