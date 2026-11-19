"""Record each container's CPU cores and memory every second from cgroup v2.

Usage: python3 resource_monitor.py <container-name-prefix> <output.jsonl>
Each line: {"t": epoch, "host_busy_cores": n, "<container>": [cores, mem_gib], ...}
"""

import json
import os
import subprocess
import sys
import time


def containers(prefix):
    result = subprocess.run(
        ["docker", "ps", "--no-trunc", "--format", "{{.ID}} {{.Names}}"],
        capture_output=True, text=True, check=False,
    )
    pairs = (line.split() for line in result.stdout.splitlines())
    return {name: cid for cid, name in pairs if name.startswith(prefix)}


def read_cgroup(cid):
    base = f"/sys/fs/cgroup/system.slice/docker-{cid}.scope"
    try:
        with open(f"{base}/cpu.stat") as fh:
            usage = next(int(line.split()[1]) for line in fh if line.startswith("usage_usec"))
        with open(f"{base}/memory.current") as fh:
            memory = int(fh.read())
    except OSError:
        return None
    return usage, memory


def host_ticks():
    with open("/proc/stat") as fh:
        values = list(map(int, fh.readline().split()[1:]))
    return sum(values), values[3] + values[4]


def main():
    prefix, path = sys.argv[1], sys.argv[2]
    cores = os.cpu_count() or 1
    previous, prev_host = {}, host_ticks()
    names, refreshed = containers(prefix), time.time()
    with open(path, "a", encoding="utf-8") as out:
        while True:
            time.sleep(1)
            # 壓測途中會起停 client 容器，定期重抓名單。
            if time.time() - refreshed > 10:
                names, refreshed = containers(prefix), time.time()
            now = time.time()
            total, idle = host_ticks()
            delta = total - prev_host[0]
            row = {"t": now, "host_busy_cores": round((delta - (idle - prev_host[1])) / delta * cores, 2) if delta else 0.0}
            prev_host = (total, idle)
            for name, cid in names.items():
                sample = read_cgroup(cid)
                if sample is None:
                    continue
                if cid in previous:
                    usage, _, at = previous[cid]
                    row[name] = [round((sample[0] - usage) / 1e6 / (now - at), 2), round(sample[1] / 2**30, 2)]
                previous[cid] = (sample[0], sample[1], now)
            out.write(json.dumps(row) + "\n")
            out.flush()


if __name__ == "__main__":
    main()
