import pytest

from app.ai.audience import GENERAL, MINE, OTHER_CLASS, detect_audience
from app.ai.priority import score_task


@pytest.mark.parametrize("subject, body, mine, expected", [
    ("Class B: lab submission due Friday", "Please submit", ["A"], OTHER_CLASS),
    ("Lab submission", "Dear Class A students, please submit", ["Class A"], MINE),
    ("[SY-B] Practical schedule", "", ["SY-A"], OTHER_CLASS),
    ("[SY-A] Practical schedule", "", ["A"], MINE),
    ("[TY-A] Practical schedule", "", ["SY-A"], OTHER_CLASS),
    ("Div. C timetable", "", ["div a"], OTHER_CLASS),
    ("Batch B2 viva", "", ["B1"], OTHER_CLASS),
    ("Class A and Class B", "", ["B"], MINE),
    ("CS201 quiz on Monday", "", ["CS201"], MINE),
    ("Assignment 3", "Read section 3 of the handout", ["A"], GENERAL),
    ("WILL BE A HOLIDAY", "", ["A"], GENERAL),
    ("Library closed", "FYI the library is closed. SEE YOU IN FEB", ["A"], GENERAL),
    ("[SY-B] Viva", "", ["sy b"], MINE),
    ("Holiday notice", "College is closed tomorrow", ["A"], GENERAL),
    ("Class B: lab", "", [], GENERAL),  # no classes set: nothing is filtered
])
def test_detect_audience(subject, body, mine, expected):
    assert detect_audience(subject, body, mine).kind == expected


def _score(**overrides):
    args = dict(
        text_for_urgency="URGENT submit asap", sender_email="hod@college.edu", project=None,
        is_blocking=True, has_dependents=False, thread_message_count=1,
        classification="ACTION_REQUIRED", effort_minutes=60, deadline=None,
    )
    args.update(overrides)
    return score_task(**args)


def test_other_class_mail_is_capped_at_info_even_when_urgent():
    score, level, reasons = _score(audience=OTHER_CLASS, audience_reason="For Class B, not your class")
    assert level == "P4"
    assert reasons == ["For Class B, not your class"]


def test_my_class_mail_is_boosted_and_explained():
    base, _, _ = _score()
    boosted, _, reasons = _score(audience=MINE, audience_reason="Addressed to your class (Class A)")
    assert boosted > base
    assert reasons[0] == "Addressed to your class (Class A)"
