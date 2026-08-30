"""Production container startup safeguards."""

from pathlib import Path


def test_api_container_migrates_before_starting_uvicorn():
    dockerfile = (
        Path(__file__).resolve().parents[3] / "infrastructure" / "docker" / "api.Dockerfile"
    ).read_text()

    startup = "python -m alembic upgrade head && exec uvicorn"
    assert startup in dockerfile