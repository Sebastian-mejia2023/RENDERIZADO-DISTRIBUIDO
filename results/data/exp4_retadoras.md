| ID | Configuracion | Workers x hilos | Tareas | T_sec (ms) | T_dist (ms) | Latencia (min) | S | E | Validacion |
| :--- | :--- | :---: | ---: | ---: | ---: | ---: | ---: | ---: | :---: |
| r1_ultrafino | R1 - Grano ultrafino con 4 workers | 4 x 4 | 14400 | 404508 | 131274 | 2.19 | 3.08x | 77.0% | OK |
| r2_ultragrueso | R2 - Grano ultragrueso con un solo hilo | 1 x 1 | 40 | 404508 | 445339 | 7.42 | 0.91x | 90.8% | OK |
| r3_pool128 | R3 - Sobredimensionamiento de 128 hilos | 1 x 128 | 8160 | 404508 | 119253 | 1.99 | 3.39x | 339.2% | OK |
| r4_4w8h | R4 - Cuatro workers con 8 hilos cada uno | 4 x 8 | 2040 | 404508 | 102307 | 1.71 | 3.95x | 98.8% | OK |
| r5_classic_fino | R5 - Vista macro con grano ultrafino | 4 x 4 | 32400 | 99958 | 60276 | 1.00 | 1.66x | 41.5% | OK |
