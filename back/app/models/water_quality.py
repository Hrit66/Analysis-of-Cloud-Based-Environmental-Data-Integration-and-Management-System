from datetime import datetime
from typing import Optional, Dict
from pydantic import BaseModel, Field
from bson import ObjectId

from app.models.dataset import PyObjectId


class WaterQualityBase(BaseModel):
    timestamp: datetime
    location: str
    ph: Optional[float] = None
    turbidity: Optional[float] = None
    tds: Optional[float] = None
    hardness: Optional[float] = None
    chlorides: Optional[float] = None
    sulfates: Optional[float] = None
    nitrates: Optional[float] = None
    fluorides: Optional[float] = None
    iron: Optional[float] = None
    manganese: Optional[float] = None
    do: Optional[float] = None
    bod: Optional[float] = None
    ammonia: Optional[float] = None
    total_coliform: Optional[float] = None
    conductivity: Optional[float] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    dataset_id: str
    dataset_type: str = "water_quality"


class WaterQualityCreate(WaterQualityBase):
    pass


class WaterQualityRecord(WaterQualityBase):
    id: PyObjectId = Field(default_factory=PyObjectId, alias="_id")
    wqi: Optional[float] = None
    wqi_category: Optional[str] = None
    sub_indices: Optional[Dict[str, float]] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    model_config = {
        "populate_by_name": True,
        "arbitrary_types_allowed": True,
        "json_encoders": {ObjectId: str, datetime: lambda v: v.isoformat()},
    }
