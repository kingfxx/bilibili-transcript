"""Keep tests independent of the user's ignored local uploader settings."""

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def sample_uploader_mapping(monkeypatch):
    from bilibili_transcript import uploader_mapping

    monkeypatch.setattr(uploader_mapping, 'DEFAULT_MAPPING',
                        Path(__file__).resolve().parents[1] / 'uploader_mapping.sample.json')
