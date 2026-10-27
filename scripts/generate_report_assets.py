#!/usr/bin/env python3
"""Consolida datos de las corridas y genera CSV/graficas del informe.

Las metricas por worker y las estadisticas de matrices se extraen de los logs
del Maestro y de los archivos binarios de referencia; las tablas principales
consolidan los valores verificados de las corridas.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
LOGS = ROOT / "results" / "logs"
RAW = ROOT / "results" / "raw"
IMG = ROOT / "results" / "img"
DATA = ROOT / "results" / "data"
for directory in (IMG, DATA):
    directory.mkdir(parents=True, exist_ok=True)

TSEC_EXP1 = 421337
TSEC_EXP2 = 404508

EXP1_TILE = {
    32: {"t": 148730, "s": 2.83, "e": 141.6},
    64: {"t": 131989, "s": 3.19, "e": 159.6},
    128: {"t": 134318, "s": 3.14, "e": 156.8},
    256: {"t": 123022, "s": 3.42, "e": 171.2},
}
EXP1_FIXED = {
    2: {"t": 238567, "s": 1.77, "e": 88.3},
    4: {"t": 154264, "s": 2.73, "e": 136.6},
    8: {"t": 141394, "s": 2.98, "e": 149.0},
    16: {"t": 123394, "s": 3.41, "e": 170.7},
}

EXP2 = [
    {"threads": 1, "t": 340743, "s": 1.187, "e": 118.7, "avg_task": 164.3},
    {"threads": 2, "t": 227950, "s": 1.774, "e": 177.4, "avg_task": 220.3},
    {"threads": 4, "t": 191292, "s": 2.115, "e": 211.5, "avg_task": 369.4},
    {"threads": 8, "t": 163161, "s": 2.479, "e": 247.9, "avg_task": 629.8},
    {"threads": 16, "t": 136424, "s": 2.965, "e": 296.5, "avg_task": 1055.4},
    {"threads": 64, "t": 104425, "s": 3.874, "e": 387.4, "avg_task": 3182.2},
]

EXP3_ONE = [
    {"workers": 1, "t": 340743, "s": 1.187, "e": 118.7},
    {"workers": 2, "t": 262611, "s": 1.540, "e": 77.0},
    {"workers": 4, "t": 173043, "s": 2.338, "e": 58.4},
]
EXP3_FOUR = [
    {"workers": 1, "t": 191292, "s": 2.115, "e": 211.5},
    {"workers": 2, "t": 189074, "s": 2.139, "e": 107.0},
    {"workers": 4, "t": 125866, "s": 3.214, "e": 80.3},
]

CLASSIC = {
    "tsec": 99958,
    "tdist": 33016,
    "s": 3.03,
    "e": 75.7,
    "mean_iter": 682.5,
    "inside": 13.56,
    "lt20": 84.31,
}
SEAHORSE = {
    "tsec": 404508,
    "tdist": 125866,
    "s": 3.214,
    "e": 80.3,
    "mean_iter": 3347.8,
    "inside": 64.95,
    "lt20": 0.00,
}

EXP2_FILES = [
    ("A", 1, LOGS / "exp2_A_1hilo.log"),
    ("B", 2, LOGS / "exp2_B_2hilos.log"),
    ("C", 4, LOGS / "exp2_C_4hilos.log"),
    ("C_rep", 4, LOGS / "exp2_C_4hilos_rep.log"),
    ("E", 8, LOGS / "exp2_E_8hilos.log"),
    ("F", 16, LOGS / "exp2_F_16hilos.log"),
    ("D", 64, LOGS / "exp2_D_64hilos.log"),
]
EXP3_FILES = [
    ("p1_1h", 1, 1, LOGS / "exp2_A_1hilo.log"),
    ("p2_1h", 2, 1, LOGS / "exp3_p2_rep.log"),
    ("p4_1h", 4, 1, LOGS / "exp3_p4.log"),
    ("p1_4h", 1, 4, LOGS / "exp2_C_4hilos.log"),
    ("p1_4h_rep", 1, 4, LOGS / "exp2_C_4hilos_rep.log"),
    ("p2_4h", 2, 4, LOGS / "exp3_p2_4h.log"),
    ("p4_4h", 4, 4, LOGS / "exp3_p4_4h.log"),
]


def parse_client_log(path: Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace")
    patterns = {
        "workers": r"Workers en el clúster:\s+(\d+)",
        "tsec": r"Tiempo Monolito \(T_sec\):\s+(\d+) ms",
        "tdist": r"Tiempo Clúster \(T_dist\):\s+(\d+) ms",
        "s": r"Aceleración \(Speedup S\):\s+([\d,\.]+)x",
        "e": r"Eficiencia Paralela \(E\):\s+([\d,\.]+)%",
    }
    result = {}
    for key, pattern in patterns.items():
        match = re.search(pattern, text)
        if match:
            result[key] = match.group(1).replace(",", ".")
    return result


def parse_master_jobs(path: Path) -> list[dict]:
    jobs = []
    current = None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = re.search(r"\[MASTER\] Nueva solicitud de renderizado: (\S+)", line)
        if match:
            current = {"id": match.group(1), "workers": {}, "wall": None}
            jobs.append(current)
            continue
        if current is None:
            continue
        match = re.search(r"\[MASTER\] \[OK\] Tarea #(\d+) entregada por (\S+) \((\d+) ms\)", line)
        if match:
            worker = match.group(2)
            millis = int(match.group(3))
            entry = current["workers"].setdefault(worker, {"tasks": 0, "sum": 0, "max": 0})
            entry["tasks"] += 1
            entry["sum"] += millis
            entry["max"] = max(entry["max"], millis)
        match = re.search(r"Renderizado completado exitosamente en (\d+) ms", line)
        if match:
            current["wall"] = int(match.group(1))
    return jobs


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def matrix_stats(path: Path) -> dict:
    with path.open("rb") as handle:
        magic, width, height, max_iter = np.fromfile(handle, dtype=">i4", count=4)
        values = np.fromfile(handle, dtype=">i4", count=int(width) * int(height))
    return {
        "width": int(width),
        "height": int(height),
        "max_iter": int(max_iter),
        "mean": float(values.mean()),
        "inside_pct": float(100.0 * (values >= max_iter).mean()),
        "lt20_pct": float(100.0 * (values < 20).mean()),
        "lt100_pct": float(100.0 * (values < 100).mean()),
        "lt1000_pct": float(100.0 * (values < 1000).mean()),
        "max": int(values.max()),
    }


def plot_exp1() -> None:
    tile_sizes = sorted(EXP1_TILE)
    tile_s = [EXP1_TILE[size]["s"] for size in tile_sizes]
    tile_t = [EXP1_TILE[size]["t"] / 1000.0 for size in tile_sizes]
    fixed_ns = sorted(EXP1_FIXED)
    fixed_t = [EXP1_FIXED[n]["t"] / 1000.0 for n in fixed_ns]

    fig, (ax_s, ax_t) = plt.subplots(1, 2, figsize=(12, 4.8))
    ax_s.plot(tile_sizes, tile_s, marker="o", linewidth=2, color="#1f77b4", label="Baldosas SxS")
    for n in fixed_ns:
        ax_s.axhline(EXP1_FIXED[n]["s"], linestyle="--", linewidth=1.2, alpha=0.75, label=f"FixedCount N={n}")
    ax_s.set_xscale("log", base=2)
    ax_s.set_xticks(tile_sizes)
    ax_s.set_xticklabels([f"{size}x{size}" for size in tile_sizes])
    ax_s.set_xlabel("Tamano de baldosa (px)")
    ax_s.set_ylabel("Speedup S = T_sec / T_dist")
    ax_s.set_title("Speedup vs. granularidad")
    ax_s.axhline(4.0, color="gray", linewidth=0.8, linestyle=":", label="4 hilos logicos")
    ax_s.legend(fontsize=8, ncol=2)
    ax_s.set_ylim(0, 4.4)

    labels = [f"N={n}" for n in fixed_ns] + [f"{size}x{size}" for size in tile_sizes]
    values = fixed_t + tile_t
    colors = ["#ff7f0e"] * len(fixed_ns) + ["#1f77b4"] * len(tile_sizes)
    bars = ax_t.bar(range(len(values)), values, color=colors, alpha=0.85)
    ax_t.set_xticks(range(len(values)))
    ax_t.set_xticklabels(labels, rotation=35, ha="right", fontsize=8)
    ax_t.set_ylabel("T_dist (s)")
    ax_t.set_title("Tiempo distribuido (4K, Seahorse, p=2, 4 hilos/worker)")
    for bar, value in zip(bars, values):
        ax_t.text(bar.get_x() + bar.get_width() / 2, value + 2, f"{value:.1f}", ha="center", fontsize=7)
    fig.tight_layout()
    fig.savefig(IMG / "fig_exp1_granularidad.png", dpi=150)
    plt.close(fig)


def plot_exp2() -> None:
    threads = [row["threads"] for row in EXP2]
    speedups = [row["s"] for row in EXP2]
    avg_tasks = [row["avg_task"] for row in EXP2]
    times = [row["t"] / 1000.0 for row in EXP2]

    fig, (ax_s, ax_task) = plt.subplots(1, 2, figsize=(12, 4.8))
    ax_s.plot(threads, speedups, marker="o", linewidth=2, color="#1f77b4")
    for x, y, t in zip(threads, speedups, times):
        ax_s.annotate(f"{y:.2f}x\n{t:.1f}s", (x, y), textcoords="offset points", xytext=(0, 9),
                      ha="center", fontsize=7)
    ax_s.set_xscale("log", base=2)
    ax_s.set_xticks(threads)
    ax_s.set_xticklabels([str(t) for t in threads])
    ax_s.set_xlabel("Hilos de computo por worker")
    ax_s.set_ylabel("Speedup S = T_sec / T_dist")
    ax_s.set_title("Speedup vs. tamano del ThreadPool")
    ax_s.axhline(4.0, color="gray", linewidth=0.8, linestyle=":", label="4 hilos logicos")
    ax_s.legend(fontsize=8)
    ax_s.set_ylim(0, 4.5)

    ax_task.plot(threads, avg_tasks, marker="s", linewidth=2, color="#d62728")
    for x, y in zip(threads, avg_tasks):
        ax_task.annotate(f"{y:.0f} ms", (x, y), textcoords="offset points", xytext=(0, 9),
                         ha="center", fontsize=7)
    ax_task.set_xscale("log", base=2)
    ax_task.set_yscale("log")
    ax_task.set_xticks(threads)
    ax_task.set_xticklabels([str(t) for t in threads])
    ax_task.set_xlabel("Hilos de computo por worker")
    ax_task.set_ylabel("Tiempo medio por tarea (ms, escala log)")
    ax_task.set_title("Latencia por tarea vs. hilos")
    fig.tight_layout()
    fig.savefig(IMG / "fig_exp2_hilos.png", dpi=150)
    plt.close(fig)


def plot_exp3() -> None:
    workers = [1, 2, 4]
    one_s = [row["s"] for row in EXP3_ONE]
    one_e = [row["e"] for row in EXP3_ONE]
    four_s = [row["s"] for row in EXP3_FOUR]
    four_e = [row["e"] for row in EXP3_FOUR]

    fig, (ax_s, ax_e) = plt.subplots(1, 2, figsize=(12, 4.8))
    ax_s.plot(workers, one_s, marker="o", linewidth=2, label="1 hilo/worker", color="#1f77b4")
    ax_s.plot(workers, four_s, marker="s", linewidth=2, label="4 hilos/worker", color="#ff7f0e")
    ax_s.plot(workers, workers, linestyle="--", linewidth=1.2, color="gray", label="Ideal S = p")
    for x, y in zip(workers, one_s):
        ax_s.annotate(f"{y:.2f}x", (x, y), textcoords="offset points", xytext=(0, 9), ha="center", fontsize=8)
    for x, y in zip(workers, four_s):
        ax_s.annotate(f"{y:.2f}x", (x, y), textcoords="offset points", xytext=(0, -15), ha="center", fontsize=8)
    ax_s.set_xticks(workers)
    ax_s.set_xlabel("Workers (p)")
    ax_s.set_ylabel("Speedup S = T_sec / T_dist")
    ax_s.set_title("Escalabilidad del cluster")
    ax_s.legend(fontsize=8)
    ax_s.set_ylim(0, 4.4)

    ax_e.plot(workers, one_e, marker="o", linewidth=2, label="1 hilo/worker", color="#1f77b4")
    ax_e.plot(workers, four_e, marker="s", linewidth=2, label="4 hilos/worker", color="#ff7f0e")
    ax_e.set_xticks(workers)
    ax_e.set_xlabel("Workers (p)")
    ax_e.set_ylabel("Eficiencia E = S/p x 100%")
    ax_e.set_title("Eficiencia aparente (p = workers)")
    ax_e.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(IMG / "fig_exp3_escalabilidad.png", dpi=150)
    plt.close(fig)


def plot_amdahl() -> None:
    t1 = EXP3_ONE[0]["t"]
    t2 = EXP3_ONE[1]["t"]
    t4 = EXP3_ONE[2]["t"]
    p = np.array([1.0, 2.0, 4.0])
    ratio = np.array([t1, t2, t4], dtype=float) / t1
    x = -(1.0 - 1.0 / p)
    y = ratio - 1.0
    f = float((x @ y) / (x @ x))
    serial = 1.0 - f

    p_curve = np.linspace(1, 8, 200)
    fitted = 1.0 / (serial + (1.0 - serial) / p_curve)
    best_case = 1.0 / (0.25 + 0.75 / p_curve)

    fig, ax = plt.subplots(figsize=(7.6, 4.9))
    ax.plot(p, 1.0 / ratio, marker="o", linestyle="none", markersize=8,
            label="Medido: S_rel = T_dist(1)/T_dist(p)", color="#1f77b4")
    ax.plot(p_curve, fitted, linewidth=2, label=f"Ajuste Amdahl 1-f={serial:.2f}", color="#1f77b4")
    ax.plot(p_curve, best_case, linewidth=1.5, linestyle="--", label="Cota optimista 1-f=0.25", color="#d62728")
    ax.axhline(1.0 / serial, color="#1f77b4", linewidth=0.8, linestyle=":")
    ax.text(1.15, 1.0 / serial + 0.06, f"Asintota 1/(1-f) = {1.0 / serial:.2f}", fontsize=8, color="#1f77b4")
    ax.text(1.15, 0.25,
            "Speedup absoluto vs monolito:\n"
            "p=1: 1.19x   p=2: 1.54x   p=4: 2.34x",
            fontsize=8, bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.8))
    ax.set_xlabel("Workers / hilos de computo (p)")
    ax.set_ylabel("Speedup relativo a p=1")
    ax.set_title("Ley de Amdahl sobre la escalabilidad relativa (1 hilo/worker)")
    ax.legend(fontsize=8, loc="lower right")
    ax.set_xlim(1, 8)
    ax.set_ylim(0, 4.5)
    fig.tight_layout()
    fig.savefig(IMG / "fig_amdahl.png", dpi=150)
    plt.close(fig)


def plot_classic() -> None:
    labels = ["classic", "seahorse"]
    tsec = [CLASSIC["tsec"] / 1000.0, SEAHORSE["tsec"] / 1000.0]
    tdist = [CLASSIC["tdist"] / 1000.0, SEAHORSE["tdist"] / 1000.0]
    mean_iter = [CLASSIC["mean_iter"], SEAHORSE["mean_iter"]]

    fig, (ax_t, ax_i) = plt.subplots(1, 2, figsize=(11, 4.4))
    x = np.arange(len(labels))
    width = 0.36
    bars1 = ax_t.bar(x - width / 2, tsec, width, label="T_sec (monolito)", color="#1f77b4")
    bars2 = ax_t.bar(x + width / 2, tdist, width, label="T_dist (p=4, 4 hilos/worker)", color="#ff7f0e")
    ax_t.set_xticks(x)
    ax_t.set_xticklabels(labels)
    ax_t.set_ylabel("Tiempo (s)")
    ax_t.set_title("Vista macro vs. zona de estres (4K, 5000 iter)")
    ax_t.legend(fontsize=8)
    for bars in (bars1, bars2):
        for bar in bars:
            ax_t.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 4, f"{bar.get_height():.1f}",
                      ha="center", fontsize=8)

    bars3 = ax_i.bar(x, mean_iter, color=["#2ca02c", "#d62728"], alpha=0.85)
    ax_i.set_xticks(x)
    ax_i.set_xticklabels(labels)
    ax_i.set_ylabel("Iteraciones promedio por pixel")
    ax_i.set_title("Carga aritmetica media")
    for bar, value, inside in zip(bars3, mean_iter, [CLASSIC["inside"], SEAHORSE["inside"]]):
        ax_i.text(bar.get_x() + bar.get_width() / 2, value + 60,
                  f"{value:.0f}\ninterior {inside:.1f}%", ha="center", fontsize=8)
    fig.tight_layout()
    fig.savefig(IMG / "fig_classic_vs_seahorse.png", dpi=150)
    plt.close(fig)


def plot_exp4() -> None:
    path = DATA / "exp4_retadoras.csv"
    if not path.exists():
        return
    with path.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        return

    labels = [row["id"].split("_")[0].upper() for row in rows]
    latency = [float(row["latencia_min"]) for row in rows]
    speedup = [float(row["speedup"]) for row in rows]
    configs = [row["configuracion"] for row in rows]

    fig, (ax_l, ax_s) = plt.subplots(1, 2, figsize=(12, 4.6))
    x = np.arange(len(rows))
    colors = ["#1f77b4", "#d62728", "#2ca02c", "#ff7f0e", "#9467bd"]

    bars = ax_l.bar(x, latency, color=colors, alpha=0.85)
    ax_l.axhspan(1.0, 10.0, color="#2ca02c", alpha=0.08, label="Rango objetivo 1-10 min")
    ax_l.set_xticks(x)
    ax_l.set_xticklabels(labels)
    ax_l.set_ylabel("Latencia extremo a extremo (min)")
    ax_l.set_title("Latencia de job de las 5 configuraciones")
    ax_l.set_ylim(0, 10.5)
    ax_l.legend(fontsize=8, loc="upper right")
    for bar, value, config in zip(bars, latency, configs):
        ax_l.text(bar.get_x() + bar.get_width() / 2, value + 0.12, f"{value:.2f}",
                  ha="center", fontsize=8)
        ax_l.text(bar.get_x() + bar.get_width() / 2, 0.25, config.split(" - ")[1],
                  ha="center", va="bottom", rotation=90, fontsize=6.5, color="white")

    bars_s = ax_s.bar(x, speedup, color=colors, alpha=0.85)
    ax_s.axhline(1.0, color="black", linewidth=0.8, linestyle="--")
    ax_s.set_xticks(x)
    ax_s.set_xticklabels(labels)
    ax_s.set_ylabel("Speedup S = T_sec / T_dist")
    ax_s.set_title("Speedup de las 5 configuraciones")
    for bar, value in zip(bars_s, speedup):
        ax_s.text(bar.get_x() + bar.get_width() / 2, value + 0.08, f"{value:.2f}x",
                  ha="center", fontsize=8)
    ax_s.set_ylim(0, max(4.5, max(speedup) + 0.6))

    fig.tight_layout()
    fig.savefig(IMG / "fig_exp4_retadoras.png", dpi=150)
    plt.close(fig)


def main() -> None:
    exp1_rows = []
    for n, row in EXP1_FIXED.items():
        exp1_rows.append({"estrategia": "FixedCount", "parametro": n, "tareas": n,
                          "t_sec_ms": TSEC_EXP1, "t_dist_ms": row["t"], "speedup": row["s"], "eficiencia_pct": row["e"]})
    for size, row in EXP1_TILE.items():
        tasks = int(np.ceil(3840 / size) * np.ceil(2160 / size))
        exp1_rows.append({"estrategia": "FixedTileSize", "parametro": size, "tareas": tasks,
                          "t_sec_ms": TSEC_EXP1, "t_dist_ms": row["t"], "speedup": row["s"], "eficiencia_pct": row["e"]})
    write_csv(DATA / "exp1_granularidad.csv", exp1_rows,
              ["estrategia", "parametro", "tareas", "t_sec_ms", "t_dist_ms", "speedup", "eficiencia_pct"])

    for row in EXP2:
        row["t_sec_ms"] = TSEC_EXP2
        row["t_dist_ms"] = row["t"]
        row["speedup"] = row["s"]
        row["eficiencia_pct"] = row["e"]
        row["avg_task_ms"] = row["avg_task"]
    write_csv(DATA / "exp2_threadpool.csv", EXP2,
              ["threads", "t_sec_ms", "t_dist_ms", "speedup", "eficiencia_pct", "avg_task_ms"])

    exp3_rows = []
    for row in EXP3_ONE:
        exp3_rows.append({"workers": row["workers"], "hilos_por_worker": 1, "t_dist_ms": row["t"],
                          "speedup": row["s"], "eficiencia_pct": row["e"]})
    for row in EXP3_FOUR:
        exp3_rows.append({"workers": row["workers"], "hilos_por_worker": 4, "t_dist_ms": row["t"],
                          "speedup": row["s"], "eficiencia_pct": row["e"]})
    write_csv(DATA / "exp3_escalabilidad.csv", exp3_rows,
              ["workers", "hilos_por_worker", "t_dist_ms", "speedup", "eficiencia_pct"])

    stats_rows = []
    for name, path in (("classic", RAW / "reference_classic_4k_5000.bin"),
                       ("seahorse", RAW / "reference_seahorse_4k_5000.bin")):
        if path.exists():
            stats = matrix_stats(path)
            stats["region"] = name
            stats_rows.append(stats)
    if stats_rows:
        write_csv(DATA / "matrix_stats.csv", stats_rows,
                  ["region", "width", "height", "max_iter", "mean", "inside_pct", "lt20_pct",
                   "lt100_pct", "lt1000_pct", "max"])

    exp1_labels = ["N=2", "N=4", "N=8", "N=16", "tile32", "tile64", "tile128", "tile256"]
    exp2_labels = ["exp2_A_1h", "exp2_B_2h", "exp2_C_4h", "exp2_D_64h", "exp2_C_4h_rep",
                   "exp2_E_8h", "exp2_F_16h", "exp3_p2_1h", "exp3_p4_1h", "exp3_p2_1h_rep",
                   "exp3_p2_4h", "exp3_p4_4h", "classic"]
    per_worker_rows = []
    for labels, filename, experiment in (
        (exp1_labels, "exp1_master.log", "exp1"),
        (exp2_labels, "exp2_master.log", "exp2/exp3"),
    ):
        for index, job in enumerate(parse_master_jobs(LOGS / filename)):
            label = labels[index] if index < len(labels) else f"job_{index + 1}"
            for worker, entry in sorted(job["workers"].items()):
                per_worker_rows.append({
                    "experimento": experiment,
                    "configuracion": label,
                    "worker": worker,
                    "tareas": entry["tasks"],
                    "computo_total_ms": entry["sum"],
                    "computo_promedio_ms": round(entry["sum"] / entry["tasks"], 1),
                    "computo_maximo_ms": entry["max"],
                    "wall_master_ms": job["wall"],
                })
    write_csv(DATA / "per_worker.csv", per_worker_rows,
              ["experimento", "configuracion", "worker", "tareas", "computo_total_ms",
               "computo_promedio_ms", "computo_maximo_ms", "wall_master_ms"])

    plot_exp1()
    plot_exp2()
    plot_exp3()
    plot_amdahl()
    plot_classic()
    plot_exp4()
    print("Artefactos generados en results/data y results/img")


if __name__ == "__main__":
    main()
