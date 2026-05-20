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
    plan = plan_pages(bursts, chunks, arcs=[], me=ME, concepts=["topic-a"])
    assert "people/thomas-martin" in plan["pages"]
    assert "people/friend" in plan["pages"]
    assert "concepts/topic-a" in plan["pages"]
    assert "positions/thomas-martin--topic-a" in plan["pages"]
    assert "positions/friend--topic-a" in plan["pages"]


def test_plan_pages_skips_concept_absent_from_concepts_list():
    """A topic that has a backing burst but is not in `concepts` gets no page."""
    chunks = [{"burst_id": "B0001", "primary": "rare-topic",
               "topics": ["rare-topic"], "summary": "..."}]
    bursts = [{"id": "B0001", "msg_ids": ["a"], "start": "2026-05-05T13:00",
               "senders": {"Me": 1}}]
    plan = plan_pages(bursts, chunks, arcs=[], me=ME, concepts=[])
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
    plan = plan_pages(bursts, chunks, arcs=[], me=me, concepts=["topic-x"])
    assert "people/alice" in plan["pages"]
    assert "people/other" in plan["pages"]  # counterpart slugified from label
    assert plan["pages"]["people/alice"]["name"] == "Alice"
    assert plan["pages"]["people/alice"]["relation"] == "Me"
    assert plan["pages"]["people/other"]["name"] == "Other"
    assert plan["pages"]["people/other"]["relation"] == "Friend"


def test_plan_pages_concept_page_for_each_concept_with_a_burst():
    """Every slug in `concepts` backed by >=1 burst gets a concept page."""
    bursts = [{"id": "B0001", "msg_ids": ["a"], "start": "2026-05-05T13:00",
               "senders": {"Me": 1}}]
    chunks = [{"burst_id": "B0001", "primary": "topic-a",
               "topics": ["topic-a"], "summary": "..."}]
    plan = plan_pages(bursts, chunks, arcs=[], me=ME, concepts=["topic-a"])
    assert "concepts/topic-a" in plan["pages"]
    assert plan["pages"]["concepts/topic-a"]["bursts"] == ["B0001"]


def test_plan_pages_no_concept_page_for_slug_absent_from_concepts():
    """A topic on many bursts but not in `concepts` produces no concept page."""
    bursts = [
        {"id": f"B{i:04d}", "msg_ids": ["a"], "start": "2026-05-05T13:00",
         "senders": {"Me": 1}}
        for i in range(1, 11)
    ]
    chunks = [{"burst_id": f"B{i:04d}", "primary": "popular-topic",
               "topics": ["popular-topic"], "summary": "..."} for i in range(1, 11)]
    plan = plan_pages(bursts, chunks, arcs=[], me=ME, concepts=["something-else"])
    assert "concepts/popular-topic" not in plan["pages"]
    # ...and the concept that *is* listed but has no burst still gets nothing.
    assert "concepts/something-else" not in plan["pages"]


def test_plan_pages_counts_non_primary_topics():
    """A burst whose `primary` is A but whose `topics` also lists B backs B's page."""
    bursts = [{"id": "B0001", "msg_ids": ["a"], "start": "2026-05-05T13:00",
               "senders": {"Me": 1}}]
    chunks = [{"burst_id": "B0001", "primary": "topic-a",
               "topics": ["topic-a", "topic-b"], "summary": "..."}]
    plan = plan_pages(bursts, chunks, arcs=[], me=ME, concepts=["topic-b"])
    assert "concepts/topic-b" in plan["pages"]
    assert plan["pages"]["concepts/topic-b"]["bursts"] == ["B0001"]


def test_plan_pages_position_page_per_holder_and_concept():
    """A (holder, concept) pair with >=1 backing burst gets a position page."""
    bursts = [{"id": "B0001", "msg_ids": ["a"], "start": "2026-05-05T13:00",
               "senders": {"Me": 3, "Friend": 2}}]
    chunks = [{"burst_id": "B0001", "primary": "topic-a",
               "topics": ["topic-a"], "summary": "..."}]
    plan = plan_pages(bursts, chunks, arcs=[], me=ME, concepts=["topic-a"])
    assert "positions/thomas-martin--topic-a" in plan["pages"]
    assert "positions/friend--topic-a" in plan["pages"]
    assert plan["pages"]["positions/thomas-martin--topic-a"]["concept"] == "topic-a"
    assert plan["pages"]["positions/thomas-martin--topic-a"]["bursts"] == ["B0001"]
