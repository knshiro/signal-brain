from signal_brain.arcs import detect_arcs


def burst(id_, primary, msg_count):
    return {"id": id_, "msg_ids": ["x"] * msg_count, "start": f"2026-05-{int(id_[1:]):02d}T10:00", "end": "..."}


def chunk(id_, primary):
    return {"burst_id": id_, "primary": primary, "topics": [primary], "summary": "..."}


def test_single_burst_below_threshold_not_an_arc():
    bursts = [burst("B0001", "topic-a", 10)]
    chunks = [chunk("B0001", "topic-a")]
    assert detect_arcs(bursts, chunks, min_burst_count=2, min_msg_count=20) == []


def test_two_adjacent_bursts_same_topic_form_arc():
    bursts = [burst("B0001", "topic-a", 12), burst("B0002", "topic-a", 15)]
    chunks = [chunk("B0001", "topic-a"), chunk("B0002", "topic-a")]
    arcs = detect_arcs(bursts, chunks, min_burst_count=2, min_msg_count=20)
    assert len(arcs) == 1
    a = arcs[0]
    assert a["id"] == "A001"
    assert a["primary"] == "topic-a"
    assert a["bursts"] == ["B0001", "B0002"]
    assert a["msg_count"] == 27
    assert a["status"] == "unresolved"


def test_topic_change_starts_new_arc():
    bursts = [burst("B0001", "topic-a", 12), burst("B0002", "topic-a", 12),
              burst("B0003", "topic-b", 12), burst("B0004", "topic-b", 12)]
    chunks = [chunk("B0001", "topic-a"), chunk("B0002", "topic-a"),
              chunk("B0003", "topic-b"), chunk("B0004", "topic-b")]
    arcs = detect_arcs(bursts, chunks, min_burst_count=2, min_msg_count=20)
    assert len(arcs) == 2
    assert arcs[0]["primary"] == "topic-a"
    assert arcs[1]["primary"] == "topic-b"


def test_min_msg_count_filters_out_low_substance():
    bursts = [burst("B0001", "topic-a", 5), burst("B0002", "topic-a", 5)]
    chunks = [chunk("B0001", "topic-a"), chunk("B0002", "topic-a")]
    assert detect_arcs(bursts, chunks, min_burst_count=2, min_msg_count=20) == []
