import time
import shlex
from queue import Queue, Empty
import paramiko
from PyQt5.QtCore import QThread, pyqtSignal

class SSHWorker(QThread):
    """
    Background worker that connects over SSH, compiles and runs the master_queue,
    and streams commands/logs. Implements advanced remote control features.
    """
    # --- Signals ---
    log_message = pyqtSignal(str, str)  # (Message, Level)
    connection_status = pyqtSignal(bool)  # True (Connected) / False (Disconnected)
    upload_progress = pyqtSignal(int)  # 0-100 for file transfers
    file_uploaded = pyqtSignal(str) # (remote_path) - Emitted upon successful upload

    def __init__(self, host="192.168.0.123", user="jacob", password=""):
        super().__init__()
        self.host = host
        self.user = user
        self.password = password
        self.port = 22
        self.remote_dir = f"/home/{self.user}/Desktop/HeliCAL_Final"
        self.compile_cmd = (
            "g++ -std=c++17 -Wall -Wextra -pthread master_queue.cpp "
            "Esp32UART.cpp TicController.cpp HeliCalHelper.cpp LED.cpp "
            "DLPC900.cpp window_manager.cpp -I/usr/include/hidapi "
            "-lhidapi-hidraw -o master_queue"
        )
        self.launch_cmd = f"cd {self.remote_dir} && sudo -S ./master_queue"
        
        self._client = None
        self._sftp = None
        self._process_stdin = None
        self.command_queue = Queue()
        self._running = False

    def _log(self, message, level="INFO"):
        """Helper to emit log messages."""
        self.log_message.emit(message, level)

    def run(self):
        """
        The main startup sequence and command loop for the SSH worker.
        """
        self._running = True
        try:
            # 1. Connect
            self._client = paramiko.SSHClient()
            self._client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            self._log(f"Connecting to {self.user}@{self.host}...")
            self._client.connect(
                hostname=self.host, port=self.port, username=self.user,
                password=self.password, timeout=10
            )
            self.connection_status.emit(True)
            self._log("SSH connection established.", "SUCCESS")

            self._execute_shell_command(f"mkdir -p {self.remote_dir}")

            # 2. Compile (Complex Command)
            self._log("Compiling master_queue with full dependencies...")
            compile_output = self._execute_shell_command(f"cd {self.remote_dir} && {self.compile_cmd}")
            if "error:" in compile_output.lower():
                self._log(f"Compilation failed with output:\n{compile_output}", "ERROR")
                self.stop()
                return
            self._log("Compilation successful.")

            # 3. Launch master_queue
            self._log(f"Launching '{self.launch_cmd}' on the remote device...")
            channel = self._client.get_transport().open_session()
            channel.get_pty()
            channel.exec_command(self.launch_cmd)
            self._process_stdin = channel.makefile('wb')
            
            # Immediately write password for sudo
            self._process_stdin.write(self.password.encode('utf-8') + b'\n')
            self._process_stdin.flush()
            self._log("master_queue process launched.", "SUCCESS")

            # 4. Command Loop
            while self._running:
                try:
                    command_type, payload = self.command_queue.get(timeout=0.1)
                    self._process_command(command_type, payload)
                except Empty:
                    pass
                # In a real implementation, we would also read from stdout/stderr here.
                time.sleep(0.05)

        except paramiko.AuthenticationException:
            self._log("Authentication failed. Please check your credentials.", "ERROR")
        except Exception as e:
            self._log(f"An error occurred in SSH worker: {e}", "ERROR")
        finally:
            self.stop()
            
    def _process_command(self, command_type, payload):
        """Processes a single command from the queue."""
        if command_type == "GCODE":
            cmd_str = payload
            self._log(f"Sending GCODE: {cmd_str}", "GCODE")
            self._process_stdin.write(cmd_str.encode('utf-8') + b'\n')
            self._process_stdin.flush()
        
        elif command_type == "SHELL":
            cmd_str = payload
            self._log(f"Executing SHELL: {cmd_str}", "REMOTE")
            output = self._execute_shell_command(cmd_str)
            if output:
                self._log(f"SHELL output:\n{output}", "REMOTE")

        elif command_type == "UPLOAD":
            local_path, remote_path = payload
            self._log(f"Uploading '{local_path}' to '{remote_path}'")
            self._upload_file_sftp(local_path, remote_path)

    def _execute_shell_command(self, command):
        """Executes a one-off shell command and returns the output."""
        try:
            stdin, stdout, stderr = self._client.exec_command(command)
            # This handles commands that need sudo by piping the password.
            if 'sudo -S' in command:
                stdin.write(self.password.encode('utf-8') + b'\n')
                stdin.flush()
            
            out = stdout.read().decode('utf-8', errors='ignore').strip()
            err = stderr.read().decode('utf-8', errors='ignore').strip()
            if err:
                self._log(f"Error executing '{command}': {err}", "ERROR")
                return err
            return out
        except Exception as e:
            self._log(f"Failed to execute shell command '{command}': {e}", "ERROR")
            return str(e)

    def _upload_file_sftp(self, local_path, remote_path):
        """Uploads a file using SFTP."""
        if not self._sftp or self._sftp.sock.closed:
            self._sftp = self._client.open_sftp()

        try:
            # Auto-create directory
            remote_dir = "/".join(remote_path.split("/")[:-1])
            if remote_dir:
                self._sftp.mkdir(remote_dir)
        except Exception:
            pass # Directory likely exists

        def progress_callback(bytes_transferred, total_bytes):
            if total_bytes > 0:
                progress = int((bytes_transferred / total_bytes) * 100)
                self.upload_progress.emit(progress)

        try:
            self._sftp.put(local_path, remote_path, callback=progress_callback)
            self.upload_progress.emit(100)
            self._log(f"File uploaded to '{remote_path}'.", "SUCCESS")
            self.file_uploaded.emit(remote_path)
        except Exception as e:
            self._log(f"File upload failed: {e}", "ERROR")
            self.upload_progress.emit(0)

    # --- Public Methods to Queue Commands ---
    def send_gcode(self, cmd: str):
        self.command_queue.put(("GCODE", cmd))

    def send_shell(self, cmd: str):
        self.command_queue.put(("SHELL", cmd))

    def upload_file(self, local_path: str, remote_path: str):
        self.command_queue.put(("UPLOAD", (local_path, remote_path)))

    def play_remote_video(self, remote_path: str):
        """Queues the command sequence to play a video on the remote machine."""
        self._log("Queueing remote video playback sequence.", "INFO")
        safe_remote_path = shlex.quote(remote_path)
        
        commands = [
            'if DISPLAY=:0 xset q >/dev/null 2>&1; then echo "Display OK"; else echo "Display not ready"; fi',
            'pkill mpv >/dev/null 2>&1 || true',
            f'DISPLAY=:0 nohup mpv --fullscreen --loop=inf --video-rotate=180 --title=ProjectorVideo {safe_remote_path} >/dev/null 2>&1 &',
            'sleep 1 && DISPLAY=:0 xdotool search --name ProjectorVideo windowmove 1920 0',
            'DISPLAY=:0 xdotool search --name ProjectorVideo windowsize 2560 1600',
            'DISPLAY=:0 xdotool search --name ProjectorVideo windowactivate --sync key space'
        ]
        for cmd in commands:
            self.send_shell(cmd)
            
    def stop_remote_video(self):
        """Queues the command to stop video playback."""
        self._log("Queueing remote video stop.", "INFO")
        self.send_shell("pkill mpv >/dev/null 2>&1 || true")

    def shutdown_remote(self):
        """Queues the command to shut down the remote machine."""
        self._log("Shutting down remote machine...", "WARNING")
        # Use echo to pipe password to sudo for non-interactive shutdown
        cmd = f"echo {shlex.quote(self.password)} | sudo -S shutdown now"
        self.send_shell(cmd)
        
    def stop(self):
        """Stops the worker thread and cleans up resources."""
        if not self._running:
            return
        self._running = False
        if self._client:
            self._client.close()
        self.connection_status.emit(False)
        self._log("SSH connection closed.")
        self.finished.emit()
