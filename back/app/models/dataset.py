from datetime import datetime
from enum import Enum
from typing import Optional
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


class DatasetStatus(str, Enum):
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class DatasetBase(BaseModel):
    filename: str
    dataset_type: str
    original_columns: list[str]
    row_count: int = 0


class DatasetCreate(DatasetBase):
    pass


class Dataset(DatasetBase):
    id: PyObjectId = Field(default_factory=PyObjectId, alias="_id")
    status: DatasetStatus = DatasetStatus.UPLOADED
    error_message: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        populate_by_name = True
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}