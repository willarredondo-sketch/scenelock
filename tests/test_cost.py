from scenelock.cost import estimate_run, format_credits, video_credits


def test_listed_and_interpolated_video_credits():
    assert video_credits(5) == (27.0, "listed approximation for 5s")
    assert video_credits(8) == (44.0, "listed approximation for 8s")
    credits, note = video_credits(6)
    assert credits == 27 + (44 - 27) / 3
    assert "interpolated" in note
    assert format_credits(credits) == "32.7"


def test_run_estimate_uses_the_flat_image_rate():
    estimate = estimate_run(4, 4, 8)
    assert estimate.total == 4 * 36 + 4 * 36 + 44
    text = estimate.format()
    assert "Approximate" in text
    assert "not a quote" in text
    assert "Total ~332" in text
