"""Issue #211: `ingest.nflverse.client`'s live-fetch path for the whole-history
games/teams CSVs, with the transport stubbed (no test here touches the
network).

Each test points `raw_dir` at a temp dir, so the committed cache under
`data/raw/nfl/` is never read or written. The body a stub serves is a real
nflverse sample (`tests/fixtures/raw_nfl_games_sample.csv`), not an invented
CSV.
"""

from __future__ import annotations

from pathlib import Path
from typing import NoReturn

import pytest
import requests

from cfb_strength.ingest.nflverse import client
from cfb_strength.ingest.nflverse.client import NflverseClientError, get_games, get_teams

GAMES_SAMPLE = Path(__file__).parent / "fixtures" / "raw_nfl_games_sample.csv"


class _Response:
    def __init__(self, status_code: int, text: str) -> None:
        self.status_code = status_code
        self.text = text


def _serve(monkeypatch: pytest.MonkeyPatch, response: _Response) -> list[str]:
    calls: list[str] = []

    def _get(url: str, timeout: float) -> _Response:
        calls.append(url)
        return response

    monkeypatch.setattr(requests, "get", _get)
    return calls


def _refuse(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []

    def _get(url: str, timeout: float) -> NoReturn:
        calls.append(url)
        raise requests.ConnectionError("network disabled in tests (#211)")

    monkeypatch.setattr(requests, "get", _get)
    return calls


def test_an_unreachable_host_raises_the_client_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls = _refuse(monkeypatch)

    with pytest.raises(NflverseClientError, match="could not reach nflverse asset") as exc:
        get_games(raw_dir=tmp_path)

    assert calls == [client.GAMES_URL]
    assert isinstance(exc.value.__cause__, requests.ConnectionError)
    assert not client.games_cache_path(tmp_path).exists()


def test_a_non_200_response_raises_with_the_status_and_no_cache_is_written(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _serve(monkeypatch, _Response(503, "Service Unavailable" + "x" * 1000))

    with pytest.raises(NflverseClientError, match="returned HTTP 503") as exc:
        get_teams(raw_dir=tmp_path)

    # The body is quoted, but cut at 500 characters.
    assert str(exc.value).endswith("Service Unavailable" + "x" * 481)
    assert not client.teams_cache_path(tmp_path).exists()


def test_a_live_fetch_writes_the_cache_and_the_next_call_reads_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    body = GAMES_SAMPLE.read_text()
    calls = _serve(monkeypatch, _Response(200, body))

    rows, fetched_live = get_games(raw_dir=tmp_path)

    assert fetched_live is True
    assert calls == [client.GAMES_URL]
    assert [r["game_id"] for r in rows][:2] == ["2023_04_ATL_JAX", "2023_19_CLE_HOU"]
    assert len(rows) == 7
    assert client.games_cache_path(tmp_path).read_text() == body

    # Cache-first: with the network down, the second call is served from disk.
    refused = _refuse(monkeypatch)
    cached_rows, fetched_live_again = get_games(raw_dir=tmp_path)
    assert fetched_live_again is False
    assert refused == []
    assert cached_rows == rows


def test_force_refetches_over_an_existing_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cache = client.games_cache_path(tmp_path)
    cache.parent.mkdir(parents=True)
    cache.write_text("game_id,season\nstale,1999\n")
    body = GAMES_SAMPLE.read_text()
    calls = _serve(monkeypatch, _Response(200, body))

    rows, fetched_live = get_games(force=True, raw_dir=tmp_path)

    assert fetched_live is True
    assert calls == [client.GAMES_URL]
    assert len(rows) == 7
    assert cache.read_text() == body
