import uuid

from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


class GenreSchema(BaseModel):
    id: int
    name: str
    movie_count: int = 0

    model_config = {
        "from_attributes": True,
    }


class StarSchema(BaseModel):
    id: int
    name: str

    model_config = {
        "from_attributes": True,
    }


class DirectorSchema(BaseModel):
    id: int
    name: str

    model_config = {
        "from_attributes": True,
    }


class StarGenreDirectorCreateSchema(BaseModel):
    name: str

    model_config = {
        "from_attributes": True,
    }


class CertificationSchema(BaseModel):
    id: int
    name: str

    model_config = {
        "from_attributes": True,
    }


class MovieBaseSchema(BaseModel):
    name: str = Field(..., max_length=255)
    year: int
    time: int
    imdb: float
    votes: int
    meta_score: float
    gross: float
    description: str
    price: Decimal = Field(..., max_digits=10, decimal_places=2, json_schema_extra={"example": 9.99})

    model_config = {
        "from_attributes": True
    }


class MovieDetailSchema(MovieBaseSchema):
    id: int
    uuid: uuid.UUID
    certification: CertificationSchema
    genres: List[GenreSchema]
    stars: List[StarSchema]
    directors: List[DirectorSchema]

    model_config = {
        "from_attributes": True
    }


class MovieListItemSchema(BaseModel):
    id: int
    name: str
    year: int
    meta_score: float
    description: str

    model_config = {
        "from_attributes": True
    }


class MovieListResponseSchema(BaseModel):
    movies: List[MovieListItemSchema]
    prev_page: Optional[str]
    next_page: Optional[str]
    total_pages: int
    total_items: int

    model_config = {
        "from_attributes": True
    }


class MovieCreateSchema(BaseModel):
    name: str
    year: int
    time: int
    imdb: float = Field(..., ge=0, le=10, json_schema_extra={"example": 8.5})
    votes: int
    meta_score: float
    gross: float
    description: str
    price: Decimal
    genres: List[str]
    stars: List[str]
    directors: List[str]
    certification: str

    model_config = {
        "from_attributes": True
    }

    @field_validator("genres", "stars", "directors", mode="before")
    @classmethod
    def normalize_list_fields(cls, value: List[str]) -> List[str]:
        return [item.title() for item in value]


class MovieUpdateSchema(BaseModel):
    name: Optional[str] = None
    year: Optional[int] = None
    time: Optional[int] = None
    meta_score: Optional[float] = Field(None, ge=0, le=100)
    description: Optional[str] = None
    price: Optional[Decimal] = Field(None, ge=0)
    gross: Optional[float] = Field(None, ge=0)

    model_config = {
        "from_attributes": True
    }
