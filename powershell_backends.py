import base64
import subprocess
from abc import ABC, abstractmethod
from typing import Any


SENTINEL = "__WUAKE__END__"


def make_ps_loop() -> str:
    # Read one line, run it, print sentinel to mark end.
    return rf"""
$ErrorActionPreference = 'Continue'
function prompt {{ '' }}
while ($true) {{
  $line = [Console]::In.ReadLine()
  if ($null -eq $line) {{ break }}
  if ([string]::IsNullOrWhiteSpace($line)) {{ Write-Output '{SENTINEL}'; continue }}
  try {{
    Invoke-Expression $line
  }} catch {{
    $_ | Out-String | Write-Output
  }}
  Write-Output '{SENTINEL}'
}}
exit
"""


def encode_ps_script(script: str) -> str:
    raw = script.encode("utf-16-le")
    return base64.b64encode(raw).decode("ascii")


class PowerShellBackend(ABC):
    @abstractmethod
    def start(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def stop(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def run_command(self, cmd: str) -> list[str]:
        raise NotImplementedError


class SubprocessPowerShellBackend(PowerShellBackend):
    def __init__(self, ps_exe: str):
        self.ps_exe = ps_exe
        self.proc: subprocess.Popen[str] | None = None

    def start(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            return
        encoded = encode_ps_script(make_ps_loop())
        self.proc = subprocess.Popen(
            [
                self.ps_exe,
                "-NoLogo",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-NoExit",
                "-EncodedCommand",
                encoded,
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )

    def stop(self) -> None:
        if not self.proc:
            return
        try:
            if self.proc.stdin:
                self.proc.stdin.write("exit\n")
                self.proc.stdin.flush()
                self.proc.stdin.close()
        except Exception:
            pass
        try:
            self.proc.terminate()
        except Exception:
            pass

    def run_command(self, cmd: str) -> list[str]:
        self.start()
        assert self.proc is not None
        assert self.proc.stdin is not None
        assert self.proc.stdout is not None

        self.proc.stdin.write(cmd + "\n")
        self.proc.stdin.flush()

        out_lines: list[str] = []
        while True:
            line = self.proc.stdout.readline()
            if line == "":
                break
            s = line.rstrip("\r\n")
            if s == SENTINEL:
                break
            out_lines.append(s)
        return out_lines


class SshPowerShellBackend(PowerShellBackend):
    def __init__(
        self,
        host: str,
        user: str = "",
        port: int = 22,
        remote_shell: str = "pwsh",
        ssh_binary: str = "ssh",
    ):
        self.host = host
        self.user = user
        self.port = port
        self.remote_shell = remote_shell
        self.ssh_binary = ssh_binary
        self.proc: subprocess.Popen[str] | None = None

    def _target(self) -> str:
        if self.user.strip():
            return f"{self.user}@{self.host}"
        return self.host

    def start(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            return
        if not self.host.strip():
            raise RuntimeError("SSH backend: host is empty in runner settings.")
        encoded = encode_ps_script(make_ps_loop())
        self.proc = subprocess.Popen(
            [
                self.ssh_binary,
                "-p",
                str(self.port),
                self._target(),
                self.remote_shell,
                "-NoLogo",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-NoExit",
                "-EncodedCommand",
                encoded,
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )

    def stop(self) -> None:
        if not self.proc:
            return
        try:
            if self.proc.stdin:
                self.proc.stdin.write("exit\n")
                self.proc.stdin.flush()
                self.proc.stdin.close()
        except Exception:
            pass
        try:
            self.proc.terminate()
        except Exception:
            pass

    def run_command(self, cmd: str) -> list[str]:
        self.start()
        assert self.proc is not None
        assert self.proc.stdin is not None
        assert self.proc.stdout is not None

        self.proc.stdin.write(cmd + "\n")
        self.proc.stdin.flush()

        out_lines: list[str] = []
        while True:
            line = self.proc.stdout.readline()
            if line == "":
                break
            s = line.rstrip("\r\n")
            if s == SENTINEL:
                break
            out_lines.append(s)
        return out_lines


class DotNetPowerShellBackend(PowerShellBackend):
    def __init__(self):
        self._ps = None
        self._runspace = None

    def start(self) -> None:
        if self._ps is not None and self._runspace is not None:
            return
        try:
            import clr  # type: ignore

            clr.AddReference("System.Management.Automation")
            from System.Management.Automation import PowerShell  # type: ignore
            from System.Management.Automation.Runspaces import RunspaceFactory  # type: ignore
        except Exception as exc:
            raise RuntimeError(
                "DotNet backend requires pythonnet and System.Management.Automation."
            ) from exc

        self._runspace = RunspaceFactory.CreateRunspace()
        self._runspace.Open()
        self._ps = PowerShell.Create()
        self._ps.Runspace = self._runspace

    def stop(self) -> None:
        if self._ps is not None:
            try:
                self._ps.Dispose()
            except Exception:
                pass
        if self._runspace is not None:
            try:
                self._runspace.Close()
                self._runspace.Dispose()
            except Exception:
                pass
        self._ps = None
        self._runspace = None

    def run_command(self, cmd: str) -> list[str]:
        self.start()
        assert self._ps is not None

        self._ps.Commands.Clear()
        self._ps.AddScript(cmd)
        result = self._ps.Invoke()
        output = [str(item) for item in result]

        err_stream = self._ps.Streams.Error
        if err_stream is not None and err_stream.Count > 0:
            output.extend(str(item) for item in err_stream)
            err_stream.Clear()
        return output


def create_backend(config: dict[str, Any]) -> PowerShellBackend:
    mode = str(config.get("mode", "subprocess")).strip().lower()
    if mode == "subprocess":
        ps_exe = str(config.get("powershell_exe", "powershell.exe"))
        return SubprocessPowerShellBackend(ps_exe=ps_exe)
    if mode == "dotnet":
        return DotNetPowerShellBackend()
    if mode == "ssh":
        ssh_cfg = config.get("ssh", {})
        if not isinstance(ssh_cfg, dict):
            ssh_cfg = {}
        return SshPowerShellBackend(
            host=str(ssh_cfg.get("host", "")),
            user=str(ssh_cfg.get("user", "")),
            port=int(ssh_cfg.get("port", 22)),
            remote_shell=str(ssh_cfg.get("remote_shell", "pwsh")),
            ssh_binary=str(ssh_cfg.get("ssh_binary", "ssh")),
        )
    raise ValueError(f"Unknown backend mode: {mode}")
