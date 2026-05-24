import subprocess
import sys
import time

import pytest

from qecc_sat.subprocess_utils import isolate_process_session, kill_process_tree


@pytest.mark.skipif(sys.platform == "win32", reason="setsid/killpg not on Windows")
def test_kill_process_tree_terminates_child():
    isolate_process_session()
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(3600)"],
    )
    try:
        time.sleep(0.2)
        assert proc.poll() is None
        kill_process_tree(proc.pid, grace_sec=0.5)
        proc.wait(timeout=5)
        assert proc.returncode is not None
    finally:
        if proc.poll() is None:
            kill_process_tree(proc.pid, grace_sec=0)
