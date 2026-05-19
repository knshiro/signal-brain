from signal_brain.wiki.build import plan_pages


ME = {"sender_label": "Me", "slug": "thomas-martin", "name": "Thomas Martin"}


def test_plan_pages_creates_one_position_per_person_concept_pair():
    bursts = [
        {"id": f"B{i:04d}", "msg_ids": ["a", "b"], "start": "2026-05-05T13:00",
         "senders": {"Me": 5, "Friend": 5}}
        for i in range(1, 7)
    ]
    chunks = [{"burst_id": f"B{i:04d}", "primary": "topic-a",
               "topics": ["topic-a"], "summary": "..."} for i in range(1, 7)]
    plan = plan_pages(bursts, chunks, arcs=[], min_concept_bursts=5, me=ME)
    assert "people/thomas-martin" in plan["pages"]
    assert "people/friend" in plan["pages"]
    assert "concepts/topic-a" in plan["pages"]
    assert "positions/thomas-martin--topic-a" in plan["pages"]
    assert "positions/friend--topic-a" in plan["pages"]


def test_plan_pages_skips_concept_below_threshold():
    chunks = [{"burst_id": "B0001", "primary": "rare-topic", "topics": ["rare-topic"], "summary": "..."}]
    bursts = [{"id": "B0001", "msg_ids": ["a"], "start": "2026-05-05T13:00", "senders": {"Me": 1}}]
    plan = plan_pages(bursts, chunks, arcs=[], min_concept_bursts=5, me=ME)
    assert "concepts/rare-topic" not in plan["pages"]


def test_plan_pages_uses_configured_me_identity():
    """The 'Me' sender's slug/name come from the me dict, not hardcoded."""
    bursts = [
        {"id": f"B{i:04d}", "msg_ids": ["a"], "start": "2026-05-05T13:00",
         "senders": {"Me": 1, "Other": 1}}
        for i in range(1, 7)
    ]
    chunks = [{"burst_id": f"B{i:04d}", "primary": "topic-x",
               "topics": ["topic-x"], "summary": "..."} for i in range(1, 7)]
    me = {"sender_label": "Me", "slug": "alice", "name": "Alice"}
    plan = plan_pages(bursts, chunks, arcs=[], min_concept_bursts=5, me=me)
    assert "people/alice" in plan["pages"]
    assert "people/other" in plan["pages"]  # counterpart slugified from label
    assert plan["pages"]["people/alice"]["name"] == "Alice"
    assert plan["pages"]["people/alice"]["relation"] == "Me"
    assert plan["pages"]["people/other"]["name"] == "Other"
    assert plan["pages"]["people/other"]["relation"] == "Friend"
