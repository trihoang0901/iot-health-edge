from __future__ import annotations

from simulator.network_profiles import build_schedule, get_profile, public_profiles


def test_baseline_schedule_never_injects_impairment():
    schedule = build_schedule(get_profile("lan-baseline"), count=20, seed=42)

    assert len(schedule) == 20
    assert all(item.delay_ms == 0 for item in schedule)
    assert all(not item.intentionally_dropped for item in schedule)


def test_remote_app_schedule_is_deterministic_and_truthfully_labeled():
    profile = get_profile("remote-app-emulated")

    first = build_schedule(profile, count=30, seed=532)
    second = build_schedule(profile, count=30, seed=532)

    assert first == second
    assert any(item.delay_ms > 0 for item in first)
    assert any(item.intentionally_dropped for item in first)
    assert profile.profile_kind == "app_impairment"
    assert profile.injection_point == "before_mqtt_publish"
    assert profile.network_claim == "none"


def test_public_profiles_never_claim_measured_5g():
    profiles = public_profiles()

    assert {item["name"] for item in profiles} == {
        "lan-baseline",
        "remote-app-emulated",
    }
    assert all(item["network_claim"] == "none" for item in profiles)
    assert "5g-emulated" not in str(profiles).lower()
