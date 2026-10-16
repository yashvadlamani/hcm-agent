from hcm_agent.telephony.transcripts import TranscriptStore


def test_transcript_store_persists_and_retains_the_newest_completed_calls(tmp_path):
    store = TranscriptStore(tmp_path / "calls.sqlite3", max_records=1)
    store.save("call-1", [{"type": "call_started", "name": "One", "ts": 1},
                          {"type": "call_ended", "ts": 2}])
    store.save("call-2", [{"type": "call_started", "name": "Two", "ts": 3},
                          {"type": "emergency", "ts": 4}, {"type": "call_ended", "ts": 5}])

    records = TranscriptStore(tmp_path / "calls.sqlite3", max_records=1).recent()
    assert [(record["call"], record["name"], record["status"]) for record in records] == [
        ("call-2", "Two", "emergency"),
    ]


def test_transcript_store_deletes_only_explicitly_selected_calls(tmp_path):
    store = TranscriptStore(tmp_path / "calls.sqlite3")
    for call_id in ("call-1", "call-2"):
        store.save(call_id, [{"type": "call_started", "name": call_id, "ts": 1},
                             {"type": "call_ended", "ts": 2}])

    assert store.delete(["call-1", "missing", "call-1"]) == ["call-1"]
    assert [record["call"] for record in store.recent()] == ["call-2"]
