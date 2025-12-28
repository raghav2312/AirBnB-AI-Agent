# schemas.py

from pydantic import BaseModel, Field


class Guests(BaseModel):
    adults: int = Field(ge=1, default=1)
    children: int = Field(ge=0, default=0)
    infants: int = Field(ge=0, default=0)
    pets: int = Field(ge=0, default=0)


class AirbnbSearchRequest(BaseModel):
    where: str
    check_in: str
    check_out: str
    guests: Guests


class AirbnbSearchResponse(BaseModel):
    title: str | None
    price: str | None
    rating: str | None
    reviews: str | None
    link: str | None
