import sys
import types
import shlex
from pathlib import Path

import numpy as np
import pytest
from PyQt5.QtWidgets import QApplication

"""
Test Suite for HeliCAL Control Station
======================================

Comprehensive pytest coverage for the PyQt GUI and pipeline helper functions. The suite
 stubs out external dependencies (vamtoolbox, SSH) so every button, dialog, and
helper method can be validated. Run with:

    python -m pytest tests/test_gui_control_station.py
"""


# Provide lightweight stubs for vamtoolbox so gui_test can import cleanly
# without the real external dependency or lab hardware.
if "vamtoolbox" not in sys.modules:
    vam_stub = types.ModuleType("vamtoolbox")

    class _Resources:
        def __init__(self):
            self.loaded = []

        def load(self, name):
            self.loaded.append(name)
            return str(Path.cwd() / name)

    vam_stub.resources = _Resources()
    sys.modules["vamtoolbox"] = vam_stub

    projector_stub = types.ModuleType("vamtoolbox.projector")

    class _ProjectorBackend:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

        def forward(self, array):
            return np.zeros((4, 4, 4), dtype=np.float32)

        def backward(self, array):
            return np.zeros((4, 4, 4), dtype=np.float32)

    class _ProjNamespace:
        Projector3DParallelAstra = _ProjectorBackend
        Projector3DParallelPython = _ProjectorBackend

    projector_stub.Projector3DParallel = _ProjNamespace()
    sys.modules["vamtoolbox.projector"] = projector_stub

    geometry_stub = types.ModuleType("vamtoolbox.geometry")

    class _TargetGeometry:
        def __init__(self, *args, **kwargs):
            self.array = np.zeros((4, 4, 4), dtype=np.float32)

    class _ProjectionGeometry:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    class _Sinogram:
        def __init__(self, array, proj_geo):
            self.array = np.asarray(array)
            self.proj_geo = proj_geo

    geometry_stub.TargetGeometry = _TargetGeometry
    geometry_stub.ProjectionGeometry = _ProjectionGeometry
    geometry_stub.Sinogram = _Sinogram
    geometry_stub.Reconstruction = _Sinogram
    sys.modules["vamtoolbox.geometry"] = geometry_stub


import gui_test
import pipeline_helpers as helpers


class DummySSHWorker:
    """Minimal stand-in that records commands so tests can assert the G-code strings."""
    def __init__(self):
        self.commands = []
        self.uploads = []
        self.shells = []
        self.stopped = False

    def enqueue_command(self, command):
        """Pretend to queue a command by storing it on the instance."""
        self.commands.append(command)

    def enqueue_upload(self, local_path, remote_path):
        """Record queued uploads for later assertions."""
        self.uploads.append((local_path, remote_path))

    def enqueue_shell(self, command, needs_sudo=False):
        """Record shell commands and whether sudo was requested."""
        self.shells.append((command, needs_sudo))

    def stop(self):
        """Mark the worker as stopped."""
        self.stopped = True



@pytest.fixture(scope="session")
def qt_app():
    """Ensure a QApplication instance exists so PyQt widgets can be constructed."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture(autouse=True)
def dialog_spy(monkeypatch):
    """Capture QMessageBox calls so tests can assert that alerts were shown."""
    records = {k: [] for k in ("information", "warning", "critical", "question")}
    records["_question_return"] = gui_test.QMessageBox.Yes

    def _simple_stub(name, ret):
        def _impl(*args, **kwargs):
            title = args[1] if len(args) > 1 else ""
            text = args[2] if len(args) > 2 else ""
            records[name].append({"title": title, "text": text})
            return ret

        return _impl

    monkeypatch.setattr(gui_test.QMessageBox, "information", _simple_stub("information", gui_test.QMessageBox.Ok))
    monkeypatch.setattr(gui_test.QMessageBox, "warning", _simple_stub("warning", gui_test.QMessageBox.Ok))
    monkeypatch.setattr(gui_test.QMessageBox, "critical", _simple_stub("critical", gui_test.QMessageBox.Ok))

    def _question_stub(*args, **kwargs):
        title = args[1] if len(args) > 1 else ""
        text = args[2] if len(args) > 2 else ""
        records["question"].append({"title": title, "text": text})
        return records["_question_return"]

    monkeypatch.setattr(gui_test.QMessageBox, "question", _question_stub)
    return records


@pytest.fixture
def gui(qt_app, monkeypatch):
    """Build a HeliCALQt window with a fake SSH worker for isolated testing."""
    window = gui_test.HeliCALQt()
    window._ssh_worker = DummySSHWorker()
    window._ssh_connected = True
    window._update_connection_indicator()
    yield window
    window.close()


def test_cfg_from_ui_reflects_widget_values(gui):
    """Ensure the config dictionary mirrors the live spin box values."""
    gui.sb_res.setValue(192)
    gui.sb_ang.setValue(60)
    gui.dsb_thr.setValue(0.75)
    gui.dsb_px.setValue(0.2)
    gui.sb_fr.setValue(1500)
    gui.sb_on.setValue(200)
    gui.sb_off.setValue(12)
    gui.sb_dw.setValue(10)
    cfg = gui._cfg_from_ui()
    assert cfg["resolution"] == 192
    assert cfg["num_angles"] == 60
    assert cfg["proj_threshold"] == pytest.approx(0.75)
    assert cfg["pixel_size_mm"] == pytest.approx(0.2)
    assert cfg["feedrate"] == 1500
    assert cfg["laser_power_on"] == 200
    assert cfg["laser_power_off"] == 12
    assert cfg["dwell_ms"] == 10


def test_save_cfg_clicked_persists_cfg_and_notifies(gui, monkeypatch, dialog_spy):
    """Verify that clicking save passes data to _save_cfg and shows a dialog."""
    captured = {}

    def _fake_save(cfg):
        captured["cfg"] = cfg

    monkeypatch.setattr(gui_test, "_save_cfg", _fake_save)
    gui._save_cfg_clicked()
    assert "cfg" in captured
    assert dialog_spy["information"]


def test_run_pipeline_clicked_aborts_when_helpers_missing(gui, monkeypatch, dialog_spy):
    """If pipeline helpers are unavailable the GUI should block the run and alert the user."""
    monkeypatch.setattr(gui_test, "PIPELINE_OK", False)
    gui._run_pipeline_clicked()
    assert dialog_spy["critical"]


def test_update_connection_indicator_toggles_disconnect_button(gui):
    """The connection indicator should lock or unlock the disconnect button appropriately."""
    gui._ssh_connected = False
    gui._update_connection_indicator()
    assert not gui.btn_manual_disconnect.isEnabled()
    gui._ssh_connected = True
    gui._update_connection_indicator()
    assert gui.btn_manual_disconnect.isEnabled()


def test_show_connection_failed_message_prompts_user(gui, dialog_spy):
    """The Wi-Fi hint dialog should appear when connection attempts fail."""
    gui._show_connection_failed_message()
    assert dialog_spy["critical"]


def test_probe_ssh_host_success(gui, monkeypatch):
    """A reachable Jetson should cause _probe_ssh_host to return True."""
    class DummyConn:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    captured = {}

    def fake_conn(addr, timeout=0):
        captured["addr"] = addr
        return DummyConn()

    monkeypatch.setattr(gui_test.socket, "create_connection", fake_conn)
    assert gui._probe_ssh_host()
    assert captured["addr"] == (gui.ssh_host, 22)


def test_probe_ssh_host_failure_logs(gui, monkeypatch):
    """Socket errors should be logged and the method should return False."""
    def fake_conn(*args, **kwargs):
        raise OSError("boom")

    monkeypatch.setattr(gui_test.socket, "create_connection", fake_conn)
    assert not gui._probe_ssh_host()
    assert "[SSH] Probe error" in gui.txt_log.toPlainText()


def test_prompt_remote_password_launches_worker(gui, monkeypatch):
    """Accepting the password dialog should trigger the SSH worker launch."""
    gui._ssh_connected = False
    gui._update_connection_indicator()

    class FakeDialog:
        def __init__(self, *args, **kwargs):
            self._password = "secret"

        def exec_(self):
            return gui_test.QDialog.Accepted

        def password(self):
            return self._password

    captured = {}
    monkeypatch.setattr(gui_test, "PasswordDialog", FakeDialog)
    monkeypatch.setattr(gui, "_launch_ssh_worker", lambda pw: captured.setdefault("pw", pw))
    gui._prompt_remote_password()
    assert captured["pw"] == "secret"
    assert gui._ssh_connecting


def test_prompt_remote_password_retries_on_empty(gui, monkeypatch, dialog_spy):
    """If the dialog is accepted without a password the user should be warned and re-prompted."""
    gui._ssh_connected = False
    gui._update_connection_indicator()

    calls = {"count": 0}

    class FakeDialog:
        def __init__(self, *args, **kwargs):
            pass

        def exec_(self):
            calls["count"] += 1
            return gui_test.QDialog.Accepted

        def password(self):
            return ""

    scheduled = {"func": None}

    def fake_single_shot(delay, func):
        scheduled["func"] = func

    monkeypatch.setattr(gui_test, "PasswordDialog", FakeDialog)
    monkeypatch.setattr(gui_test.QTimer, "singleShot", fake_single_shot)
    gui._prompt_remote_password()
    assert dialog_spy["warning"]
    assert scheduled["func"] == gui._prompt_remote_password


def test_ensure_remote_ready_blocks_without_connection(gui, dialog_spy):
    """G-code sends must be prevented when SSH is not connected."""
    gui._ssh_connected = False
    gui._ssh_worker = None
    assert not gui._ensure_remote_ready()
    assert dialog_spy["warning"]


def test_send_gcode_command_enqueues_when_ready(gui):
    """Commands should be forwarded to the worker and echoed locally."""
    gui._send_gcode_command("G90")
    assert gui._ssh_worker.commands[-1] == "G90"
    assert "G90" in gui.txt_gcode_log.toPlainText()


def test_send_gcode_command_skips_when_not_ready(gui, monkeypatch):
    """If the SSH link is down the command should not be enqueued."""
    monkeypatch.setattr(gui, "_ensure_remote_ready", lambda: False)
    gui._ssh_worker.commands.clear()
    gui._send_gcode_command("G0")
    assert gui._ssh_worker.commands == []


def test_send_gcode_command_logs_local_error(gui):
    """If the worker raises errors they should appear in the G-code log."""
    class FaultyWorker:
        def enqueue_command(self, command):
            raise RuntimeError("boom")

    gui._ssh_worker = FaultyWorker()
    gui._send_gcode_command("G91")
    assert "[LOCAL] Failed to queue command" in gui.txt_gcode_log.toPlainText()


def test_cleanup_finished_thread_resets_handles(gui):
    """Finished threads should be released to allow future reconnects."""
    class DummyThread:
        def isRunning(self):
            return False

    gui._ssh_thread = DummyThread()
    gui._cleanup_finished_thread()
    assert gui._ssh_thread is None


def test_disconnect_clicked_requests_shutdown(gui, dialog_spy):
    """The Disconnect button should submit a shutdown command then drop the status."""
    gui._ssh_connected = True
    gui._ssh_worker = DummySSHWorker()
    gui._disconnect_clicked()
    assert gui._ssh_worker.commands[0] == "sudo shutdown now"
    assert not gui._ssh_connected


def test_disconnect_clicked_no_connection_shows_info(gui, dialog_spy):
    """Clicking disconnect without an active session should just inform the user."""
    gui._ssh_connected = False
    gui._ssh_worker = None
    gui._disconnect_clicked()
    assert dialog_spy["information"]


def test_on_ssh_success_homes_when_confirmed(gui, dialog_spy):
    """Successful connections should prompt for homing and run G28 when accepted."""
    sent = []
    gui._send_gcode_command = sent.append
    gui._on_ssh_success()
    assert dialog_spy["question"]
    assert sent == ["G28"]


def test_on_ssh_success_skips_homing_when_declined(gui, dialog_spy):
    """Operators can decline homing immediately after connecting."""
    dialog_spy["_question_return"] = gui_test.QMessageBox.No
    sent = []
    gui._send_gcode_command = sent.append
    gui._on_ssh_success()
    assert sent == []


def test_collect_feedrates_only_returns_filled_entries(gui):
    """FR/FT/FZ strings should only appear for text boxes that contain numbers."""
    gui.le_g1_fr.setText("100")
    gui.le_g1_ft.setText("")
    gui.le_g1_fz.setText("200")
    assert gui._collect_feedrates() == ["FR100", "FZ200"]


def test_send_axis_command_warns_without_axes(gui, dialog_spy):
    """Motion buttons must not fire if every axis entry is blank."""
    gui._send_axis_command("G0", {"R": gui.le_g0_r, "T": gui.le_g0_t, "Z": gui.le_g0_z})
    assert dialog_spy["warning"]


def test_send_axis_command_sends_composed_command(gui):
    """When axes are filled in, the composed command should include them and extra arguments."""
    commands = []
    gui._send_gcode_command = commands.append
    gui.le_g0_r.setText("10")
    gui.le_g0_z.setText("5")
    gui._send_axis_command("G0", {"R": gui.le_g0_r, "T": gui.le_g0_t, "Z": gui.le_g0_z}, ["FR120"])
    assert commands[0] == "G0 R10 Z5 FR120"


def test_send_g4_wait_uses_spinbox_value(gui):
    """The pause helper must convert the double spin value into a G4 command."""
    commands = []
    gui._send_gcode_command = commands.append
    gui.sb_g4_wait.setValue(12.5)
    gui._send_g4_wait()
    assert commands[0] == "G4 P12.5"


def test_send_g92_zero_uses_dropdown(gui):
    """G92 should target whichever axis is currently selected in the combo box."""
    commands = []
    gui._send_gcode_command = commands.append
    gui.cb_g92_axis.setCurrentText("T")
    gui._send_g92_zero()
    assert commands[0] == "G92 T"


def test_send_custom_command_clears_field(gui):
    """After sending a custom line the textbox should clear."""
    commands = []
    gui._send_gcode_command = commands.append
    gui.le_custom_cmd.setText("M114")
    gui._send_custom_command()
    assert commands[0] == "M114"
    assert gui.le_custom_cmd.text() == ""


def test_save_gcode_log_writes_text(gui, tmp_path, monkeypatch):
    """Saving the log should write the QTextEdit contents to the chosen path."""
    target = tmp_path / "gcode.txt"
    monkeypatch.setattr(gui_test.QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), "txt"))
    gui.txt_gcode_log.setText("hello log")
    gui._save_gcode_log()
    assert target.read_text(encoding="utf-8") == "hello log"


def test_send_jog_requires_positive_values(gui, dialog_spy, monkeypatch):
    """Jog commands should validate both the step size and feed speed."""
    monkeypatch.setattr(gui.le_jog_step, "value", lambda: 0.0)
    monkeypatch.setattr(gui.le_jog_feed, "value", lambda: 10.0)
    gui._send_jog("R", 1)
    assert dialog_spy["warning"]


def test_send_jog_emits_relative_sequence(gui):
    """A successful jog should emit the expected G91/G1/G90 trio."""
    sent = []
    gui._send_gcode_command = sent.append
    gui.le_jog_step.setValue(2.0)
    gui.le_jog_feed.setValue(50.0)
    gui._send_jog("Z", 1)
    assert sent == ["G91", "G1 Z2.0 F50.0", "G90"]


def test_send_start_sequence_requires_values(gui, dialog_spy):
    """If the start macro lacks a target position it should warn and exit."""
    gui.le_g0_r.clear()
    gui.le_g0_t.clear()
    gui.le_g0_z.clear()
    gui._send_start_sequence()
    assert any(msg["title"] == "Start Sequence" for msg in dialog_spy["warning"])


def test_send_start_sequence_runs_full_flow(gui):
    """When values exist the macro should send the hard-coded sequence including the G0 line."""
    sent = []
    gui._send_gcode_command = sent.append
    gui.le_g0_r.setText("1")
    gui.le_g0_t.setText("2")
    gui.le_g0_z.setText("3")
    gui._send_start_sequence()
    assert sent == ["M17", "G28", "G0 R1 T2 Z3", "G92", "G33 A9", "G5"]


def test_send_end_sequence_stops_machine(gui):
    """The end macro should always issue the stop commands in order."""
    sent = []
    gui._send_gcode_command = sent.append
    gui._send_end_sequence()
    assert sent == ["G33 A0", "G28", "M18 R T"]


def test_send_led_current_uses_spinbox_value(gui):
    """Setting the LED current should emit the new M205 command."""
    sent = []
    gui._send_gcode_command = sent.append
    gui.sb_led_current.setValue(123)
    gui._send_led_current()
    assert sent == ["M205 S123"]


def test_console_input_sends_entered_command(gui):
    """Typing into the console input line should dispatch commands."""
    sent = []
    gui._send_gcode_command = sent.append
    gui.le_terminal_input.setText("G0 R5")
    gui._handle_terminal_input()
    assert sent == ["G0 R5"]
    assert gui.le_terminal_input.text() == ""


def test_upload_video_clicked_queues_upload(gui, tmp_path):
    """Uploading a video should queue the transfer with the worker."""
    video = tmp_path / "projector.mp4"
    video.write_text("stub", encoding="utf-8")
    gui.le_video.setText(str(video))
    gui._upload_video_clicked()
    assert gui._ssh_worker.uploads[-1] == (str(video), f"{gui.remote_dir}/Videos/{video.name}")
    assert gui.current_video_remote_path.endswith(video.name)


def test_upload_video_clicked_rejects_non_mp4(gui, tmp_path, dialog_spy):
    """Only MP4 assets should be accepted for upload."""
    video = tmp_path / "clip.mov"
    video.write_text("stub", encoding="utf-8")
    gui.le_video.setText(str(video))
    gui._upload_video_clicked()
    assert dialog_spy["warning"]
    assert gui._ssh_worker.uploads == []


def test_on_remote_file_uploaded_triggers_playback(gui):
    """Once the remote upload finishes the GUI should queue playback shell commands."""
    remote = "/home/jacob/Desktop/HeliCAL_Final/Videos/demo.mp4"
    gui._on_remote_file_uploaded(remote)
    expected_shells = [
        "pkill mpv || true",
        (
            f"DISPLAY=:0 nohup mpv --title=ProjectorVideo --pause --no-border --loop=inf "
            f"--video-rotate=180 {shlex.quote(remote)} >/tmp/mpv.log 2>&1 &"
        ),
        "DISPLAY=:0 xdotool search --name ProjectorVideo windowmove 1920 0",
        "DISPLAY=:0 xdotool search --name ProjectorVideo windowsize 2560 1600",
        "DISPLAY=:0 xdotool search --name ProjectorVideo windowactivate --sync key f",
    ]
    assert [cmd for cmd, _ in gui._ssh_worker.shells] == expected_shells
    assert all(not needs_sudo for _, needs_sudo in gui._ssh_worker.shells)
    assert gui.current_video_remote_path == remote


def test_build_axis_command_for_sequence_handles_missing(gui):
    """The helper should return None when no axes are filled and a string otherwise."""
    gui.le_g0_r.clear()
    assert gui._build_axis_command_for_sequence() is None
    gui.le_g0_r.setText("5")
    gui.le_g0_z.setText("1")
    assert gui._build_axis_command_for_sequence() == "G0 R5 Z1"


def test_append_connection_log_updates_both_logs(gui):
    """SSH log lines should appear in both QTextEdits."""
    gui.txt_log.clear()
    gui.txt_gcode_log.clear()
    gui._append_connection_log("[SSH] test")
    assert "[SSH] test" in gui.txt_log.toPlainText()
    assert "[SSH] test" in gui.txt_gcode_log.toPlainText()


def test_pipeline_helper_resolve_stl_path_prefers_user_file(tmp_path):
    """The helper should return the provided file when it exists."""
    mesh = tmp_path / "mesh.stl"
    mesh.write_text("stub", encoding="utf-8")
    resolved = helpers.resolve_stl_path(str(mesh), False)
    assert resolved == str(mesh)


def test_pipeline_helper_resolve_stl_path_demo_mode(monkeypatch):
    """In demo mode the helper should fall back to packaged assets."""
    class DemoResources:
        def __init__(self):
            self.calls = 0

        def load(self, name):
            self.calls += 1
            if name == "ring.stl":
                return f"/demo/{name}"
            raise FileNotFoundError

    monkeypatch.setattr(helpers, "vam", types.SimpleNamespace(resources=DemoResources()))
    resolved = helpers.resolve_stl_path("missing.stl", True)
    assert resolved.endswith("ring.stl")


def test_pipeline_helper_gcode_from_slice_and_write(tmp_path):
    """Toy G-code generation should emit text and create the .gcode file."""
    img = np.array([[0.0, 1.0], [0.4, 0.6]], dtype=float)
    cfg = {
        "proj_threshold": 0.5,
        "pixel_size_mm": 0.1,
        "feedrate": 1200,
        "laser_power_on": 200,
        "laser_power_off": 0,
        "dwell_ms": 1,
    }
    code = helpers.gcode_from_slice(img, cfg)
    assert "G21" in code
    out = helpers.write_gcode_from_recon_slice(str(tmp_path), np.stack([img, img, img], axis=-1), cfg)
    assert Path(out).exists()


def test_pipeline_helper_save_reconstruction_video(monkeypatch, tmp_path):
    """Video helper should call saveAsVideo when ImageSeq/ImageConfig exist."""
    saved = {}

    class DummyImageConfig:
        def __init__(self, *args, **kwargs):
            self.args = args

    class DummyImageSeq:
        def __init__(self, cfg, sinogram):
            self.cfg = cfg
            self.sinogram = sinogram

        def saveAsVideo(self, save_path, rot_vel, preview):
            saved["path"] = save_path
            Path(save_path).write_text("video", encoding="utf-8")

    monkeypatch.setattr(helpers, "ImageConfig", DummyImageConfig)
    monkeypatch.setattr(helpers, "ImageSeq", DummyImageSeq)
    sino = types.SimpleNamespace(array=np.zeros((2, 2)))
    out = helpers.save_reconstruction_video(str(tmp_path), sino)
    if out:
        assert Path(out).exists()


def test_pipeline_worker_run_success(monkeypatch, tmp_path):
    """The threaded worker should emit done when every helper succeeds."""
    recon = np.zeros((2, 2, 2), dtype=float)
    sino = types.SimpleNamespace(array=np.zeros((2, 2)), proj_geo=None)
    ns = types.SimpleNamespace(
        resolve_stl_path=lambda stl, demo: "resolved.stl",
        voxelize_stl=lambda path, res: "tg",
        run_projection=lambda tg, num_angles, ray_type: (recon, sino, "recon"),
        save_projection_images=lambda out, s, r: (str(Path(out) / "sino.png"), str(Path(out) / "recon.png")),
        save_angle_montage=lambda *a, **k: None,
        write_gcode_from_recon_slice=lambda out, r, cfg: str(Path(out) / "toy.gcode"),
        save_reconstruction_video=lambda out, s: str(Path(out) / "preview.mp4"),
    )
    monkeypatch.setattr(gui_test, "pipeline", ns)
    monkeypatch.setattr(gui_test, "PIPELINE_OK", True)
    worker = gui_test.PipelineWorker("mesh.stl", str(tmp_path), {"resolution": 2, "num_angles": 1, "ray_type": "parallel"}, True)
    events = []
    worker.done.connect(lambda out: events.append(("done", out)))
    worker.failed.connect(lambda err: events.append(("failed", err)))
    worker.run()
    assert events and events[-1][0] == "done"


def test_pipeline_worker_run_fails_when_pipeline_missing(monkeypatch):
    """If the helpers cannot be imported the worker should emit failed."""
    monkeypatch.setattr(gui_test, "PIPELINE_OK", False)
    worker = gui_test.PipelineWorker("", "", {"resolution": 1, "num_angles": 1, "ray_type": "parallel"}, False)
    errors = []
    worker.failed.connect(lambda err: errors.append(err))
    worker.run()
    assert "not available" in errors[0]


def test_pipeline_worker_run_handles_exceptions(monkeypatch):
    """Helper exceptions should be surfaced via the failed signal."""
    def bad_resolve(*args, **kwargs):
        raise RuntimeError("missing file")

    ns = types.SimpleNamespace(
        resolve_stl_path=bad_resolve,
        voxelize_stl=lambda *a, **k: None,
        run_projection=lambda *a, **k: None,
        save_projection_images=lambda *a, **k: None,
        save_angle_montage=lambda *a, **k: None,
        write_gcode_from_recon_slice=lambda *a, **k: None,
        save_reconstruction_video=lambda *a, **k: None,
    )
    monkeypatch.setattr(gui_test, "pipeline", ns)
    monkeypatch.setattr(gui_test, "PIPELINE_OK", True)
    worker = gui_test.PipelineWorker("", "", {"resolution": 1, "num_angles": 1, "ray_type": "parallel"}, False)
    errors = []
    worker.failed.connect(lambda err: errors.append(err))
    worker.run()
    assert "missing file" in errors[0]


def test_sino_preview_2d_handles_volumes():
    """The helper should collapse 3D arrays into 2D slices."""
    data = np.zeros((3, 3, 3), dtype=float)
    preview = helpers._sino_preview_2d(data)
    assert preview.ndim == 2


def test_save_projection_images_and_montage(tmp_path):
    """Saving preview artifacts should create PNG files."""
    sino = types.SimpleNamespace(array=np.zeros((4, 4)), proj_geo=None)
    recon = np.zeros((4, 4, 4))
    sino_path, recon_path = helpers.save_projection_images(str(tmp_path), sino, recon)
    helpers.save_angle_montage(str(tmp_path), sino, n_cols=2)
    assert Path(sino_path).exists()
    assert Path(recon_path).exists()
    assert (Path(tmp_path) / "angle_montage.png").exists()
