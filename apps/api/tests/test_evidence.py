from io import BytesIO


def test_mock_asr_creates_an_explicit_demo_transcript(client) -> None:
    person = client.post("/v1/persons", json={"display_name": "陈先生"}).json()
    asset = client.post(
        "/v1/evidence/assets",
        data={"subject_id": person["id"], "kind": "audio", "consent_scope": "private"},
        files={"file": ("demo.webm", BytesIO(b"OggSmock-asr-audio"), "audio/webm")},
    ).json()

    response = client.post(f"/v1/evidence/assets/{asset['id']}/transcribe")

    assert response.status_code == 200
    version = response.json()["versions"][0]
    assert version["source"] == "mock_asr"
    assert "模拟转写" in version["text"]


def test_openai_compatible_asr_creates_source_backed_transcript(client, monkeypatch) -> None:
    from lifereel_api.core.config import get_settings
    from lifereel_api.providers.openai_compatible import OpenAICompatibleClient

    person = client.post("/v1/persons", json={"display_name": "许奶奶"}).json()
    asset = client.post(
        "/v1/evidence/assets",
        data={"subject_id": person["id"], "kind": "audio", "consent_scope": "private"},
        files={"file": ("interview.webm", BytesIO(b"OggSsynthetic-asr-audio"), "audio/webm")},
    ).json()
    monkeypatch.setenv("ASR_PROVIDER", "openai-compatible")
    monkeypatch.setenv("OPENAI_COMPATIBLE_BASE_URL", "https://asr.example/v1")
    monkeypatch.setenv("OPENAI_COMPATIBLE_API_KEY", "asr-secret")
    monkeypatch.setenv("OPENAI_COMPATIBLE_MODEL", "asr-model")
    get_settings.cache_clear()
    monkeypatch.setattr(
        OpenAICompatibleClient,
        "transcribe",
        lambda self, filename, content, mime_type: "这是经过自动转写的采访原话。",
    )
    try:
        response = client.post(f"/v1/evidence/assets/{asset['id']}/transcribe")
        assert response.status_code == 200
        transcript = response.json()
        assert transcript["versions"][0]["source"] == "provider_asr"
        assert transcript["versions"][0]["text"] == "这是经过自动转写的采访原话。"
    finally:
        for key in (
            "ASR_PROVIDER",
            "OPENAI_COMPATIBLE_BASE_URL",
            "OPENAI_COMPATIBLE_API_KEY",
            "OPENAI_COMPATIBLE_MODEL",
        ):
            monkeypatch.delenv(key, raising=False)
        get_settings.cache_clear()


def test_faster_whisper_asr_creates_source_backed_observation(client, monkeypatch) -> None:
    from lifereel_api.core.config import get_settings
    from lifereel_api.providers.whisper import FasterWhisperClient

    person = client.post("/v1/persons", json={"display_name": "本地转写"}).json()
    asset = client.post(
        "/v1/evidence/assets",
        data={"subject_id": person["id"], "kind": "audio", "consent_scope": "private"},
        files={"file": ("interview.webm", BytesIO(b"OggSsynthetic-audio"), "audio/webm")},
    ).json()
    monkeypatch.setenv("ASR_PROVIDER", "faster-whisper")
    monkeypatch.setenv("ASR_MODEL", "small")
    get_settings.cache_clear()
    monkeypatch.setattr(
        FasterWhisperClient,
        "transcribe",
        lambda self, filename, content, mime_type: "这是本地 Whisper 识别的采访回答。",
    )
    try:
        response = client.post(f"/v1/evidence/assets/{asset['id']}/analyze")
        assert response.status_code == 200
        observation = response.json()
        assert observation["text"] == "这是本地 Whisper 识别的采访回答。"
        assert observation["provider"] == "faster-whisper"
        assert observation["model_name"] == "small"
    finally:
        monkeypatch.delenv("ASR_PROVIDER", raising=False)
        monkeypatch.delenv("ASR_MODEL", raising=False)
        get_settings.cache_clear()


def test_provider_asr_is_preserved_before_manual_correction(client, monkeypatch) -> None:
    from lifereel_api.core.config import get_settings
    from lifereel_api.providers.whisper import FasterWhisperClient

    person = client.post("/v1/persons", json={"display_name": "逐字稿校对"}).json()
    asset = client.post(
        "/v1/evidence/assets",
        data={"subject_id": person["id"], "kind": "audio"},
        files={"file": ("answer.webm", BytesIO(b"OggSsynthetic-audio"), "audio/webm")},
    ).json()
    client.post(
        f"/v1/evidence/assets/{asset['id']}/transcript",
        json={"text": "人工先写的文字", "source": "manual"},
    )
    monkeypatch.setenv("ASR_PROVIDER", "faster-whisper")
    monkeypatch.setenv("ASR_MODEL", "small")
    get_settings.cache_clear()
    monkeypatch.setattr(
        FasterWhisperClient,
        "transcribe",
        lambda self, filename, content, mime_type: "Whisper 识别原稿",
    )
    try:
        response = client.post(f"/v1/evidence/assets/{asset['id']}/transcribe")
        assert response.status_code == 200
        versions = response.json()["versions"]
        assert [item["source"] for item in versions] == ["manual", "provider_asr"]
        assert versions[-1]["text"] == "Whisper 识别原稿"
    finally:
        monkeypatch.delenv("ASR_PROVIDER", raising=False)
        monkeypatch.delenv("ASR_MODEL", raising=False)
        get_settings.cache_clear()


def test_evidence_is_deduplicated_and_transcript_is_versioned(client) -> None:
    person = client.post("/v1/persons", json={"display_name": "周先生"}).json()
    content = b"OggSsynthetic-audio-evidence"
    form = {
        "subject_id": person["id"],
        "kind": "audio",
        "consent_scope": "private",
    }
    first = client.post(
        "/v1/evidence/assets",
        data=form,
        files={"file": ("memory.webm", BytesIO(content), "audio/webm")},
    )
    assert first.status_code == 201
    asset = first.json()
    assert asset["byte_size"] == len(content)

    duplicate = client.post(
        "/v1/evidence/assets",
        data=form,
        files={"file": ("copy.webm", BytesIO(content), "audio/webm")},
    )
    assert duplicate.status_code == 201
    assert duplicate.json()["id"] == asset["id"]

    transcript = client.post(
        f"/v1/evidence/assets/{asset['id']}/transcript",
        json={"text": "我小时候住在海边。", "source": "mock_asr"},
    )
    assert transcript.status_code == 201
    transcript_payload = transcript.json()
    assert transcript_payload["versions"][0]["text"] == "我小时候住在海边。"

    revision = client.post(
        f"/v1/evidence/transcripts/{transcript_payload['id']}/revisions",
        json={"text": "我小时候住在海边的村子里。", "edit_reason": "补充原话"},
    )
    assert revision.status_code == 200
    versions = revision.json()["versions"]
    assert [item["version_number"] for item in versions] == [1, 2]
    assert versions[0]["text"] == "我小时候住在海边。"
    assert versions[1]["text"] == "我小时候住在海边的村子里。"

    downloaded = client.get(f"/v1/evidence/assets/{asset['id']}/content")
    assert downloaded.status_code == 200
    assert downloaded.content == content
    assert downloaded.headers["accept-ranges"] == "bytes"
    assert downloaded.headers["content-length"] == str(len(content))


def test_evidence_listing_and_deduplication_are_isolated_by_subject(client) -> None:
    first_person = client.post("/v1/persons", json={"display_name": "人物甲"}).json()
    second_person = client.post("/v1/persons", json={"display_name": "人物乙"}).json()
    content = b"OggSsame-content-for-two-subjects"

    first = client.post(
        "/v1/evidence/assets",
        data={"subject_id": first_person["id"], "kind": "audio"},
        files={"file": ("same.webm", BytesIO(content), "audio/webm")},
    )
    second = client.post(
        "/v1/evidence/assets",
        data={"subject_id": second_person["id"], "kind": "audio"},
        files={"file": ("same-copy.webm", BytesIO(content), "audio/webm")},
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert second.json()["id"] != first.json()["id"]
    assert second.json()["subject_id"] == second_person["id"]
    assert [item["subject_id"] for item in client.get(
        f"/v1/evidence/assets?subject_id={first_person['id']}"
    ).json()] == [first_person["id"]]
    assert [item["subject_id"] for item in client.get(
        f"/v1/evidence/assets?subject_id={second_person['id']}"
    ).json()] == [second_person["id"]]


def test_evidence_content_supports_chinese_filename_and_byte_ranges(client) -> None:
    person = client.post("/v1/persons", json={"display_name": "预览测试"}).json()
    content = b"0123456789"
    asset = client.post(
        "/v1/evidence/assets",
        data={"subject_id": person["id"], "kind": "document"},
        files={"file": ("家庭年表.txt", BytesIO(content), "text/plain")},
    ).json()
    url = f"/v1/evidence/assets/{asset['id']}/content"

    downloaded = client.get(url)
    assert downloaded.status_code == 200
    assert downloaded.content == content
    assert "filename*=UTF-8''" in downloaded.headers["content-disposition"]

    partial = client.get(url, headers={"Range": "bytes=2-5"})
    assert partial.status_code == 206
    assert partial.content == b"2345"
    assert partial.headers["content-range"] == "bytes 2-5/10"
    assert partial.headers["content-length"] == "4"

    suffix = client.get(url, headers={"Range": "bytes=-3"})
    assert suffix.status_code == 206
    assert suffix.content == b"789"

    invalid = client.get(url, headers={"Range": "bytes=20-30"})
    assert invalid.status_code == 416
    assert invalid.json() == {
        "error": {"code": "EVIDENCE_RANGE_INVALID", "context": {"size": 10}}
    }


def test_evidence_size_limits_are_applied_by_file_type(client, monkeypatch) -> None:
    from lifereel_api.core.config import get_settings

    person = client.post("/v1/persons", json={"display_name": "限制测试"}).json()
    monkeypatch.setenv("MAX_EVIDENCE_IMAGE_BYTES", "4")
    monkeypatch.setenv("MAX_EVIDENCE_AUDIO_BYTES", "16")
    get_settings.cache_clear()
    try:
        photo = client.post(
            "/v1/evidence/assets",
            data={"subject_id": person["id"], "kind": "photo"},
            files={"file": ("large.png", BytesIO(b"12345"), "image/png")},
        )
        assert photo.status_code == 413
        assert photo.json() == {
            "error": {
                "code": "EVIDENCE_FILE_TOO_LARGE",
                "context": {"kind": "photo", "limit_bytes": 4},
            }
        }

        audio = client.post(
            "/v1/evidence/assets",
            data={"subject_id": person["id"], "kind": "audio"},
            files={"file": ("allowed.wav", BytesIO(b"RIFF1234WAVE"), "audio/wav")},
        )
        assert audio.status_code == 201
        assert audio.json()["byte_size"] == 12
    finally:
        get_settings.cache_clear()


def test_evidence_kind_must_match_mime_type(client) -> None:
    person = client.post("/v1/persons", json={"display_name": "类型测试"}).json()
    response = client.post(
        "/v1/evidence/assets",
        data={"subject_id": person["id"], "kind": "video"},
        files={"file": ("not-video.png", BytesIO(b"image"), "image/png")},
    )

    assert response.status_code == 415
    assert response.json() == {"error": {"code": "EVIDENCE_TYPE_UNSUPPORTED"}}


def test_evidence_rejects_spoofed_image_content(client) -> None:
    person = client.post("/v1/persons", json={"display_name": "伪造类型测试"}).json()
    response = client.post(
        "/v1/evidence/assets",
        data={"subject_id": person["id"], "kind": "photo"},
        files={"file": ("spoof.png", BytesIO(b"this is plain text"), "image/png")},
    )

    assert response.status_code == 415
    assert response.json() == {"error": {"code": "EVIDENCE_TYPE_UNSUPPORTED"}}


def test_evidence_rejects_audio_content_disguised_as_video(client) -> None:
    person = client.post("/v1/persons", json={"display_name": "音视频类型测试"}).json()
    response = client.post(
        "/v1/evidence/assets",
        data={"subject_id": person["id"], "kind": "video"},
        files={"file": ("spoof.mp4", BytesIO(b"ID3synthetic-audio"), "video/mp4")},
    )

    assert response.status_code == 415
    assert response.json() == {"error": {"code": "EVIDENCE_TYPE_UNSUPPORTED"}}
