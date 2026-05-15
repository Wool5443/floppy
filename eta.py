def estimate_remaining_seconds(
    elapsed_seconds: float,
    completed_files: int,
    current_file_fraction: float,
    total_files: int,
) -> float | None:
    if elapsed_seconds <= 0 or total_files <= 0:
        return None

    batch_fraction = (completed_files + current_file_fraction) / total_files

    if batch_fraction <= 0:
        return None

    total_estimated_seconds = elapsed_seconds / batch_fraction
    return max(0.0, total_estimated_seconds - elapsed_seconds)


def format_remaining_time(seconds: float) -> str:
    rounded_seconds = max(0, round(seconds))
    hours, remainder = divmod(rounded_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    if hours > 0:
        return f"{hours}:{minutes:02}:{seconds:02}"

    return f"{minutes:02}:{seconds:02}"
