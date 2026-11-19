"""Tests for the terminal runner behind `make chat` (spec 14 §3.12; AC-14.57).

Why: the runner must drive the interview exactly as the API does, and it is only trustworthy if it
runs in tests with a scripted model. What: three turns from injected stdin with a status line after
each reply, the commands `/confirm roles`, `/cluster FIN`, `/finish` and `/quit`, and a clean exit
on end of input. No live model is called.
"""

import importlib.util
import io
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[4]
SCRIPT = BACKEND / "tests" / "fixtures" / "transcripts" / "chat_fake.yaml"


def load_chat():
    spec = importlib.util.spec_from_file_location("chat_script", BACKEND / "scripts" / "chat.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_three_turns_and_the_commands():
    """AC-14.57."""
    chat = load_chat()
    out = io.StringIO()
    stdin = io.StringIO(
        "Finance\n/confirm roles\nI'm a cost controller\n/cluster FIN\n/finish\nEurope\n/quit\nnever read\n"
    )
    assert chat.main(["--fake", str(SCRIPT)], stdin=stdin, out=out) == 0
    text = out.getvalue()
    replies = [line for line in text.splitlines() if line.startswith("agent> ")]
    assert len(replies) == 4  # the welcome and three turns
    assert replies[1] == "agent> What is your own role in Finance?"
    status = [line for line in text.splitlines() if line.startswith("phase=")]
    assert len(status) == 1 + 3 + 3  # welcome, three turns, three commands
    assert "confirmed roles" in text and "cluster set to FIN" in text
    assert "ready=False blocked_by=below_gate" in text
    assert "phase=find" in status[-1]


def test_end_of_input_exits_cleanly():
    """AC-14.57."""
    chat = load_chat()
    out = io.StringIO()
    assert chat.main(["--fake", str(SCRIPT)], stdin=io.StringIO("Finance\n"), out=out) == 0
    assert out.getvalue().count("agent> ") == 2
