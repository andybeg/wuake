import os
import subprocess
import sys


SENTINEL = "__WUAKE__END__"


def main() -> int:
    ps = os.environ.get("WUAKE_POWERSHELL", "powershell.exe")

    # Important: `powershell -Command -` often buffers stdin until EOF.
    # We instead run a small PS loop that reads one line at a time and executes it.
    ps_loop = rf"""
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

    proc = subprocess.Popen(
        [
            ps,
            "-NoLogo",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-NoExit",
            "-Command",
            ps_loop,
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )

    assert proc.stdin is not None
    assert proc.stdout is not None

    def send(script: str) -> None:
        proc.stdin.write(script)
        proc.stdin.flush()

    while True:
        try:
            cmd = input("ps> ")
        except EOFError:
            cmd = "exit"
        except KeyboardInterrupt:
            sys.stdout.write("\n")
            sys.stdout.flush()
            continue

        if not cmd.strip():
            continue

        if cmd.strip().lower() in {"exit", "quit"}:
            break

        send(cmd + "\n")

        while True:
            line = proc.stdout.readline()
            if line == "":
                return proc.returncode or 0
            if line.rstrip("\r\n") == SENTINEL:
                break
            sys.stdout.write(line)
            sys.stdout.flush()

    try:
        send("exit\n")
        proc.stdin.close()
    except Exception:
        pass

    try:
        proc.wait(timeout=2)
    except Exception:
        try:
            proc.terminate()
        except Exception:
            pass

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

