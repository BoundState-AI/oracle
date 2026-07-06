"""Two-way voice invariants (dude.api.app + dude.voice).

Fakes are injected through create_app() — no monkeypatching. The
load-bearing tests: the safety floor scans spoken input exactly like
typed input, a crisis utterance gets resources BEFORE the reply and the
crisis message AS the spoken reply, and a missing STT backend refuses
visibly instead of pretending.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from dude.api.app import create_app
from dude.data import Case
from dude.pipeline.passes import PassSet
from dude.store.jsonl import CaseStore
from dude.voice.stt import TranscriptSegment, VoiceUnavailable

CRISIS_UTTERANCE = "He said he's going to kill me if I leave."
BENIGN_UTTERANCE = "Jerry replied about MIRA and suggested open source."


class FakeSTT:
    """Returns a scripted transcript for whatever audio arrives."""

    def __init__(self, text: str) -> None:
        self.text = text

    def transcribe(self, audio: bytes) -> list[TranscriptSegment]:
        if not audio:
            raise VoiceUnavailable("Empty audio payload; nothing to transcribe.")
        return [TranscriptSegment(text=self.text)]


class FakeTTS:
    def __init__(self) -> None:
        self.spoken: list[str] = []

    def synthesize(self, text: str) -> bytes:
        self.spoken.append(text)
        return b"RIFF-fake-wav"


def _client(tmp_path, stt=None, tts=None) -> tuple[TestClient, CaseStore, str]:
    store = CaseStore(root=tmp_path / "dude_home")
    case = Case(title="voice case")
    store.create_case(case)
    # Explicit stub PassSet keeps tests hermetic even when the developer's
    # environment carries live provider keys.
    app = create_app(store=store, stt=stt, tts=tts, passes=PassSet())
    return TestClient(app), store, case.id


def _speak(websocket, payload: bytes = b"audio-bytes") -> None:
    websocket.send_bytes(payload)
    websocket.send_json({"type": "end"})


class TestVoiceRoundTrip:
    def test_benign_utterance_two_way(self, tmp_path) -> None:
        tts = FakeTTS()
        client, store, case_id = _client(tmp_path, FakeSTT(BENIGN_UTTERANCE), tts)
        with client.websocket_connect(f"/cases/{case_id}/voice") as ws:
            _speak(ws)
            transcript = ws.receive_json()
            reply = ws.receive_json()
            audio = ws.receive_bytes()
        assert transcript["type"] == "transcript"
        assert transcript["text"] == BENIGN_UTTERANCE
        assert reply["type"] == "reply"
        assert audio == b"RIFF-fake-wav"
        assert tts.spoken == [reply["text"]]
        # The transcript entered the normal capture path.
        bundle = store.load_case(case_id)
        assert [c.text for c in bundle.captures] == [BENIGN_UTTERANCE]
        assert bundle.captures[0].source_type.value == "voice"

    def test_crisis_utterance_gets_resources_before_reply(self, tmp_path) -> None:
        """v0.2 I1 on the voice path: safety fires on spoken input, the
        safety frame precedes the reply, and the spoken reply IS the
        crisis message."""
        tts = FakeTTS()
        client, store, case_id = _client(tmp_path, FakeSTT(CRISIS_UTTERANCE), tts)
        with client.websocket_connect(f"/cases/{case_id}/voice") as ws:
            _speak(ws)
            frames = [ws.receive_json() for _ in range(3)]
            ws.receive_bytes()
        kinds = [f["type"] for f in frames]
        assert kinds == ["transcript", "safety", "reply"]
        safety_frame = frames[1]
        assert safety_frame["crisis"]
        assert any("988" in r["contact"] for r in safety_frame["resources"])
        assert frames[2]["text"] == safety_frame["message"]
        assert tts.spoken == [safety_frame["message"]]
        # SafetyEvent persisted through the shared capture path.
        assert store.load_case(case_id).safety_events

    def test_missing_stt_refuses_visibly(self, tmp_path) -> None:
        client, _store, case_id = _client(tmp_path, stt=None)
        with client.websocket_connect(f"/cases/{case_id}/voice") as ws:
            refusal = ws.receive_json()
        assert refusal["type"] == "refusal"
        assert "speech-to-text" in refusal["reason"]

    def test_missing_tts_stays_two_way_in_text(self, tmp_path) -> None:
        client, _store, case_id = _client(tmp_path, FakeSTT(BENIGN_UTTERANCE), None)
        with client.websocket_connect(f"/cases/{case_id}/voice") as ws:
            _speak(ws)
            transcript = ws.receive_json()
            reply = ws.receive_json()
            ws.send_json({"type": "bye"})
        assert transcript["type"] == "transcript"
        assert reply["type"] == "reply"


class TestRestSurface:
    def test_capture_and_analyze_round_trip(self, tmp_path) -> None:
        client, _store, case_id = _client(tmp_path)
        captured = client.post(
            f"/cases/{case_id}/capture", json={"text": BENIGN_UTTERANCE}
        ).json()
        assert not captured["crisis"]
        analyzed = client.post(f"/cases/{case_id}/analyze").json()
        assert analyzed["mode"] == "new_evidence"
        again = client.post(f"/cases/{case_id}/analyze").json()
        assert again["served_prior"]

    def test_rest_capture_surfaces_crisis(self, tmp_path) -> None:
        client, _store, case_id = _client(tmp_path)
        captured = client.post(
            f"/cases/{case_id}/capture", json={"text": CRISIS_UTTERANCE}
        ).json()
        assert captured["crisis"]
        assert any("988" in r["contact"] for r in captured["resources"])

    def test_unknown_case_is_conflict_not_silence(self, tmp_path) -> None:
        client, _store, _case_id = _client(tmp_path)
        response = client.post("/cases/nope/capture", json={"text": "hi"})
        assert response.status_code == 409


class TestMountedRouterAuth:
    """The server.py mount path: X-API-Key guards REST routes and the
    websocket authenticates before accept."""

    def _authed_client(self, tmp_path) -> tuple[TestClient, str]:
        from fastapi import FastAPI

        from dude.api.app import create_router

        store = CaseStore(root=tmp_path / "dude_home")
        case = Case(title="authed")
        store.create_case(case)
        app = FastAPI()
        app.include_router(
            create_router(
                store=store,
                stt=FakeSTT(BENIGN_UTTERANCE),
                passes=PassSet(),
                prefix="/dude",
                api_key="secret",
            )
        )
        return TestClient(app), case.id

    def test_rest_requires_key(self, tmp_path) -> None:
        client, case_id = self._authed_client(tmp_path)
        denied = client.post(f"/dude/cases/{case_id}/capture", json={"text": "hi"})
        assert denied.status_code == 401
        allowed = client.post(
            f"/dude/cases/{case_id}/capture",
            json={"text": "hi"},
            headers={"X-API-Key": "secret"},
        )
        assert allowed.status_code == 200

    def test_websocket_requires_key(self, tmp_path) -> None:
        client, case_id = self._authed_client(tmp_path)
        with client.websocket_connect(
            f"/dude/cases/{case_id}/voice", headers={"X-API-Key": "secret"}
        ) as ws:
            _speak(ws)
            assert ws.receive_json()["type"] == "transcript"
