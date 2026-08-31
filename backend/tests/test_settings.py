import pytest
from pydantic import ValidationError

from meridian.settings import Settings


def test_allowed_origins_are_normalized() -> None:
    settings = Settings(cors_origins="https://one.example, https://two.example, ")

    assert settings.allowed_origins == ["https://one.example", "https://two.example"]


def test_api_port_is_validated() -> None:
    with pytest.raises(ValidationError):
        Settings(api_port=0)
