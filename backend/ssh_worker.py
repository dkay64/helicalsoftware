
import time
from queue import Queue, Empty
import paramiko
from PyQt5.QtCore import QThread, pyqtSignal
import re
import shlex

class SSHWorker(QThread):
    """
    Background worker that connects over SSH, compiles and runs the master_queue,
    and streams commands/logs.
    """
    log_message = pyqtSignal(str, str)  # Message, Level
    connection_status = pyqtSignal(bool)  # True (Connected) / False (Disconnected)
    upload_progress = pyqtSignal(int)  # 0-100 for file transfers

    def __init__(self, host="192.168.0.123", user="jetson", password=""):
        super().__init__()
        self.host = host
        self.user = user
        self.password = password
        self.port = 22
        self.remote_dir = f"/home/{self.user}/helical" 
        self.compile_cmd = "g++ -std=c++17 -Wall -Wextra -pthread master_queue.cpp -o master_queue"
        self.launch_cmd = "sudo -S ./master_queue"
        
        self._client = None
        self._sftp = None
        self._channel = None
        self._process_stdin = None
        self._process_stdout = None
        self._process_stderr = None
        
        self.command_queue = Queue()
        self._running = False
        self.pid = None

    def _log(self, message, level="INFO"):
        self.log_message.emit(message, level)

    def run(self):
        """
        The main startup sequence for the SSH worker thread.
        Connects, compiles, and launches the remote process, then enters the command loop.
        """
        self._running = True
        try:
            # 1. Connect
            self._client = paramiko.SSHClient()
            self._client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            self._log(f"Connecting to {self.user}@{self.host}...")
            self._client.connect(
                hostname=self.host,
                port=self.port,
                username=self.user,
                password=self.password,
                timeout=10
            )
            self.connection_status.emit(True)
            self._log("SSH connection established.", "SUCCESS")

            # Create remote directory if it doesn't exist
            self._execute_shell_command(f"mkdir -p {self.remote_dir}")

            # 2. Compile
            self._log("Compiling master_queue on the remote device...")
            compile_output = self._execute_shell_command(f"cd {self.remote_dir} && {self.compile_cmd}")
            if compile_output:
                self._log(f"Compilation output:\n{compile_output}")
            
            # Check if compilation was successful by checking for the executable
            ls_output = self._execute_shell_command(f"ls {self.remote_dir}/master_queue")
            if "master_queue" not in ls_output:
                 self._log("Compilation failed. 'master_queue' not found.", "ERROR")
                 self.stop()
                 return
            self._log("Compilation successful.")


            # 3. Launch
            self._log(f"Launching '{self.launch_cmd}' on the remote device...")
            self._channel = self._client.get_transport().open_session()
            self._channel.get_pty()
            self._channel.exec_command(f"cd {self.remote_dir} && {self.launch_cmd} & echo $!")
            
            self._process_stdin = self._channel.makefile('wb')
            self._process_stdout = self._channel.makefile('r')
            self._process_stderr = self._channel.makefile('r')

            # Get the PID
            self.pid = self._process_stdout.readline().strip()
            if not self.pid.isdigit():
                self._log("Failed to get PID of remote process.", "ERROR")
                self.stop()
                return
            self._log(f"master_queue process started with PID: {self.pid}")

            # Wait for the sudo prompt and then write the password
            prompt_found = False
            while not prompt_found:
                if self._channel.recv_stderr_ready():
                    line = self._process_stderr.readline()
                    if "[sudo] password for" in line:
                        prompt_found = True
                if not prompt_found:
                    time.sleep(0.1)

            self._process_stdin.write(self.password.encode('utf-8') + b'\n')
            self._process_stdin.flush()
            
            self._log("master_queue process launched.", "SUCCESS")

            # 4. Loop
            while self._running:
                # Check for new commands
                try:
                    command_type, payload = self.command_queue.get_nowait()
                    self._process_command(command_type, payload)
                except Empty:
                    pass

                # Read stdout from the process
                self._read_process_output()
                time.sleep(0.1) # Prevent busy-waiting

        except paramiko.AuthenticationException:
            self._log("Authentication failed. Please check your credentials.", "ERROR")
        except Exception as e:
            self._log(f"An error occurred: {e}", "ERROR")
        finally:
            self.stop()

    def _process_command(self, command_type, payload):
        """Processes a command from the command queue."""
        if command_type == "GCODE":
            self._log(f"Sending GCODE: {payload}")
            self._process_stdin.write(payload.encode('utf-8') + b'\n')
            self._process_stdin.flush()
        elif command_type == "SHELL":
            self._log(f"Executing SHELL: {payload}")
            output = self._execute_shell_command(payload)
            self._log(f"SHELL output:\n{output}")
        elif command_type == "UPLOAD":
            local_path, remote_path = payload
            self._log(f"Uploading '{local_path}' to '{remote_path}'")
            self._upload_file_sftp(local_path, remote_path)

import shlex
...
    def _execute_shell_command(self, command):
        """Executes a one-off shell command."""
        try:
            stdin, stdout, stderr = self._client.exec_command(command)
            # Note: shlex.split() may not work correctly with unicode characters.
            parts = shlex.split(command)
            if 'sudo' in parts and '-S' in parts:
                stdin.write(self.password + '\n')
                stdin.flush()
            
            out = stdout.read().decode('utf-8')
            err = stderr.read().decode('utf-8')
            if err:
                self._log(f"Error executing '{command}': {err}", "ERROR")
                return err
            return out
        except Exception as e:
            self._log(f"Failed to execute shell command '{command}': {e}", "ERROR")
            return str(e)

    def _read_process_output(self):
        """Reads and logs output from the running master_queue process."""
        try:
            if self._channel.recv_ready():
                data = self._channel.recv(4096).decode('utf-8')
                for line in data.splitlines():
                    self._log(f"[master_queue] {line.strip()}", "REMOTE")
            
            if self._channel.recv_stderr_ready():
                 data = self._channel.recv_stderr(4096).decode('utf-8')
                 for line in data.splitlines():
                    self._log(f"[master_queue] {line.strip()}", "ERROR")

        except Exception as e:
            if self._running:
                self._log(f"Error reading process output: {e}", "ERROR")

    def _upload_file_sftp(self, local_path, remote_path):
        """Uploads a file using SFTP."""
        if not self._sftp:
            try:
                self._sftp = self._client.open_sftp()
            except Exception as e:
                self._log(f"Failed to open SFTP session: {e}", "ERROR")
                return

        try:
            remote_dir = "/".join(remote_path.split("/")[:-1])
            if remote_dir:
                if remote_dir.startswith('/'):
                    # Absolute path
                    dirs = remote_dir.split('/')[1:]
                    current_dir = ''
                else:
                    # Relative path
                    dirs = remote_dir.split('/')
                    current_dir = ''
                
                for part in dirs:
                    if not part:
                        continue
                    current_dir += f'/{part}' if current_dir else part
                    try:
                        self._sftp.stat(current_dir)
                    except FileNotFoundError:
                        self._sftp.mkdir(current_dir)

            def progress_callback(bytes_transferred, total_bytes):
                if total_bytes > 0:
                    progress = int((bytes_transferred / total_bytes) * 100)
                    self.upload_progress.emit(progress)

            self._sftp.put(local_path, remote_path, callback=progress_callback)
            self.upload_progress.emit(100)
            self._log(f"File '{local_path}' uploaded successfully to '{remote_path}'.", "SUCCESS")
        except Exception as e:
            self._log(f"File upload failed: {e}", "ERROR")
            self.upload_progress.emit(0)

    def send_gcode(self, cmd: str):
        """Adds a GCODE command to the queue."""
        self.command_queue.put(("GCODE", cmd))

    def send_shell(self, cmd: str):
        """Adds a SHELL command to the queue."""
        self.command_queue.put(("SHELL", cmd))

    def upload_file(self, local: str, remote: str):
        """Adds a file upload command to the queue."""
        self.command_queue.put(("UPLOAD", (local, remote)))

    def stop(self):
        """Stops the worker thread and cleans up resources."""
        if not self._running:
            return
            
        self._running = False
        self._log("Stopping SSH worker...")
        
        if self.pid:
            try:
                self._execute_shell_command(f"kill -9 -{self.pid}")
            except:
                pass 
                
        if self._sftp:
            self._sftp.close()
        if self._client:
            self._client.close()

        self.connection_status.emit(False)
        self._log("SSH connection closed.", "INFO")
        self.finished.emit()
