from common.logging import mask_secrets


def test_mask_secrets_removes_rtsp_password_and_query_secrets():
    text = "rtsp://admin:camera-pass@10.0.0.1/stream password=db-pass SECRET_KEY=abc"

    masked = mask_secrets(text)

    assert "camera-pass" not in masked
    assert "db-pass" not in masked
    assert "abc" not in masked
    assert "rtsp://admin:***@10.0.0.1/stream" in masked

