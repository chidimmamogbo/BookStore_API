import os
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import app

# Test database URL
TEST_DATABASE_URL = "sqlite:///./test_bookstore.db"

test_engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
)

# Enable foreign keys for SQLite
@event.listens_for(test_engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()

TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(scope="session", autouse=True)
def setup_test_database():
    # Setup test schema
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)
    yield
    # Teardown
    Base.metadata.drop_all(bind=test_engine)
    if os.path.exists("./test_bookstore.db"):
        try:
            os.remove("./test_bookstore.db")
        except Exception:
            pass


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def auth_headers(client):
    # Register and log in a test user
    username = "testlibrarian"
    password = "SecretPassword123!"
    email = "librarian@example.com"

    # Register
    reg_resp = client.post(
        "/api/v1/auth/register",
        json={"username": username, "email": email, "password": password},
    )
    assert reg_resp.status_code in (201, 400)

    # Login
    login_resp = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    assert login_resp.status_code == 200
    token = login_resp.json()["session_token"]
    return {"Authorization": f"Bearer {token}"}


# ==========================================
# General & Health Check Tests
# ==========================================

def test_root_endpoint(client):
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert "Bookstore API" in data["message"]
    assert data["docs_url"] == "/docs"


def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["database"] == "healthy"


# ==========================================
# Authentication & Session Tests
# ==========================================

def test_user_registration_and_duplicate_handling(client):
    user_data = {
        "username": "unique_user",
        "email": "unique@example.com",
        "password": "Password123!",
    }
    # Successful registration
    resp = client.post("/api/v1/auth/register", json=user_data)
    assert resp.status_code == 201
    assert resp.json()["username"] == user_data["username"]

    # Duplicate registration should fail
    dup_resp = client.post("/api/v1/auth/register", json=user_data)
    assert dup_resp.status_code == 400
    assert "already exists" in dup_resp.json()["detail"]


def test_login_invalid_credentials(client):
    resp = client.post(
        "/api/v1/auth/login",
        json={"username": "non_existent_user", "password": "wrongpassword"},
    )
    assert resp.status_code == 401


def test_get_current_user_profile(client, auth_headers):
    resp = client.get("/api/v1/auth/me", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["username"] == "testlibrarian"


def test_logout_and_session_invalidation(client):
    # Register and login a one-off user
    username = "logout_test_user"
    client.post(
        "/api/v1/auth/register",
        json={"username": username, "email": "logout@test.com", "password": "Password123!"},
    )
    login_resp = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": "Password123!"},
    )
    token = login_resp.json()["session_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Verify session works
    me_resp = client.get("/api/v1/auth/me", headers=headers)
    assert me_resp.status_code == 200

    # Logout
    logout_resp = client.post("/api/v1/auth/logout", headers=headers)
    assert logout_resp.status_code == 200
    assert "invalidated" in logout_resp.json()["message"]

    # Using the same token now must fail with 401
    me_after_resp = client.get("/api/v1/auth/me", headers=headers)
    assert me_after_resp.status_code == 401


# ==========================================
# Author CRUD & Write Auth Tests
# ==========================================

def test_author_write_requires_auth(client):
    # Unauthenticated POST must fail
    resp = client.post(
        "/api/v1/authors",
        json={"name": "Unauthorized Author", "bio": "No Token"},
    )
    assert resp.status_code == 401


def test_author_crud_flow(client, auth_headers):
    # 1. Create Author (Authenticated)
    author_data = {
        "name": "J.R.R. Tolkien",
        "bio": "English writer, philologist, and academic.",
        "birth_date": "1892-01-03",
    }
    create_resp = client.post("/api/v1/authors", json=author_data, headers=auth_headers)
    assert create_resp.status_code == 201
    author = create_resp.json()
    author_id = author["id"]
    assert author["name"] == "J.R.R. Tolkien"

    # 2. Get Author (Public)
    get_resp = client.get(f"/api/v1/authors/{author_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == author_id

    # 3. List Authors (Public)
    list_resp = client.get("/api/v1/authors")
    assert list_resp.status_code == 200
    assert any(a["id"] == author_id for a in list_resp.json())

    # 4. Update Author (Authenticated)
    update_resp = client.put(
        f"/api/v1/authors/{author_id}",
        json={"bio": "Updated biography."},
        headers=auth_headers,
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["bio"] == "Updated biography."

    # 5. Delete Author (Authenticated)
    del_resp = client.delete(f"/api/v1/authors/{author_id}", headers=auth_headers)
    assert del_resp.status_code == 200

    # 6. Verify Deletion
    get_del_resp = client.get(f"/api/v1/authors/{author_id}")
    assert get_del_resp.status_code == 404


# ==========================================
# Book CRUD, Foreign Key & Cascade Tests
# ==========================================

def test_book_crud_and_foreign_key(client, auth_headers):
    # Create an author first
    author_resp = client.post(
        "/api/v1/authors",
        json={"name": "Frank Herbert", "bio": "American science fiction author."},
        headers=auth_headers,
    )
    assert author_resp.status_code == 201
    author_id = author_resp.json()["id"]

    # Attempt to create book with non-existent author_id -> 404
    bad_book_resp = client.post(
        "/api/v1/books",
        json={
            "title": "Invalid Author Book",
            "price": 19.99,
            "author_id": 99999,
        },
        headers=auth_headers,
    )
    assert bad_book_resp.status_code == 404
    assert "does not exist" in bad_book_resp.json()["detail"]

    # Create book with valid author_id
    book_data = {
        "title": "Dune",
        "description": "Epic science fiction masterpiece.",
        "isbn": "978-0441172719",
        "published_year": 1965,
        "price": 14.99,
        "author_id": author_id,
    }
    create_book_resp = client.post("/api/v1/books", json=book_data, headers=auth_headers)
    assert create_book_resp.status_code == 201
    book = create_book_resp.json()
    book_id = book["id"]
    assert book["title"] == "Dune"
    assert book["author_id"] == author_id

    # Duplicate ISBN should fail
    dup_isbn_resp = client.post(
        "/api/v1/books",
        json={
            "title": "Dune Duplicate",
            "isbn": "978-0441172719",
            "price": 9.99,
            "author_id": author_id,
        },
        headers=auth_headers,
    )
    assert dup_isbn_resp.status_code == 400
    assert "already exists" in dup_isbn_resp.json()["detail"]

    # Public Read: Get single book
    get_book_resp = client.get(f"/api/v1/books/{book_id}")
    assert get_book_resp.status_code == 200
    assert get_book_resp.json()["title"] == "Dune"
    assert get_book_resp.json()["author"]["name"] == "Frank Herbert"

    # Public Read: List books with author filter
    list_book_resp = client.get(f"/api/v1/books?author_id={author_id}")
    assert list_book_resp.status_code == 200
    assert len(list_book_resp.json()) == 1
    assert list_book_resp.json()[0]["id"] == book_id

    # Update book (Authenticated)
    update_book_resp = client.put(
        f"/api/v1/books/{book_id}",
        json={"price": 16.99},
        headers=auth_headers,
    )
    assert update_book_resp.status_code == 200
    assert update_book_resp.json()["price"] == 16.99

    # Update book without auth -> 401
    unauth_update = client.put(f"/api/v1/books/{book_id}", json={"price": 20.00})
    assert unauth_update.status_code == 401

    # Delete book (Authenticated)
    del_book_resp = client.delete(f"/api/v1/books/{book_id}", headers=auth_headers)
    assert del_book_resp.status_code == 200
    assert client.get(f"/api/v1/books/{book_id}").status_code == 404


def test_cascade_delete_author_deletes_books(client, auth_headers):
    # 1. Create an author
    author_resp = client.post(
        "/api/v1/authors",
        json={"name": "Isaac Asimov", "bio": "American writer and professor."},
        headers=auth_headers,
    )
    author_id = author_resp.json()["id"]

    # 2. Create two books for this author
    book1_resp = client.post(
        "/api/v1/books",
        json={"title": "Foundation", "price": 12.50, "author_id": author_id},
        headers=auth_headers,
    )
    book2_resp = client.post(
        "/api/v1/books",
        json={"title": "Foundation and Empire", "price": 13.50, "author_id": author_id},
        headers=auth_headers,
    )
    book1_id = book1_resp.json()["id"]
    book2_id = book2_resp.json()["id"]

    # Verify both books exist
    assert client.get(f"/api/v1/books/{book1_id}").status_code == 200
    assert client.get(f"/api/v1/books/{book2_id}").status_code == 200

    # 3. Delete the author
    del_author_resp = client.delete(f"/api/v1/authors/{author_id}", headers=auth_headers)
    assert del_author_resp.status_code == 200

    # 4. Verify cascade: both books must be gone
    assert client.get(f"/api/v1/books/{book1_id}").status_code == 404
    assert client.get(f"/api/v1/books/{book2_id}").status_code == 404
