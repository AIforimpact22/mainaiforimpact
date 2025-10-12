import importlib
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from werkzeug.security import check_password_hash, generate_password_hash


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    db_url = f"sqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", db_url)

    for mod in ["registration", "main"]:
        if mod in sys.modules:
            del sys.modules[mod]

    project_root = Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    engine = create_engine(db_url)
    with engine.begin() as conn:
        conn.exec_driver_sql(
            """
            CREATE TABLE users (
                email TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL,
                must_change_password BOOLEAN NOT NULL DEFAULT 1,
                created_at TIMESTAMP,
                updated_at TIMESTAMP
            );
            """
        )
        conn.exec_driver_sql(
            """
            CREATE TABLE registrations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_email TEXT,
                first_name TEXT,
                middle_name TEXT,
                last_name TEXT,
                age INTEGER,
                gender TEXT,
                gender_other_note TEXT,
                phone TEXT,
                address_line1 TEXT,
                address_line2 TEXT,
                city TEXT,
                state TEXT,
                postal_code TEXT,
                country TEXT,
                job_title TEXT,
                company TEXT,
                ai_current_involvement TEXT,
                ai_goals_wish_to_achieve TEXT,
                ai_datasets_available TEXT,
                referral_source TEXT,
                referral_details TEXT,
                reason_choose_us TEXT,
                invoice_name TEXT,
                invoice_company TEXT,
                invoice_vat_id TEXT,
                invoice_email TEXT,
                invoice_phone TEXT,
                invoice_addr_line1 TEXT,
                invoice_addr_line2 TEXT,
                invoice_city TEXT,
                invoice_state TEXT,
                invoice_postal_code TEXT,
                invoice_country TEXT,
                course_session_code TEXT,
                notes TEXT,
                consent_contact_ok BOOLEAN,
                consent_marketing_ok BOOLEAN,
                data_processing_ok BOOLEAN,
                created_at TIMESTAMP,
                updated_at TIMESTAMP
            );
            """
        )

    registration = importlib.import_module("registration")
    main = importlib.import_module("main")
    app = main.app
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    return app.test_client(), registration, engine


def _insert_user(engine, registration_module, email, password, must_change):
    now = datetime.now(timezone.utc)
    hashed = generate_password_hash(password)
    with engine.begin() as conn:
        conn.execute(
            registration_module.users.insert().values(
                email=email,
                password_hash=hashed,
                must_change_password=must_change,
                created_at=now,
                updated_at=now,
            )
        )
    return hashed


def test_signin_success(app_client):
    client, registration_module, engine = app_client
    _insert_user(engine, registration_module, "tester@gmail.com", "secret123", must_change=False)

    response = client.post(
        "/register/signin",
        data={"user_email": "tester@gmail.com", "password": "secret123"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/register/")
    with client.session_transaction() as sess:
        assert sess["user_email"] == "tester@gmail.com"
        assert sess["require_password_change"] is False

    page = client.get("/register/")
    assert page.status_code == 200
    assert b"Signed in as" in page.data


def test_signin_requires_password_change(app_client):
    client, registration_module, engine = app_client
    _insert_user(engine, registration_module, "resetme@gmail.com", "temp-pass", must_change=True)

    response = client.post(
        "/register/signin",
        data={"user_email": "resetme@gmail.com", "password": "temp-pass"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/register/password/change")
    with client.session_transaction() as sess:
        assert sess["require_password_change"] is True

    redirect = client.get("/register/", follow_redirects=False)
    assert redirect.status_code == 302
    assert redirect.headers["Location"].endswith("/register/password/change")


def test_signin_rejects_non_gmail(app_client):
    client, registration_module, engine = app_client
    _insert_user(engine, registration_module, "example@gmail.com", "abc12345", must_change=False)

    response = client.post(
        "/register/signin",
        data={"user_email": "user@example.com", "password": "abc12345"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/register/")
    with client.session_transaction() as sess:
        assert "user_email" not in sess


def test_registration_flow_after_password_reset(app_client):
    client, registration_module, engine = app_client
    _insert_user(engine, registration_module, "flow@gmail.com", "start-pass", must_change=True)

    resp = client.post(
        "/register/signin",
        data={"user_email": "flow@gmail.com", "password": "start-pass"},
        follow_redirects=False,
    )
    assert resp.headers["Location"].endswith("/register/password/change")

    change = client.post(
        "/register/password/change",
        data={
            "new_password": "freshpass1",
            "confirm_password": "freshpass1",
        },
        follow_redirects=False,
    )
    assert change.status_code == 302
    assert change.headers["Location"].endswith("/register/")

    with client.session_transaction() as sess:
        assert sess["require_password_change"] is False

    with engine.connect() as conn:
        row = conn.execute(
            select(registration_module.users).where(registration_module.users.c.email == "flow@gmail.com")
        ).mappings().first()
        assert row is not None
        assert not row["must_change_password"]
        assert check_password_hash(row["password_hash"], "freshpass1")

    form_response = client.post(
        "/register/submit",
        data={
            "course_session_code": "AAI-RTD",
            "first_name": "Flow",
            "last_name": "Tester",
            "user_email": "flow@gmail.com",
            "data_processing_ok": "on",
            "job_title": "Other",
        },
        follow_redirects=False,
    )

    assert form_response.status_code == 302
    assert "/register/?submitted=1" in form_response.headers["Location"]

    with engine.connect() as conn:
        registrations = conn.execute(
            select(registration_module.registrations).where(
                registration_module.registrations.c.user_email == "flow@gmail.com"
            )
        ).mappings().all()
        assert len(registrations) == 1

    page = client.get(form_response.headers["Location"], follow_redirects=True)
    assert b"Thank you!" in page.data
