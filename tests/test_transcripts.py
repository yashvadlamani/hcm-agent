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
