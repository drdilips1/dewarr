from app.domain.automatic_eligibility import track_sequence

TITLE = "The Magic of Reality"


def test_common_audiobook_file_names_form_a_track_sequence():
    assert track_sequence(["01", "02", "03"], TITLE)
    assert track_sequence(["Track 01", "Track 02"], TITLE)
    assert track_sequence(["The Magic of Reality 01", "The Magic of Reality 02"], TITLE)
    assert track_sequence(
        ["01 - What Is Reality? What Is Magic?", "02 - Who Was the First Person?"], TITLE
    )
    assert track_sequence(["Chapter 01 - Intro", "Chapter 02 - Stars"], TITLE)
    assert track_sequence(["Richard Dawkins - Reality 01", "Richard Dawkins - Reality 02"], TITLE)
    assert track_sequence(["Disc 1 Track 01", "Disc 1 Track 02", "Disc 2 Track 01"], TITLE)
    assert track_sequence(["00 Credits", "01 One", "02 Two"], TITLE)


def test_gaps_duplicates_and_unnumbered_files_still_need_review():
    assert not track_sequence(["01", "03"], TITLE)
    assert not track_sequence(["01 - Intro", "01 - Intro (copy)"], TITLE)
    assert not track_sequence(["01", "Bonus interview"], TITLE)
    assert not track_sequence(["05", "06", "07"], TITLE)
    assert not track_sequence(["Intro", "Ending"], TITLE)
