from datetime import date, datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field


# ==========================================
# Author Schemas
# ==========================================

class AuthorBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=150, examples=["George R.R. Martin"])
    bio: Optional[str] = Field(None, examples=["American novelist and short story writer."])
    birth_date: Optional[date] = Field(None, examples=["1948-09-20"])


class AuthorCreate(AuthorBase):
    pass


class AuthorUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=150, examples=["George R.R. Martin"])
    bio: Optional[str] = Field(None, examples=["American novelist and short story writer."])
    birth_date: Optional[date] = Field(None, examples=["1948-09-20"])


class BookSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    isbn: Optional[str] = None
    published_year: Optional[int] = None
    price: float


class AuthorResponse(AuthorBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime


class AuthorDetailResponse(AuthorResponse):
    books: List[BookSummary] = []


# ==========================================
# Book Schemas
# ==========================================

class BookBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=255, examples=["A Game of Thrones"])
    description: Optional[str] = Field(None, examples=["First novel in A Song of Ice and Fire series."])
    isbn: Optional[str] = Field(None, max_length=30, examples=["978-0553103540"])
    published_year: Optional[int] = Field(None, ge=1000, le=2100, examples=[1996])
    price: float = Field(..., ge=0.0, examples=[24.99])


class BookCreate(BookBase):
    author_id: int = Field(..., description="ID of the author who wrote this book")


class BookUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=255, examples=["A Game of Thrones"])
    description: Optional[str] = None
    isbn: Optional[str] = Field(None, max_length=30)
    published_year: Optional[int] = Field(None, ge=1000, le=2100)
    price: Optional[float] = Field(None, ge=0.0)
    author_id: Optional[int] = None


class AuthorSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class BookResponse(BookBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    author_id: int
    created_at: datetime
    updated_at: datetime


class BookDetailResponse(BookResponse):
    author: Optional[AuthorSummary] = None


# ==========================================
# User & Session Schemas
# ==========================================

class UserRegister(BaseModel):
    username: str = Field(..., min_length=3, max_length=50, examples=["john_doe"])
    email: str = Field(..., min_length=5, max_length=100, examples=["john@example.com"])
    password: str = Field(..., min_length=6, max_length=100, examples=["securePassword123!"])


class UserLogin(BaseModel):
    username: str = Field(..., examples=["john_doe"])
    password: str = Field(..., examples=["securePassword123!"])


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str
    is_active: bool
    created_at: datetime


class SessionResponse(BaseModel):
    session_token: str
    token_type: str = "Bearer"
    expires_at: datetime
    user: UserResponse


class MessageResponse(BaseModel):
    message: str
