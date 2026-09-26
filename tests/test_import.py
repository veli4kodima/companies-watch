from companies_watch.commands import parse_numbers


def test_parse_numbers_dedupes_normalizes_and_skips_garbage() -> None:
    lines = [
        "6\n",
        "00000006\n",
        "# comment\n",
        "\n",
        "sc123456  # scottish\n",
        "../../etc\n",
    ]
    good, bad = parse_numbers(lines)
    assert good == ["00000006", "SC123456"]
    assert bad == ["../../etc"]
