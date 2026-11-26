"""Record each container's CPU cores and memory every second from cgroup v2.

Usage: python3 resource_monitor.py <container-name-prefix> <output.jsonl>
Each line: {"t": epoch, "host_busy_cores": n, "<container>": [cores, mem_gib, rx_mbps, tx_mbps], ...}
網路是容器 network namespace 的總收發（/proc/<pid>/net/dev，不含 lo），單位 Mbit/s。
另有整台主機的 "host"：記憶體已用 GiB、實體網卡收發 Mbit/s、磁碟讀寫 MB/s、1 分鐘負載，
以及每張 GPU 的使用率與顯存（nvidia-smi，每 2 秒一次）。
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


def container_pid(cid):
    result = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Pid}}", cid],
        capture_output=True, text=True, check=False,
    )
    try:
        return int(result.stdout.strip())
    except ValueError:
        return 0


def read_net(pid):
    """Bytes received and sent by the container's interfaces, loopback excluded."""
    if not pid:
        return None
    try:
        with open(f"/proc/{pid}/net/dev") as fh:
            lines = fh.readlines()[2:]
    except OSError:
        return None
    rx = tx = 0
    for line in lines:
        name, data = line.split(":", 1)
        if name.strip() == "lo":
            continue
        fields = data.split()
        rx += int(fields[0])
        tx += int(fields[8])
    return rx, tx


PHYSICAL_NIC_PREFIXES = ("en", "eth", "wl")


def host_net():
    rx = tx = 0
    with open("/proc/net/dev") as fh:
        for line in fh.readlines()[2:]:
            name, data = line.split(":", 1)
            if name.strip().startswith(PHYSICAL_NIC_PREFIXES):
                fields = data.split()
                rx += int(fields[0])
                tx += int(fields[8])
    return rx, tx


def host_disk():
    """Sectors read and written on whole physical disks (512-byte sectors)."""
    read = written = 0
    with open("/proc/diskstats") as fh:
        for line in fh:
            fields = line.split()
            name = fields[2]
            if name.startswith(("loop", "ram", "dm-", "sr")) or name[-1].isdigit() and not name.startswith("nvme"):
                continue
            if name.startswith("nvme") and "p" in name[4:]:
                continue
            read += int(fields[5])
            written += int(fields[9])
    return read, written


def host_memory_gib():
    info = {}
    with open("/proc/meminfo") as fh:
        for line in fh:
            key, value = line.split(":", 1)
            info[key] = int(value.split()[0])
    return round((info["MemTotal"] - info["MemAvailable"]) / 2**20, 2)


def gpus():
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=index,utilization.gpu,memory.used",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, check=False, timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        # 沒有 NVIDIA 工具的主機照樣記其他資源，GPU 欄位留空。
        return {}
    rows = {}
    for line in result.stdout.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) == 3:
            rows[f"gpu{parts[0]}"] = [float(parts[1]), round(float(parts[2]) / 1024, 2)]
    return rows


def host_io_pressure():
    """Cumulative microseconds some / all tasks waited on I/O (PSI); None without PSI."""
    try:
        with open("/proc/pressure/io") as fh:
            totals = [int(line.rsplit("total=", 1)[1]) for line in fh if "total=" in line]
        return totals[0], totals[1]
    except (OSError, IndexError, ValueError):
        return None


def host_ticks():
    with open("/proc/stat") as fh:
        values = list(map(int, fh.readline().split()[1:]))
    return sum(values), values[3] + values[4]


def main():
    prefix, path = sys.argv[1], sys.argv[2]
    cores = os.cpu_count() or 1
    previous, prev_host = {}, host_ticks()
    names, refreshed = containers(prefix), time.time()
    pids = {cid: container_pid(cid) for cid in names.values()}
    prev_net, prev_disk, last_gpu, gpu_rows = host_net(), host_disk(), 0.0, {}
    prev_io = host_io_pressure()
    with open(path, "a", encoding="utf-8") as out:
        while True:
            time.sleep(1)
            # 壓測途中會起停 client 容器，定期重抓名單。
            if time.time() - refreshed > 10:
                names, refreshed = containers(prefix), time.time()
                pids = {cid: pids.get(cid) or container_pid(cid) for cid in names.values()}
            now = time.time()
            total, idle = host_ticks()
            delta = total - prev_host[0]
            row = {"t": now, "host_busy_cores": round((delta - (idle - prev_host[1])) / delta * cores, 2) if delta else 0.0}
            prev_host = (total, idle)
            net, disk = host_net(), host_disk()
            row["host"] = {
                "mem_gib": host_memory_gib(),
                "rx_mbps": round((net[0] - prev_net[0]) * 8 / 1e6, 2),
                "tx_mbps": round((net[1] - prev_net[1]) * 8 / 1e6, 2),
                "disk_read_mbs": round((disk[0] - prev_disk[0]) * 512 / 1e6, 2),
                "disk_write_mbs": round((disk[1] - prev_disk[1]) * 512 / 1e6, 2),
                "load1": os.getloadavg()[0],
            }
            # 這一秒內有程序／全部程序在等磁碟各幾毫秒：對得上單次卡頓，10 秒平均對不上。
            io = host_io_pressure()
            if io and prev_io:
                row["host"]["io_some_ms"] = round((io[0] - prev_io[0]) / 1000)
                row["host"]["io_full_ms"] = round((io[1] - prev_io[1]) / 1000)
            prev_net, prev_disk, prev_io = net, disk, io
            # nvidia-smi 本身要 0.1～0.3 秒，隔一秒才叫一次，結果沿用到下一筆。
            if now - last_gpu >= 2:
                gpu_rows, last_gpu = gpus(), now
            row.update(gpu_rows)
            for name, cid in names.items():
                sample = read_cgroup(cid)
                if sample is None:
                    continue
                net = read_net(pids.get(cid)) or (0, 0)
                if cid in previous:
                    usage, _, at, prev_cnet = previous[cid]
                    span = now - at
                    row[name] = [
                        round((sample[0] - usage) / 1e6 / span, 2),
                        round(sample[1] / 2**30, 2),
                        round((net[0] - prev_cnet[0]) * 8 / 1e6 / span, 2),
                        round((net[1] - prev_cnet[1]) * 8 / 1e6 / span, 2),
                    ]
                previous[cid] = (sample[0], sample[1], now, net)
            out.write(json.dumps(row) + "\n")
            out.flush()


if __name__ == "__main__":
    main()
