from app.database import get_db


def test_get_db_yields_session_and_closes() -> None:
    generator = get_db()
    session = next(generator)
    assert session is not None
    try:
        next(generator)
    except StopIteration:
        pass
