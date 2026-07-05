"""
Helper condiviso per l'esecuzione sicura di comandi di sistema.
Sempre invocato con liste di argomenti (mai shell=True), input sensibili
(password) passati via STDIN.
"""
import subprocess


class SystemCommandError(Exception):
    """Sollevata quando un comando di sistema fallisce (contiene lo stderr)."""


def run_command(cmd: list[str], input_text: str | None = None) -> str:
    try:
        result = subprocess.run(
            cmd,
            input=input_text,
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        return result.stdout
    except subprocess.CalledProcessError as exc:
        raise SystemCommandError(exc.stderr.strip() or str(exc)) from exc
    except subprocess.TimeoutExpired as exc:
        raise SystemCommandError(f"Timeout eseguendo: {' '.join(cmd)}") from exc
