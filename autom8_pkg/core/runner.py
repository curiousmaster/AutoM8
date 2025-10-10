# =====================================================================
# File: autom8_pkg/core/runner.py
# Subprocess runner that streams Ansible output line-by-line
# Supports colors (PTY) and optional --vault-password-file
# =====================================================================
from __future__ import annotations
import os
import pty
import subprocess
import threading
from queue import Queue, Empty
from typing import Iterable, List, Optional


def _reader(fd: int, q: Queue):
    try:
        with os.fdopen(fd, "rb", buffering=0, closefd=True) as f:
            while True:
                try:
                    chunk = f.read(4096)
                    if not chunk:
                        break
                    q.put(chunk)
                except OSError:
                    # Common when the PTY slave closes: EIO on master read.
                    break
    finally:
        q.put(None)  # EOF sentinel


class LiveRunner:
    """
    Run a command in a PTY and stream combined stdout/stderr as bytes.
    Intended for Ansible so color codes are preserved.
    """

    def __init__(self, cmd: List[str], env: Optional[dict] = None, cwd: Optional[str] = None):
        self.cmd = cmd
        self.env = env or os.environ.copy()
        self.cwd = cwd
        self.process: Optional[subprocess.Popen] = None
        self.queue: Queue = Queue()

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.wait()

    def start(self):
        master_fd, slave_fd = pty.openpty()
        self.process = subprocess.Popen(
            self.cmd,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            env=self.env,
            cwd=self.cwd,
            close_fds=True,
            text=False,
        )
        os.close(slave_fd)
        t = threading.Thread(target=_reader, args=(master_fd, self.queue), daemon=True)
        t.start()

    def stream(self) -> Iterable[bytes]:
        while True:
            try:
                item = self.queue.get(timeout=0.05)
            except Empty:
                if self.process and self.process.poll() is not None:
                    # Drain any remaining output
                    while not self.queue.empty():
                        item = self.queue.get_nowait()
                        if item is None:
                            return
                        yield item
                    return
                continue
            if item is None:
                return
            yield item

    def wait(self) -> int:
        if self.process is None:
            return 0
        return self.process.wait()


def build_ansible_cmd(
    playbook_path: str,
    inventory: str,
    hosts: Optional[List[str]] = None,
    ask_vault: bool = False,
    vault_password_file: Optional[str] = None,
    extra_env: Optional[dict] = None,
) -> List[str]:
    """
    Construct ansible-playbook command.
    - If vault_password_file is provided, uses --vault-password-file.
    - Else if ask_vault is True, uses --ask-vault-pass.
    """
    cmd = [
        "ansible-playbook",
        "-i", inventory,
        playbook_path,
    ]
    if hosts:
        cmd += ["--limit", ",".join(hosts)]
    if vault_password_file:
        cmd += ["--vault-password-file", vault_password_file]
    elif ask_vault:
        cmd.append("--ask-vault-pass")
    if extra_env:
        os.environ.update(extra_env)
    return cmd

