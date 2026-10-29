"""AD-1346 M3c1 (#1604): ``admission.shadow_enabled``, the switch of the shadow admission decision.

- W1 the field defaults to true, and a config file can turn it off.
- W2 with it off, a real boot builds no shadow store, recorder or service, creates no ``admission_shadow.db`` and says
     so once at INFO.
- W3 with it on, shutdown closes the service before the recorder's last flush: a ``shadow`` call made when that flush
     begins decides and counts nothing (R6).

The boots use ``SystemConfig()`` with the naming ceremony, the proactive loop and QA turned off, as
``tests/test_ad1346_admission_service_boot.py`` does, and ``MockLLMClient``; every data directory is under ``tmp_path``.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from probos.admission import AdmissionService
from probos.admission.recorder import ShadowRecorder
from probos.admission.store import STORE_FILENAME
from probos.cognitive.llm_client import MockLLMClient
from probos.config import AdmissionConfig, SystemConfig, load_config
from probos.runtime import ProbOSRuntime


def _config(*, shadow_enabled: bool) -> SystemConfig:
    config = SystemConfig()
    config.onboarding.naming_ceremony = False
    config.proactive_cognitive.enabled = False
    config.qa.enabled = False
    config.admission.shadow_enabled = shadow_enabled
    return config


async def _boot(data_dir: Path, *, shadow_enabled: bool) -> ProbOSRuntime:
    runtime = ProbOSRuntime(config=_config(shadow_enabled=shadow_enabled), data_dir=data_dir, llm_client=MockLLMClient())
    await runtime.start()
    return runtime


def test_the_switch_defaults_on_and_a_config_file_turns_it_off(tmp_path: Path) -> None:
    """W1 (kills CF-1)."""
    assert list(AdmissionConfig.model_fields) == ["shadow_enabled"]
    assert SystemConfig().admission.shadow_enabled is True
    path = tmp_path / "system.yaml"
    path.write_text("admission:\n  shadow_enabled: false\n", encoding="utf-8")
    assert load_config(path).admission.shadow_enabled is False


async def test_with_the_switch_off_a_boot_builds_no_shadow_store_recorder_or_service(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    """W2 (kills RT-1)."""
    caplog.set_level(logging.INFO, logger="probos.runtime")
    data_dir = tmp_path / "data"
    rt = await _boot(data_dir, shadow_enabled=False)
    try:
        assert (rt.admission_service, rt.admission_shadow_store, rt.admission_shadow_recorder) == (None, None, None)
        assert not (data_dir / STORE_FILENAME).exists()
        notes = [
            r for r in caplog.records
            if r.name == "probos.runtime" and "admission.shadow_enabled is false" in r.getMessage()
        ]
        assert [r.levelno for r in notes] == [logging.INFO]
    finally:
        await rt.stop()


async def test_shutdown_closes_the_service_before_the_recorders_last_flush(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W3: R6 decided (D61) (kills SD-1)."""
    rt = await _boot(tmp_path / "data", shadow_enabled=True)
    seen: dict[str, object] = {}
    try:
        service, recorder = rt.admission_service, rt.admission_shadow_recorder
        assert isinstance(service, AdmissionService) and isinstance(recorder, ShadowRecorder)
        assert vars(service)["_closed"] is False
        real_stop = recorder.stop

        async def stop_after_one_more_call() -> None:
            seen["closed"] = vars(service)["_closed"]
            before = service.tally()
            service.shadow(
                presented_id="system:ship_computer", work_kind="intent", seam="intent", origin="system",
                origin_id="ad1346-m3c1",
            )
            seen["counted"] = service.tally() != before
            await real_stop()

        monkeypatch.setattr(recorder, "stop", stop_after_one_more_call)
    finally:
        await rt.stop()
    assert seen == {"closed": True, "counted": False}
    assert recorder.counters()["late"] == 0
