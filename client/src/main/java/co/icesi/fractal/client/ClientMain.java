package co.icesi.fractal.client;

import FractalApp.*;
import co.icesi.fractal.core.FractalRegion;
import co.icesi.fractal.core.MandelbrotCore;
import com.zeroc.Ice.*;
import java.io.*;
import java.util.UUID;

/**
 * Cliente de Pruebas y Benchmark del Clúster de Renderizado.
 * 
 * 1. Conecta con el Maestro.
 * 2. Ejecuta un cómputo monohilo local para establecer la línea base de tiempo (T_sec).
 * 3. Solicita al clúster el renderizado distribuido (T_dist).
 * 4. Valida numéricamente que el resultado distribuido sea idéntico celda por celda.
 * 5. Calcula y reporta Speedup (S), Eficiencia (E) y guarda la imagen PNG final.
 */
public class ClientMain {

    public static void main(String[] args) {
        String masterHost = (args.length >= 1) ? args[0] : "localhost";
        int masterPort = (args.length >= 2) ? Integer.parseInt(args[1]) : 10000;
        int width = (args.length >= 3) ? Integer.parseInt(args[2]) : 3840;
        int height = (args.length >= 4) ? Integer.parseInt(args[3]) : 2160;
        int maxIter = (args.length >= 5) ? Integer.parseInt(args[4]) : 5000;
        int strategyType = (args.length >= 6) ? Integer.parseInt(args[5]) : 1; // 1 = FixedTileSize por defecto
        int strategyParam = (args.length >= 7) ? Integer.parseInt(args[6]) : 64; // Baldosas de 64x64 por defecto
        
        String presetName = "seahorse";
        String outputPath = "output/mandelbrot_distribuido.png";

        if (args.length >= 8) {
            if (args[7].endsWith(".png") || args[7].contains("/") || args[7].contains("\\")) {
                outputPath = args[7];
            } else {
                presetName = args[7];
                if (args.length >= 9) {
                    outputPath = args[8];
                }
            }
        }

        Long tSecOverride = null;
        String referencePath = null;
        for (String arg : args) {
            if (arg.startsWith("--tsec=")) {
                tSecOverride = Long.parseLong(arg.substring("--tsec=".length()));
            } else if (arg.startsWith("--ref=")) {
                referencePath = arg.substring("--ref=".length());
            }
        }

        FractalRegion region = FractalRegion.fromName(presetName);
        double xMin = region.getXMin();
        double xMax = region.getXMax();
        double yMin = region.getYMin();
        double yMax = region.getYMax();

        // Ajuste isometrico de aspecto
        if (width > 0 && height > 0) {
            double aspect = (double) width / (double) height;
            double realHeight = yMax - yMin;
            xMax = xMin + realHeight * aspect;
        }

        InitializationData initData = new InitializationData();
        initData.properties = Util.createProperties(args);
        initData.properties.setProperty("Ice.MessageSizeMax", "204800");

        try (Communicator communicator = Util.initialize(initData)) {
            String masterEndpoint = String.format("MasterService:tcp -h %s -p %d", masterHost, masterPort);
            MasterServicePrx master = MasterServicePrx.checkedCast(communicator.stringToProxy(masterEndpoint));

            if (master == null) {
                System.err.println("[ERROR] No se pudo conectar al Master en " + masterEndpoint);
                return;
            }

            int workerCount = master.getWorkerCount();
            System.out.println("=================================================");
            System.out.println("         CLIENTE DE BENCHMARK FRACTAL");
            System.out.println("=================================================");
            System.out.printf("Conectado a Master:    %s%n", masterEndpoint);
            System.out.printf("Workers en el clúster: %d nodo(s) activo(s)%n", workerCount);
            System.out.printf("Preset / Región:       %s (%s)%n", region.getName(), region.getId());
            System.out.printf("Dimensiones imagen:    %dx%d (%d px)%n", width, height, (long) width * height);
            System.out.printf("Plano Complejo:        X=[%.6f, %.6f], Y=[%.6f, %.6f]%n", xMin, xMax, yMin, yMax);
            System.out.printf("Max. Iteraciones:      %d%n", maxIter);
            System.out.printf("Estrategia elegida:    %s (Parametro = %d)%n",
                (strategyType == 0 ? "FixedCount (N franjas)" : "FixedTileSize (Baldosas)"), strategyParam);

            if (workerCount == 0) {
                System.err.println("[ADVERTENCIA] No hay workers registrados. El clúster no podrá procesar.");
                return;
            }

            // 1. Línea Base Monohilo Local (T_sec), con cache opcional de referencia
            long tSec;
            int[][] localMatrix;
            if (referencePath != null && new File(referencePath).isFile()) {
                System.out.println("\n[1/3] Cargando matriz de referencia desde " + referencePath + "...");
                localMatrix = loadReferenceMatrix(referencePath, width, height, maxIter);
                tSec = readReferenceTime(referencePath);
                System.out.printf("[REFERENCIA] T_sec registrado: %d ms (%.2f s)%n", tSec, tSec / 1000.0);
            } else {
                System.out.println("\n[1/3] Ejecutando línea base monohilo local (T_sec)...");
                long t0Sec = System.currentTimeMillis();
                localMatrix = new int[height][width];
                double dx = (width > 1) ? (xMax - xMin) / (width - 1) : 0.0;
                double dy = (height > 1) ? (yMax - yMin) / (height - 1) : 0.0;

                for (int y = 0; y < height; y++) {
                    double ci = yMin + y * dy;
                    for (int x = 0; x < width; x++) {
                        double cr = xMin + x * dx;
                        localMatrix[y][x] = MandelbrotCore.computePoint(cr, ci, maxIter);
                    }
                }
                tSec = System.currentTimeMillis() - t0Sec;
                System.out.printf("[LINEA BASE] Tiempo Secuencial (T_sec): %d ms (%.2f s)%n", tSec, tSec / 1000.0);
                if (referencePath != null) {
                    saveReferenceMatrix(referencePath, localMatrix, maxIter, tSec);
                    System.out.println("[REFERENCIA] Matriz base guardada en " + referencePath);
                }
            }
            if (tSecOverride != null) {
                tSec = tSecOverride;
                System.out.printf("[REFERENCIA] T_sec forzado por argumento: %d ms%n", tSec);
            }

            // 2. Solicitud de Renderizado al Clúster Distribuido (T_dist)
            System.out.println("\n[2/3] Solicitando renderizado distribuido al clúster Master-Worker...");
            String jobId = "job-" + UUID.randomUUID().toString().substring(0, 8);
            RenderConfig config = new RenderConfig(
                jobId, width, height, xMin, xMax, yMin, yMax, maxIter, strategyType, strategyParam
            );

            long t0Dist = System.currentTimeMillis();
            int[][] distMatrix = master.renderFractal(config);
            long tDist = System.currentTimeMillis() - t0Dist;

            // 3. Verificación de Corrección y Métricas
            System.out.println("\n[3/3] Validando integridad de los datos calculados...");
            int errorCount = 0;
            for (int y = 0; y < height; y++) {
                for (int x = 0; x < width; x++) {
                    if (localMatrix[y][x] != distMatrix[y][x]) {
                        errorCount++;
                    }
                }
            }

            if (errorCount > 0) {
                System.err.printf("[FALLO] Se detectaron %d diferencias entre el monolito y el clúster!%n", errorCount);
            } else {
                System.out.println("[VERIFICACION OK] El resultado distribuido es 100% idéntico al secuencial.");
            }

            // Métricas de Rendimiento
            double speedup = (double) tSec / (double) Math.max(1, tDist);
            double efficiency = (workerCount > 0) ? (speedup / workerCount) * 100.0 : 0.0;

            System.out.println("\n=================================================");
            System.out.println("              RESULTADOS DEL BENCHMARK");
            System.out.println("=================================================");
            System.out.printf("Tiempo Monolito (T_sec):      %d ms (%.2f s)%n", tSec, tSec / 1000.0);
            System.out.printf("Tiempo Clúster (T_dist):      %d ms (%.2f s)%n", tDist, tDist / 1000.0);
            System.out.printf("Aceleración (Speedup S):      %.2fx%n", speedup);
            System.out.printf("Eficiencia Paralela (E):      %.1f%%%n", efficiency);
            System.out.println("=================================================");

            // Guardar imagen distribuida
            try {
                MandelbrotCore.saveImage(distMatrix, width, height, maxIter, outputPath);
            } catch (IOException e) {
                System.err.println("[ERROR] No se pudo guardar la imagen generada: " + e.getMessage());
            }

        } catch (java.lang.Exception e) {
            System.err.println("[ERROR] Excepción durante la ejecución del cliente: " + e.getMessage());
            e.printStackTrace();
        }
    }

    private static final int REFERENCE_MAGIC = 0x46524143;

    private static void saveReferenceMatrix(String path, int[][] matrix, int maxIter, long tSec) throws IOException {
        File file = new File(path);
        if (file.getParentFile() != null) {
            file.getParentFile().mkdirs();
        }
        int height = matrix.length;
        int width = (height > 0) ? matrix[0].length : 0;
        try (DataOutputStream out = new DataOutputStream(new BufferedOutputStream(new FileOutputStream(file)))) {
            out.writeInt(REFERENCE_MAGIC);
            out.writeInt(width);
            out.writeInt(height);
            out.writeInt(maxIter);
            for (int[] row : matrix) {
                for (int value : row) {
                    out.writeInt(value);
                }
            }
        }
        try (PrintWriter writer = new PrintWriter(path + ".tsec")) {
            writer.println(tSec);
        }
    }

    private static int[][] loadReferenceMatrix(String path, int width, int height, int maxIter) throws IOException {
        try (DataInputStream in = new DataInputStream(new BufferedInputStream(new FileInputStream(path)))) {
            int magic = in.readInt();
            if (magic != REFERENCE_MAGIC) {
                throw new IOException("Formato de matriz de referencia inválido.");
            }
            int storedWidth = in.readInt();
            int storedHeight = in.readInt();
            int storedMaxIter = in.readInt();
            if (storedWidth != width || storedHeight != height || storedMaxIter != maxIter) {
                throw new IOException("La matriz de referencia no coincide con la configuración solicitada.");
            }
            int[][] matrix = new int[height][width];
            for (int y = 0; y < height; y++) {
                for (int x = 0; x < width; x++) {
                    matrix[y][x] = in.readInt();
                }
            }
            return matrix;
        }
    }

    private static long readReferenceTime(String path) throws IOException {
        try (BufferedReader reader = new BufferedReader(new FileReader(path + ".tsec"))) {
            return Long.parseLong(reader.readLine().trim());
        }
    }
}
