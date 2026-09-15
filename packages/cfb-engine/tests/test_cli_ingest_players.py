"""`cfb ingest-players` (issue #289): dispatch to a league's player-stats ingest.

Only the NFL has one today. The CLI keeps a per-league table, like
`INGEST_ENTRY_POINTS`, so adding CFB player stats later is one entry rather
than a new command.
"""

from __future__ import annotations

from typing import get_args

import pytest

from cfb_strength import cli
from cfb_strength.contracts import Sport


def _recording_main(calls: list[list[str]]) -> cli.IngestMain:
    def main(argv: list[str]) -> int:
        calls.append(argv)
        return 0

    return main


def test_nfl_dispatches_to_the_nflverse_player_ingest_without_the_sport_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setitem(cli.PLAYER_INGEST_ENTRY_POINTS, "nfl", lambda: _recording_main(calls))

    code = cli.main(["ingest-players", "--sport", "nfl", "--years", "2004", "--force"])

    assert code == 0
    assert calls == [["--years", "2004", "--force"]]


def test_a_league_without_a_player_ingest_is_rejected(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["ingest-players", "--sport", "cfb", "--years", "2004"]) == 2
    assert "no player-stats ingest for 'cfb'" in capsys.readouterr().err


def test_sport_is_required(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["ingest-players", "--years", "2004"]) == 2
    assert "ingest-players requires --sport" in capsys.readouterr().err


def test_every_player_ingest_league_is_a_known_sport() -> None:
    assert set(cli.PLAYER_INGEST_ENTRY_POINTS) <= set(get_args(Sport))


def test_the_nfl_loader_resolves_the_real_entry_point() -> None:
    from cfb_strength.ingest.nflverse.ingest_players import main

    assert cli.PLAYER_INGEST_ENTRY_POINTS["nfl"]() is main


def test_usage_documents_the_command() -> None:
    assert "ingest-players" in cli.USAGE
