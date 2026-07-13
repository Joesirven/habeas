from habeas_privacy_core.health import health_payload


def test_health_payload():
    assert health_payload() == {"status": "ok"}
