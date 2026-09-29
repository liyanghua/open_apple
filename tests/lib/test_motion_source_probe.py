"""Real decoded PTS regressions: aggregate stream rates cannot establish CFR."""
from pathlib import Path
import shutil
import subprocess
import io
import threading

import pytest

from lib.render_plan import probe_media


def cadence(path: Path, probe: dict, **kwargs):
    import lib.production_brand as brand
    assert hasattr(brand, "probe_motion_source_cadence"), "independent decoded PTS check is missing"
    return brand.probe_motion_source_cadence(path, probe, **kwargs)


@pytest.fixture
def encoded_pair(tmp_path):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("ffmpeg/ffprobe required for real PTS regression")
    cfr, vfr = tmp_path / "cfr.mp4", tmp_path / "vfr.mp4"
    for path, pts in ((cfr, "N*3000"), (vfr, "N*3000+if(eq(N\\,110)\\,300\\,0)")):
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=red:s=64x64:r=30:d=4",
            "-vf", f"settb=1/90000,setpts={pts}", "-fps_mode", "passthrough", "-enc_time_base", "1:90000",
            "-c:v", "libx264", "-bf", "0", str(path)], capture_output=True, check=True, timeout=30)
    return cfr, vfr


def test_actual_local_vfr_is_rejected_despite_equal_stream_rates_count_and_duration(encoded_pair):
    from lib.production_brand import validate_motion_source_metadata
    cfr, vfr = encoded_pair
    shot = {"sourceFps": 30, "sourceDurationSeconds": 4, "framing": {"source": {"width": 64, "height": 64}}}
    for path in (cfr, vfr):
        assert validate_motion_source_metadata(shot, probe_media(path))["frame_count"] == 120
    result = cadence(cfr, probe_media(cfr))
    assert result["frame_count"] == 120
    assert result["min_delta_ticks"] == result["max_delta_ticks"] == 3000
    with pytest.raises(ValueError, match="PTS cadence"):
        cadence(vfr, probe_media(vfr))


@pytest.mark.parametrize("name", ["A01-H1-seedance-v1.mp4", "A03-H3-seedance-v1.mp4"])
def test_real_seedance_24fps_97_frames_remains_compatible(name):
    path = Path(__file__).resolve().parents[2] / "projects/opening-upgrade-validation/assets/video/hooks-20260928" / name
    if not path.is_file():
        pytest.skip("local source fixture is optional")
    result = cadence(path, probe_media(path))
    assert result["frame_count"] == 97
    assert result["time_base"] == "1/12288"
    assert result["min_delta_ticks"] == result["max_delta_ticks"] == 512


def test_cadence_limits_refuse_unbounded_media_before_spawn(encoded_pair):
    cfr, _ = encoded_pair
    with pytest.raises(ValueError, match="bounded"):
        cadence(cfr, probe_media(cfr), max_frames=119)


@pytest.mark.parametrize("declared_count", [119, 121])
def test_decoded_frame_count_must_match_header_not_just_declared_metadata(encoded_pair, declared_count):
    cfr, _ = encoded_pair
    probe = probe_media(cfr)
    probe["streams"][0]["nb_frames"] = str(declared_count)
    with pytest.raises(ValueError, match="frame count"):
        cadence(cfr, probe)


def test_fractional_time_base_rounding_is_allowed_without_cumulative_drift(monkeypatch):
    from lib import motion_source_probe
    count = 97
    probe = {"streams": [{"codec_type": "video", "nb_frames": str(count), "duration": "4.041667",
        "avg_frame_rate": "24/1", "time_base": "1/1000"}]}
    class CompletedProcess:
        stdout = io.StringIO("".join(f"{i * 125 // 3}\n" for i in range(count)))
        def poll(self): return 0
        def wait(self, **kwargs): return 0
    monkeypatch.setattr(motion_source_probe.shutil, "which", lambda name: "ffprobe")
    monkeypatch.setattr(motion_source_probe.subprocess, "Popen", lambda *a, **k: CompletedProcess())
    result = cadence(Path("source.mp4"), probe)
    assert result["frame_count"] == 97
    assert result["allowed_delta_ticks"] == [41, 42]
    assert result["min_delta_ticks"] == 41 and result["max_delta_ticks"] == 42


@pytest.mark.parametrize("problem", ["timeout", "oversized_line"])
def test_streaming_probe_timeout_and_output_limits_kill_the_process(monkeypatch, problem):
    from lib import motion_source_probe
    stopped = threading.Event()
    class Reader:
        def readline(self, limit):
            if problem == "oversized_line": return "1" * limit
            assert stopped.wait(2), "timeout must kill ffprobe to unblock streaming stdout"
            return ""
        def close(self): pass
    class Process:
        stdout = Reader()
        def poll(self): return -9 if stopped.is_set() else None
        def kill(self): stopped.set()
        def wait(self, **kwargs): return -9
    monkeypatch.setattr(motion_source_probe.shutil, "which", lambda name: "ffprobe")
    monkeypatch.setattr(motion_source_probe.subprocess, "Popen", lambda *a, **k: Process())
    probe = {"streams": [{"codec_type": "video", "nb_frames": "120", "duration": "4",
        "avg_frame_rate": "30/1", "time_base": "1/90000"}]}
    with pytest.raises(ValueError, match="timeout" if problem == "timeout" else "bounded"):
        cadence(Path("source.mp4"), probe, timeout_seconds=.01)
    assert stopped.is_set()
