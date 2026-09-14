from typing import List, Optional, Tuple
from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import or_, text
from sqlalchemy.orm import Session

from app.auth import (
    create_user_session,
    get_current_session,
    hash_password,
    require_authenticated_user,
    terminate_session,
    verify_password,
)
from app.database import get_db
from app.models import Author, Book, User, UserSession
from app.schemas import (
    AuthorCreate,
    AuthorDetailResponse,
    AuthorResponse,
    AuthorUpdate,
    BookCreate,
    BookDetailResponse,
    BookResponse,
    BookUpdate,
    MessageResponse,
    SessionResponse,
    UserLogin,
    UserRegister,
    UserResponse,
)

# Notice: Base.metadata.create_all(bind=engine) is intentionally NOT called.
# Schema creation and evolution are handled strictly via Alembic migrations.

app = FastAPI(
    title="Bookstore API",
    description=(
        "A complete REST API for managing Authors and Books built with FastAPI, "
        "PostgreSQL, Alembic migrations, and database-backed Session Authentication.\n\n"
        "### Authentication\n"
        "1. Register a user at `/api/v1/auth/register`\n"
        "2. Log in at `/api/v1/auth/login` to receive a `session_token`\n"
        "3. Click the **Authorize** button at the top right of `/docs` and paste the token into the Bearer token field.\n"
        "4. Write endpoints (`POST`, `PUT`, `DELETE`) require an active session. Read endpoints (`GET`) are public."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==========================================
# Root & Health Check
# ==========================================

@app.get("/", tags=["General"])
def root():
    return {
        "message": "Welcome to the Bookstore API",
        "docs_url": "/docs",
        "redoc_url": "/redoc",
        "version": "1.0.0",
    }


@app.get("/health", tags=["General"])
def health_check(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        db_status = "healthy"
    except Exception as e:
        db_status = f"unhealthy: {str(e)}"
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"status": "unhealthy", "database": db_status},
        )
    return {"status": "ok", "database": db_status}


# ==========================================
# Authentication Endpoints
# ==========================================

@app.post(
    "/api/v1/auth/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Authentication"],
    summary="Register a new user",
)
def register_user(payload: UserRegister, db: Session = Depends(get_db)):
    # Check if username or email already exists
    existing_user = (
        db.query(User)
        .filter(or_(User.username == payload.username, User.email == payload.email))
        .first()
    )
    if existing_user:
        if existing_user.username == payload.username:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A user with this username already exists.",
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A user with this email already exists.",
        )

    new_user = User(
        username=payload.username,
        email=payload.email,
        hashed_password=hash_password(payload.password),
        is_active=True,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user


@app.post(
    "/api/v1/auth/login",
    response_model=SessionResponse,
    tags=["Authentication"],
    summary="Log in and create a user session",
)
def login_user(payload: UserLogin, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == payload.username).first()
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is deactivated.",
        )

    session = create_user_session(db, user)
    return {
        "session_token": session.session_token,
        "token_type": "Bearer",
        "expires_at": session.expires_at,
        "user": user,
    }


@app.post(
    "/api/v1/auth/logout",
    response_model=MessageResponse,
    tags=["Authentication"],
    summary="Log out and invalidate current session",
)
def logout_user(
    auth_data: Tuple[User, UserSession] = Depends(get_current_session),
    db: Session = Depends(get_db),
):
    _, session = auth_data
    terminate_session(db, session.session_token)
    return {"message": "Successfully logged out. Session has been invalidated."}


@app.get(
    "/api/v1/auth/me",
    response_model=UserResponse,
    tags=["Authentication"],
    summary="Get current authenticated user profile",
)
def get_me(current_user: User = Depends(require_authenticated_user)):
    return current_user


# ==========================================
# Author Endpoints (CRUD)
# ==========================================

@app.post(
    "/api/v1/authors",
    response_model=AuthorResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Authors"],
    summary="Create a new author (Requires Session Auth)",
)
def create_author(
    payload: AuthorCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_authenticated_user),
):
    author = Author(
        name=payload.name,
        bio=payload.bio,
        birth_date=payload.birth_date,
    )
    db.add(author)
    db.commit()
    db.refresh(author)
    return author


@app.get(
    "/api/v1/authors",
    response_model=List[AuthorResponse],
    tags=["Authors"],
    summary="List all authors (Public)",
)
def list_authors(
    skip: int = Query(0, ge=0, description="Records to skip for pagination"),
    limit: int = Query(20, ge=1, le=100, description="Max records to return"),
    search: Optional[str] = Query(None, description="Search author by name"),
    db: Session = Depends(get_db),
):
    query = db.query(Author)
    if search:
        query = query.filter(Author.name.ilike(f"%{search}%"))
    authors = query.order_by(Author.id.asc()).offset(skip).limit(limit).all()
    return authors


@app.get(
    "/api/v1/authors/{author_id}",
    response_model=AuthorDetailResponse,
    tags=["Authors"],
    summary="Get author details with list of books (Public)",
)
def get_author(author_id: int, db: Session = Depends(get_db)):
    author = db.query(Author).filter(Author.id == author_id).first()
    if not author:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Author with id {author_id} not found.",
        )
    return author


@app.put(
    "/api/v1/authors/{author_id}",
    response_model=AuthorResponse,
    tags=["Authors"],
    summary="Update author details (Requires Session Auth)",
)
def update_author(
    author_id: int,
    payload: AuthorUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_authenticated_user),
):
    author = db.query(Author).filter(Author.id == author_id).first()
    if not author:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Author with id {author_id} not found.",
        )

    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(author, field, value)

    db.commit()
    db.refresh(author)
    return author


@app.delete(
    "/api/v1/authors/{author_id}",
    response_model=MessageResponse,
    tags=["Authors"],
    summary="Delete an author and their books (Requires Session Auth)",
)
def delete_author(
    author_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_authenticated_user),
):
    author = db.query(Author).filter(Author.id == author_id).first()
    if not author:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Author with id {author_id} not found.",
        )

    db.delete(author)
    db.commit()
    return {"message": f"Author with id {author_id} and all related books deleted successfully."}


# ==========================================
# Book Endpoints (CRUD)
# ==========================================

@app.post(
    "/api/v1/books",
    response_model=BookResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Books"],
    summary="Create a new book (Requires Session Auth)",
)
def create_book(
    payload: BookCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_authenticated_user),
):
    # Verify that author exists
    author = db.query(Author).filter(Author.id == payload.author_id).first()
    if not author:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Author with id {payload.author_id} does not exist.",
        )

    # Check for unique ISBN if provided
    if payload.isbn:
        existing_isbn = db.query(Book).filter(Book.isbn == payload.isbn).first()
        if existing_isbn:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Book with ISBN '{payload.isbn}' already exists.",
            )

    book = Book(
        title=payload.title,
        description=payload.description,
        isbn=payload.isbn,
        published_year=payload.published_year,
        price=payload.price,
        author_id=payload.author_id,
    )
    db.add(book)
    db.commit()
    db.refresh(book)
    return book


@app.get(
    "/api/v1/books",
    response_model=List[BookResponse],
    tags=["Books"],
    summary="List all books (Public)",
)
def list_books(
    author_id: Optional[int] = Query(None, description="Filter books by author ID"),
    search: Optional[str] = Query(None, description="Search books by title"),
    skip: int = Query(0, ge=0, description="Records to skip for pagination"),
    limit: int = Query(20, ge=1, le=100, description="Max records to return"),
    db: Session = Depends(get_db),
):
    query = db.query(Book)
    if author_id is not None:
        query = query.filter(Book.author_id == author_id)
    if search:
        query = query.filter(Book.title.ilike(f"%{search}%"))

    books = query.order_by(Book.id.asc()).offset(skip).limit(limit).all()
    return books


@app.get(
    "/api/v1/books/{book_id}",
    response_model=BookDetailResponse,
    tags=["Books"],
    summary="Get book details with author info (Public)",
)
def get_book(book_id: int, db: Session = Depends(get_db)):
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Book with id {book_id} not found.",
        )
    return book


@app.put(
    "/api/v1/books/{book_id}",
    response_model=BookResponse,
    tags=["Books"],
    summary="Update a book (Requires Session Auth)",
)
def update_book(
    book_id: int,
    payload: BookUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_authenticated_user),
):
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Book with id {book_id} not found.",
        )

    update_data = payload.model_dump(exclude_unset=True)

    # If author_id is being updated, verify that author exists
    if "author_id" in update_data and update_data["author_id"] != book.author_id:
        author = db.query(Author).filter(Author.id == update_data["author_id"]).first()
        if not author:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Author with id {update_data['author_id']} does not exist.",
            )

    # If ISBN is being updated, check uniqueness
    if "isbn" in update_data and update_data["isbn"] != book.isbn:
        if update_data["isbn"] is not None:
            existing_isbn = (
                db.query(Book)
                .filter(Book.isbn == update_data["isbn"], Book.id != book_id)
                .first()
            )
            if existing_isbn:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Book with ISBN '{update_data['isbn']}' already exists.",
                )

    for field, value in update_data.items():
        setattr(book, field, value)

    db.commit()
    db.refresh(book)
    return book


@app.delete(
    "/api/v1/books/{book_id}",
    response_model=MessageResponse,
    tags=["Books"],
    summary="Delete a book (Requires Session Auth)",
)
def delete_book(
    book_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_authenticated_user),
):
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Book with id {book_id} not found.",
        )

    db.delete(book)
    db.commit()
    return {"message": f"Book with id {book_id} deleted successfully."}
