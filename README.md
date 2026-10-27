# Taller Evaluativo: Renderizado Distribuido de Fractales (Patrón Master-Worker)

**Asignatura:** Computación en Internet I (`09810 - TIC`)  
**Facultad:** Facultad de Ingeniería, Diseño y Ciencias Aplicadas  
**Departamento:** Departamento de Computación y Sistemas Inteligentes (DCSI)  
**Institución:** Universidad Icesi, Cali, Colombia  
**Tecnología:** Java 17+, ZeroC Ice 3.7.10, Slice IDL, Gradle 8.6 Multimódulo  

---

## Informe de resultados

El informe técnico completo, con tablas, gráficas, respuestas y bitácora de IAG, está en [`INFORME.md`](INFORME.md). Los datos y figuras se generan con `scripts/generate_report_assets.py`.

---

## 🎯 Propósito del Taller

Este taller evalúa el diseño y optimización de sistemas de **procesamiento distribuido** bajo el patrón **Master-Worker** y el modelo **MIMD + NORMA (Shared-Nothing)**.

A diferencia de esquemas simples de comunicación por red, este sistema resuelve el renderizado del **Conjunto de Mandelbrot**, un problema con alta densidad aritmética y **carga intrínsecamente heterogénea**:
* En la vista macro tradicional, las regiones exteriores escapan en 1 o 2 iteraciones (nanosegundos), por lo que el monolito parece engañosamente rápido.
* En regiones de frontera profunda como el **Valle de los Caballitos de Mar (*Seahorse Valley*)**, más del 85% de los píxeles demandan entre 4.000 y 10.000 iteraciones (milisegundos por píxel).

El estudiante experimentará cómo las **decisiones arquitectónicas** (la estrategia de partición de tareas, el tamaño de baldosa *tileSize*, la resolución 4K y el dimensionamiento del pool de hilos) determinan si un clúster logra una aceleración real (**Speedup $S > 1$**) o colapsa por sobrecosto de red o contención de CPU.

---

## 🏛️ Arquitectura del Sistema (Flujo Desacoplado Asíncrono)

Para evitar que el Maestro mantenga hilos bloqueados hacia los Workers, el sistema opera bajo un **modelo desacoplado de extracción de trabajo (*Work-Pulling / Bag of Tasks*)**:

```text
       ┌─────────────────────────────────────────────────────────────┐
       │                       CLIENTE                               │
       │  1. Ejecuta cómputo monohilo secuencial (T_sec de control)  │
       │  2. Invoca master.renderFractal(config)                     │
       │  3. Valida resultado celda por celda contra el monolito     │
       │  4. Calcula Speedup (S), Eficiencia (E) y guarda el PNG     │
       └──────────────────────────────┬──────────────────────────────┘
                                      │ Invocación RPC
                                      ▼
       ┌─────────────────────────────────────────────────────────────┐
       │                       MAESTRO (MASTER)                      │
       │  - Aplica Patrón Strategy para dividir el fractal en tareas │
       │  - Encola las tareas en una ConcurrentLinkedQueue (Bolsa)   │
       │  - Notifica asíncronamente a los Workers registrados        │
       │  - Atiende llamadas pollTask() y reportResult()             │
       │  - Consolida incrementalmente los bloques de píxeles        │
       └──────────────▲───────────────────────────────▲──────────────┘
                      │                               │
         (1) notify   │                  (1) notify   │
         (2) pollTask │                  (2) pollTask │
         (3) report   │                  (3) report   │
                      ▼                               ▼
       ┌─────────────────────────────┐ ┌─────────────────────────────┐
       │     WORKER 1 (Worker-1)     │ │     WORKER 2 (Worker-2)     │
       │ - Recibe notify()           │ │ - Recibe notify()           │
       │ - Bucle: pollTask()         │ │ - Bucle: pollTask()         │
       │ - Cómputo local intensivo   │ │ - Cómputo local intensivo   │
       │ - master.reportResult()     │ │ - master.reportResult()     │
       │ - Repite hasta cola vacía   │ │ - Repite hasta cola vacía   │
       └─────────────────────────────┘ └─────────────────────────────┘
```

---

## 🗺️ Presets de Exploración y Zonas de Carga (`FractalRegion`)

El proyecto incorpora un catálogo de regiones complejas para comparar el comportamiento macro vs. estrés:

| Preset | Nombre / Región | Coordenadas Complejas | Carga de Cómputo | Uso Recomendado |
| :---: | :--- | :---: | :---: | :--- |
| `classic` | Vista Panorámica General | $X \in [-2.0, 0.5], Y \in [-1.25, 1.25]$ | 76% espacio exterior vacío | Prueba funcional inicial |
| **`seahorse`** | **Valle de los Caballitos** | $X \in [-0.75, -0.74], Y \in [0.09, 0.10]$ | **Hiperdensa (85% en frontera)** | **Benchmarking 4K / Estrés Clúster** |
| `elephant` | Valle de los Elefantes | $X \in [0.25, 0.35], Y \in [-0.05, 0.05]$ | Espirales densas | Estudio de desbalance de carga |
| `mini` | Mini-Mandelbrot Satélite | $X \in [-1.78, -1.74], Y \in [-0.02, 0.02]$ | 100% píxeles agotan iteraciones | Saturación sostenida de cores |

---

## 🧩 Patrón Strategy: Partición de Tareas

El Maestro delega la descomposición geométrica del fractal en implementaciones de la interfaz `TaskPartitionStrategy`:

1. **`FixedCountPartitionStrategy` (División en $N$ tareas fijas):**
   * Divide la altura total de la imagen en $N$ franjas horizontales contiguas.
   * *Comportamiento esperado:* Sufre de severo desbalance de carga (*load imbalance*) cuando la franja central coincide con zonas densas del fractal.
2. **`FixedTileSizePartitionStrategy` (División por baldosas $S \times S$):**
   * Divide la imagen en una cuadrícula de baldosas de tamaño configurable (ej. $16\times 16$, $64\times 64$, $128\times 128$).
   * *Comportamiento esperado:* Permite que el bucle dinámico de extracción mantenga a todos los workers y núcleos saturados de cómputo útil.

---

## 📁 Estructura del Proyecto

```text
fractal-master-worker/
├── settings.gradle                        # Orquestador multimódulo
├── build.gradle                           # Configuración global y plugin oficial de Slice
├── common/                                # Subproyecto de contrato y lógica compartida
│   ├── build.gradle                       # Plugin com.zeroc.gradle.ice-builder.slice
│   └── src/main/
│       ├── slice/FractalCompute.ice       # Contrato IDL (RenderConfig, TaskTile, TileResult, Interfaces)
│       └── java/co/icesi/fractal/
│           ├── core/MandelbrotCore.java   # Motor matemático y generador de PNG
│           ├── core/FractalRegion.java    # Presets de exploración y coordenadas
│           └── strategy/                  # Patrón Strategy (FixedCount, FixedTileSize, Factory)
├── monolith/                              # Línea base secuencial en una sola CPU
│   ├── build.gradle
│   └── src/main/java/co/icesi/fractal/monolith/MonolithicMain.java
├── server/                                # Nodo Maestro
│   ├── build.gradle
│   └── src/main/java/co/icesi/fractal/master/
│       ├── MasterMain.java                # Inicialización Ice y endpoints
│       └── MasterServiceI.java            # Servant: Bolsa de tareas y consolidación incremental
├── worker/                                # Nodo Trabajador
│   ├── build.gradle
│   └── src/main/java/co/icesi/fractal/worker/
│       ├── WorkerMain.java                # Bucle de extracción (pollTask) y ThreadPool
│       └── WorkerObserverI.java           # Servant callback: recepción de notifyTasksAvailable
├── client/                                # Nodo Cliente y Banco de Pruebas
│   ├── build.gradle
│   └── src/main/java/co/icesi/fractal/client/
│       ├── ClientMain.java                # Benchmark único con validación de píxeles y Speedup
│       └── ExperimentRunner.java          # Ejecutor automatizado de la matriz experimental
├── scripts/
│   ├── generate_report_assets.py          # Consolida CSV y figuras del informe
│   └── run_challenging_suite.py           # Orquesta las 5 configuraciones retadoras
└── results/                               # Logs, CSV, matrices de referencia y PNG
    ├── data/                              # Tablas consolidadas (incluye exp4_retadoras.csv)
    ├── img/                               # Figuras e imágenes generadas
    ├── logs/                              # Logs crudos del Maestro, workers y cliente
    └── raw/                               # Matrices binarias de referencia del monolito
```

---

## 🚀 Guía de Ejecución Rápida

### 1. Compilar todo el proyecto
```bash
./gradlew build
```

### 2. Probar la versión monolítica (Línea base en 4K y 5.000 iteraciones)
```bash
# Argumentos: <ancho> <alto> <maxIter> <preset: seahorse|classic|elephant|mini> <salida>
./gradlew :monolith:runMonolith --args="3840 2160 5000 seahorse output/mandelbrot_monolith.png"
```

### 3. Iniciar el Clúster Distribuido

**Terminal 1 — Iniciar Maestro (Puerto 10000):**
```bash
./gradlew :server:runMaster --args="10000"
```

**Terminal 2 — Iniciar Worker 1 (Puerto 10001 con 4 hilos):**
```bash
./gradlew :worker:runWorker --args="10001 Worker-1 localhost 10000 4"
```

**Terminal 3 — Iniciar Worker 2 (Puerto 10002 con 4 hilos):**
```bash
./gradlew :worker:runWorker --args="10002 Worker-2 localhost 10000 4"
```

**Terminal 4 — Ejecutar Cliente de Pruebas (4K / 5.000 iteraciones / Baldosas 64x64):**
```bash
# Argumentos: <host> <puerto> <ancho> <alto> <maxIter> <estrategia: 0=franjas, 1=baldosas> <parametro> <preset> <salida>
./gradlew :client:runClient --args="localhost 10000 3840 2160 5000 1 64 seahorse output/mandelbrot_distribuido.png"
```

El cliente acepta además `--ref=<archivo>` y `--tsec=<ms>` para reutilizar una matriz de referencia del monolito y evitar repetir la línea base en cada corrida.

### 4. Ejecutar la Matriz Automatizada de Experimentos
Con el Maestro y los Workers corriendo, ejecute el generador de la tabla comparativa en la región de estrés:
```bash
./gradlew :client:runExperiment --args="localhost 10000 3840 2160 5000 seahorse"
```

El script imprimirá automáticamente una tabla en formato Markdown con las métricas de **$T_{\text{sec}}$, $T_{\text{dist}}$, $S$ y $E$** para cada combinación arquitectónica.

### 5. Ejecutar la Suite de 5 Configuraciones Retadoras

La suite levanta y apaga el Maestro y los workers para cada configuración, reutiliza las matrices de referencia del monolito y valida la imagen completa:

```bash
python3 scripts/run_challenging_suite.py

# Repetir solo una configuración
python3 scripts/run_challenging_suite.py --only r4_4w8h
```

La **latencia** reportada es el tiempo de pared extremo a extremo del job ($T_{\text{dist}}$). Las cinco configuraciones se eligieron para cubrir latencias entre 1 y 10 minutos:

| ID | Configuración | Workers × hilos | Tile | Latencia | Speedup | Validación |
| :--- | :--- | :---: | :---: | ---: | ---: | :---: |
| R1 | Grano ultrafino con 4 workers | 4 × 4 | 24 × 24 | 2,19 min | 3,08× | OK |
| R2 | Grano ultragrueso con un solo hilo | 1 × 1 | 512 × 512 | 7,42 min | 0,91× | OK |
| R3 | Sobredimensionamiento de 128 hilos | 1 × 128 | 32 × 32 | 1,99 min | 3,39× | OK |
| R4 | Cuatro workers con 8 hilos cada uno | 4 × 8 | 64 × 64 | 1,71 min | 3,95× | OK |
| R5 | Vista macro con grano ultrafino | 4 × 4 | 16 × 16 | 1,00 min | 1,66× | OK |

Los resultados completos, la figura y el análisis están en el [`INFORME.md`](INFORME.md) (§3.6). Los datos crudos se guardan en `results/data/exp4_retadoras.csv` y `results/logs/challenge_*`.
