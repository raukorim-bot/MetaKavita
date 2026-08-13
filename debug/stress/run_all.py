"""
Enchaîne les six scénarios de stress, en séquence.

En séquence et non en parallèle : les mesures de latence et de débit seraient
faussées par la contention entre scénarios (tous sont liés au disque). Compter
une trentaine de minutes.

Relance :
    python debug/stress/run_all.py
    python debug/stress/run_all.py s2 s4      # seulement ces scénarios
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = [
    "s1_volume_pass_scale.py",
    "s2_cancel_resume.py",
    "s3_concurrency.py",
    "s4_sqlite_load.py",
    "s5_providers_degraded.py",
    "s6_leaks.py",
    "s7_eventlet_blocking.py",
]


def main():
    wanted = [arg for arg in sys.argv[1:] if not arg.startswith("-")]
    scripts = [s for s in SCRIPTS if not wanted or any(w in s for w in wanted)]
    results = []
    for script in scripts:
        print(f"\n########## {script} ##########", flush=True)
        start = time.time()
        code = subprocess.call([sys.executable, os.path.join(HERE, script)])
        results.append((script, code, round(time.time() - start, 1)))
    print("\n########## résumé ##########", flush=True)
    for script, code, elapsed in results:
        print(f"{script:32s} code={code} {elapsed}s", flush=True)


if __name__ == "__main__":
    main()
