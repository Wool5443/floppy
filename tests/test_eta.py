import eta


def test_estimate_remaining_seconds_returns_none_before_progress() -> None:
    assert eta.estimate_remaining_seconds(
        elapsed_seconds=10,
        completed_files=0,
        current_file_fraction=0,
        total_files=4,
    ) is None


def test_estimate_remaining_seconds_uses_batch_fraction() -> None:
    assert eta.estimate_remaining_seconds(
        elapsed_seconds=30,
        completed_files=1,
        current_file_fraction=0.5,
        total_files=3,
    ) == 30


def test_estimate_remaining_seconds_never_returns_negative() -> None:
    assert eta.estimate_remaining_seconds(
        elapsed_seconds=30,
        completed_files=1,
        current_file_fraction=1,
        total_files=1,
    ) == 0


def test_format_remaining_time_uses_minutes_and_seconds() -> None:
    assert eta.format_remaining_time(125) == "02:05"


def test_format_remaining_time_uses_hours_when_needed() -> None:
    assert eta.format_remaining_time(3661) == "1:01:01"
