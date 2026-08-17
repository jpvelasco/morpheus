"""Unit tests: documented voice (STT/TTS) contract for Open WebUI (VOICE-003)."""

from __future__ import annotations

import pytest

from morpheus.core.voice_contract import (
    DEFAULT_VOICES,
    VoiceContractError,
    VoiceEndpointContract,
    documented_stt_url,
    documented_tts_url,
    documented_voices,
    validate_audio_content_type,
    verify_speech_response,
    verify_stt_payload,
)

DEFAULT = VoiceEndpointContract(base_url="http://voice.test")


def test_documented_stt_url_uses_openai_transcriptions_path() -> None:
    assert documented_stt_url(DEFAULT) == "http://voice.test/v1/audio/transcriptions"


def test_documented_tts_url_uses_openai_speech_path() -> None:
    assert documented_tts_url(DEFAULT) == "http://voice.test/v1/audio/speech"


def test_contract_rejects_unsafe_base_url() -> None:
    with pytest.raises(ValueError, match="http or https"):
        VoiceEndpointContract(base_url="file:///etc/passwd")
    with pytest.raises(ValueError, match="embedded credentials"):
        VoiceEndpointContract(base_url="https://user:pass@voice.test")
    with pytest.raises(ValueError, match="path, query, or fragment"):
        VoiceEndpointContract(base_url="http://voice.test/v1")


def test_documented_voices_are_stable_and_usable() -> None:
    assert len(DEFAULT_VOICES) >= 4
    assert all(isinstance(voice, str) and voice for voice in DEFAULT_VOICES)
    assert "af_heart" in documented_voices(DEFAULT)
    assert documented_voices(DEFAULT) == DEFAULT_VOICES


def test_validate_audio_content_type_accepts_openai_audio_types() -> None:
    for content_type in ("audio/wav", "audio/mpeg", "audio/webm", "audio/ogg", "audio/mp4"):
        validate_audio_content_type(DEFAULT, content_type)


def test_validate_audio_content_type_rejects_others() -> None:
    with pytest.raises(ValueError, match="unsupported audio content type"):
        validate_audio_content_type(DEFAULT, "application/json")


def test_verify_stt_payload_accepts_text() -> None:
    assert verify_stt_payload({"text": "fixture transcription"}) == "fixture transcription"


def test_verify_stt_payload_rejects_incompatible_payloads() -> None:
    with pytest.raises(VoiceContractError, match="transcription response"):
        verify_stt_payload([])
    with pytest.raises(VoiceContractError, match="does not contain text"):
        verify_stt_payload({"text": 42})
    with pytest.raises(VoiceContractError, match="does not contain text"):
        verify_stt_payload({})


def test_verify_speech_response_accepts_audio() -> None:
    assert verify_speech_response(content_type="audio/mpeg", content=b"ID3audio") == "audio/mpeg"
    assert (
        verify_speech_response(content_type="AUDIO/MPEG; charset=utf-8", content=b"ID3audio")
        == "audio/mpeg"
    )


def test_verify_speech_response_rejects_non_audio_or_empty() -> None:
    with pytest.raises(VoiceContractError, match="non-empty audio"):
        verify_speech_response(content_type="application/json", content=b"{}")
    with pytest.raises(VoiceContractError, match="non-empty audio"):
        verify_speech_response(content_type="audio/mpeg", content=b"")
