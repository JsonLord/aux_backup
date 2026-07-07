import os

def test_filtering_logic():
    # Simulate a list of discovered paths
    reports = [
        "user_experience_reports/slides",
        "user_experience_reports/slides/01_intro.md",
        "user_experience_reports/slides/02_body.md",
        "user_experience_reports/other_slides.md"
    ]

    filter_type = "slides"

    # Logic from app.py
    if filter_type == "slides":
        folders = [r for r in reports if not r.endswith(".md")]
        if folders:
            reports = [r for r in reports if not any(r.startswith(f + "/") for f in folders)]

    print(f"Filtered reports: {reports}")
    assert "user_experience_reports/slides" in reports
    assert "user_experience_reports/other_slides.md" in reports
    assert "user_experience_reports/slides/01_intro.md" not in reports
    assert "user_experience_reports/slides/02_body.md" not in reports
    print("Filtering logic test PASSED")

if __name__ == "__main__":
    test_filtering_logic()
