#!/usr/bin/env python3
"""Ejecuta cinco configuraciones retadoras y consolida sus metricas."""

import argparse
import csv
import math
import os
import re
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "server" / "build" / "install" / "server" / "bin" / "server"
WORKER = ROOT / "worker" / "build" / "install" / "worker" / "bin" / "worker"
CLIENT = ROOT / "client" / "build" / "install" / "client" / "bin" / "client"
LOGS = ROOT / "results" / "logs"
IMG = ROOT / "results" / "img"
DATA = ROOT / "results" / "data"
RAW = ROOT / "results" / "raw"

CONFIGS = [
    {
        "id": "r1_ultrafino",
        "nombre": "R1 - Grano ultrafino con 4 workers",
        "preset": "seahorse",
        "width": 3840,
        "height": 2160,
        "max_iter": 5000,
        "strategy": 1,
        "param": 24,
        "workers": 4,
        "threads": 4,
        "ref": "reference_seahorse_4k_5000.bin",
    },
    {
        "id": "r2_ultragrueso",
        "nombre": "R2 - Grano ultragrueso con un solo hilo",
        "preset": "seahorse",
        "width": 3840,
        "height": 2160,
        "max_iter": 5000,
        "strategy": 1,
        "param": 512,
        "workers": 1,
        "threads": 1,
        "ref": "reference_seahorse_4k_5000.bin",
    },
    {
        "id": "r3_pool128",
        "nombre": "R3 - Sobredimensionamiento de 128 hilos",
        "preset": "seahorse",
        "width": 3840,
        "height": 2160,
        "max_iter": 5000,
        "strategy": 1,
        "param": 32,
        "workers": 1,
        "threads": 128,
        "ref": "reference_seahorse_4k_5000.bin",
    },
    {
        "id": "r4_4w8h",
        "nombre": "R4 - Cuatro workers con 8 hilos cada uno",
        "preset": "seahorse",
        "width": 3840,
        "height": 2160,
        "max_iter": 5000,
        "strategy": 1,
        "param": 64,
        "workers": 4,
        "threads": 8,
        "ref": "reference_seahorse_4k_5000.bin",
    },
    {
        "id": "r5_classic_fino",
        "nombre": "R5 - Vista macro con grano ultrafino",
        "preset": "classic",
        "width": 3840,
        "height": 2160,
        "max_iter": 5000,
        "strategy": 1,
        "param": 16,
        "workers": 4,
        "threads": 4,
        "ref": "reference_classic_4k_5000.bin",
    },
]

FIELDS = [
    "id",
    "configuracion",
    "preset",
    "width",
    "height",
    "max_iter",
    "estrategia",
    "parametro",
    "tareas",
    "workers",
    "hilos_por_worker",
    "hilos_totales",
    "t_sec_ms",
    "t_dist_ms",
    "latencia_min",
    "speedup",
    "eficiencia_pct",
    "validacion",
    "latencia_1_10",
    "log_cliente",
    "png",
]


def wait_port(port, timeout=45):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.2)
    return False


def wait_log(path, pattern, timeout=60):
    regex = re.compile(pattern)
    deadline = time.time() + timeout
    while time.time() < deadline:
        if path.exists():
            if regex.search(path.read_text(errors="ignore")):
                return True
        time.sleep(0.2)
    return False


def start_process(cmd, log_path, java_opts):
    env = os.environ.copy()
    env["JAVA_OPTS"] = java_opts
    log = log_path.open("w")
    proc = subprocess.Popen(
        cmd,
        cwd=ROOT,
        stdout=log,
        stderr=subprocess.STDOUT,
        env=env,
        start_new_session=True,
    )
    return proc, log


def stop_process(proc, log):
    if proc is not None and proc.poll() is None:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait(timeout=5)
    if log is not None:
        log.close()


def run_client(cmd, log_path, timeout):
    log = log_path.open("w")
    proc = subprocess.Popen(
        cmd,
        cwd=ROOT,
        stdout=log,
        stderr=subprocess.STDOUT,
        env=os.environ.copy(),
        start_new_session=True,
    )
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait(timeout=5)
        log.close()
        return False
    log.close()
    return proc.returncode == 0


def parse_int(text, pattern):
    match = re.search(pattern, text)
    return int(match.group(1)) if match else None


def run_config(cfg, suite_index):
    cid = cfg["id"]
    master_port = 10000
    base_worker_port = 10101 + suite_index * 10
    master_log = LOGS / f"challenge_{cid}_master.log"
    client_log = LOGS / f"challenge_{cid}_client.log"
    png_path = IMG / f"challenge_{cid}.png"
    ref_path = RAW / cfg["ref"]

    for port in [master_port] + [base_worker_port + i for i in range(cfg["workers"])]:
        if wait_port(port, timeout=0.3):
            raise RuntimeError(f"El puerto {port} ya esta ocupado")

    if not ref_path.is_file():
        raise FileNotFoundError(f"No existe la matriz de referencia {ref_path}")

    print(f"[SUITE] {cfg['nombre']} ({cid})", flush=True)
    print(
        f"[SUITE] {cfg['workers']} worker(s), {cfg['threads']} hilo(s)/worker, "
        f"tile {cfg['param']}x{cfg['param']}, preset {cfg['preset']}",
        flush=True,
    )

    master_proc = None
    master_handle = None
    workers = []

    try:
        master_proc, master_handle = start_process(
            [str(SERVER), str(master_port)], master_log, "-Xms32m -Xmx512m"
        )
        if not wait_port(master_port):
            raise RuntimeError("El Maestro no abrio el puerto")
        if not wait_log(master_log, r"NODO MAESTRO \(MASTER\) INICIADO", timeout=30):
            raise RuntimeError("El Maestro no confirmo su inicio")

        for i in range(cfg["workers"]):
            worker_port = base_worker_port + i
            worker_log = LOGS / f"challenge_{cid}_w{i + 1}.log"
            worker_cmd = [
                str(WORKER),
                str(worker_port),
                f"Worker-{i + 1}",
                "localhost",
                str(master_port),
                str(cfg["threads"]),
            ]
            proc, handle = start_process(worker_cmd, worker_log, "-Xms32m -Xmx256m")
            workers.append((proc, handle, worker_log))
            if not wait_log(worker_log, r"NODO TRABAJADOR \(WORKER\) ACTIVO", timeout=30):
                raise RuntimeError(f"Worker-{i + 1} no confirmo su inicio")

        if not wait_log(
            master_log,
            rf"Total activos: {cfg['workers']}\b",
            timeout=60,
        ):
            raise RuntimeError("El Maestro no registro todos los workers")

        client_cmd = [
            str(CLIENT),
            "localhost",
            str(master_port),
            str(cfg["width"]),
            str(cfg["height"]),
            str(cfg["max_iter"]),
            str(cfg["strategy"]),
            str(cfg["param"]),
            cfg["preset"],
            str(png_path),
            f"--ref={ref_path}",
        ]
        if not run_client(client_cmd, client_log, timeout=780):
            raise RuntimeError("El cliente fallo o excedio 13 minutos")

    finally:
        for proc, handle, _ in reversed(workers):
            stop_process(proc, handle)
        stop_process(master_proc, master_handle)

    text = client_log.read_text(errors="ignore")
    t_sec = parse_int(text, r"Tiempo Monolito \(T_sec\):\s+(\d+) ms")
    t_dist = parse_int(text, r"Tiempo Cl[uú]ster \(T_dist\):\s+(\d+) ms")
    if t_sec is None or t_dist is None:
        raise RuntimeError(f"No se pudieron leer las metricas de {client_log}")

    tasks = math.ceil(cfg["width"] / cfg["param"]) * math.ceil(cfg["height"] / cfg["param"])
    latency_min = t_dist / 60000.0
    speedup = t_sec / t_dist
    efficiency = speedup / cfg["workers"] * 100.0
    valid = "[VERIFICACION OK]" in text
    in_range = 1.0 <= latency_min <= 10.0

    row = {
        "id": cid,
        "configuracion": cfg["nombre"],
        "preset": cfg["preset"],
        "width": cfg["width"],
        "height": cfg["height"],
        "max_iter": cfg["max_iter"],
        "estrategia": "FixedTileSize",
        "parametro": cfg["param"],
        "tareas": tasks,
        "workers": cfg["workers"],
        "hilos_por_worker": cfg["threads"],
        "hilos_totales": cfg["workers"] * cfg["threads"],
        "t_sec_ms": t_sec,
        "t_dist_ms": t_dist,
        "latencia_min": f"{latency_min:.2f}",
        "speedup": f"{speedup:.2f}",
        "eficiencia_pct": f"{efficiency:.1f}",
        "validacion": "OK" if valid else "FALLO",
        "latencia_1_10": "SI" if in_range else "NO",
        "log_cliente": str(client_log.relative_to(ROOT)),
        "png": str(png_path.relative_to(ROOT)),
    }
    print(
        f"[SUITE] T_dist={t_dist} ms ({latency_min:.2f} min), S={speedup:.2f}x, "
        f"validacion={'OK' if valid else 'FALLO'}, rango_1_10={'SI' if in_range else 'NO'}",
        flush=True,
    )
    return row


def write_csv(rows):
    DATA.mkdir(parents=True, exist_ok=True)
    path = DATA / "exp4_retadoras.csv"
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return path


def write_markdown(rows):
    lines = [
        "| ID | Configuracion | Workers x hilos | Tareas | T_sec (ms) | T_dist (ms) | Latencia (min) | S | E | Validacion |",
        "| :--- | :--- | :---: | ---: | ---: | ---: | ---: | ---: | ---: | :---: |",
    ]
    for row in rows:
        lines.append(
            f"| {row['id']} | {row['configuracion']} | {row['workers']} x {row['hilos_por_worker']} | "
            f"{row['tareas']} | {row['t_sec_ms']} | {row['t_dist_ms']} | {row['latencia_min']} | "
            f"{row['speedup']}x | {row['eficiencia_pct']}% | {row['validacion']} |"
        )
    path = DATA / "exp4_retadoras.md"
    path.write_text("\n".join(lines) + "\n")
    return path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", help="IDs separados por coma")
    args = parser.parse_args()

    selected = None
    if args.only:
        selected = {item.strip() for item in args.only.split(",") if item.strip()}

    for path in (LOGS, IMG, DATA):
        path.mkdir(parents=True, exist_ok=True)

    rows = []
    for index, cfg in enumerate(CONFIGS):
        if selected and cfg["id"] not in selected:
            continue
        rows.append(run_config(cfg, index))

    if not rows:
        print("[SUITE] No se ejecuto ninguna configuracion", file=sys.stderr)
        return 1

    csv_path = write_csv(rows)
    md_path = write_markdown(rows)
    print(f"[SUITE] CSV: {csv_path}", flush=True)
    print(f"[SUITE] Tabla: {md_path}", flush=True)

    failed = [row for row in rows if row["validacion"] != "OK"]
    out_of_range = [row for row in rows if row["latencia_1_10"] != "SI"]
    if failed:
        print("[SUITE] Configuraciones sin validacion: " + ", ".join(row["id"] for row in failed))
    if out_of_range:
        print("[SUITE] Latencias fuera de 1-10 min: " + ", ".join(row["id"] for row in out_of_range))
    return 0 if not failed and not out_of_range else 2


if __name__ == "__main__":
    sys.exit(main())
