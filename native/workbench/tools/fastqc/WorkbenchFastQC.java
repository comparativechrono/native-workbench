/* Copyright (c) 2026 Native Workbench contributors. MIT licensed; see repository LICENSE.
 * Fixed local adapter. Upstream FastQC classes and algorithms are unmodified.
 */
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import java.util.zip.*;

public final class WorkbenchFastQC {
    private static final String VERSION = "0.13.0";
    private static final long MAX_REPORT_TEXT = 64L * 1024 * 1024;

    private static int integer(String text, int lo, int hi, String label) throws IOException {
        try { int n = Integer.parseInt(text); if (n >= lo && n <= hi) return n; }
        catch (NumberFormatException ignored) { }
        throw new IOException("Invalid " + label + "; expected " + lo + ".." + hi);
    }

    private static BufferedReader reader(Path path) throws IOException {
        BufferedInputStream raw = new BufferedInputStream(Files.newInputStream(path));
        raw.mark(2); int a = raw.read(), b = raw.read(); raw.reset();
        InputStream in;
        try { in = a == 31 && b == 139 ? new GZIPInputStream(raw) : raw; }
        catch (IOException e) { raw.close(); throw e; }
        return new BufferedReader(new InputStreamReader(in, StandardCharsets.US_ASCII.newDecoder()));
    }

    private static String[] record(BufferedReader in, long n, int offset) throws IOException {
        String header = in.readLine(); if (header == null) return null;
        String seq = in.readLine(), plus = in.readLine(), quality = in.readLine();
        if (!header.startsWith("@") || header.length() < 2 || Character.isWhitespace(header.charAt(1)) || seq == null || seq.isEmpty()
                || plus == null || !plus.startsWith("+") || quality == null || seq.length() != quality.length())
            throw new IOException("Invalid four-line FASTQ record " + n);
        for (int i = 0; i < seq.length(); i++) {
            if ("ACGTUNRYKMSWBDHVacgtunrykmswbdhv".indexOf(seq.charAt(i)) < 0)
                throw new IOException("Unsupported FASTQ base in record " + n);
            if (quality.charAt(i) < offset || quality.charAt(i) > 126)
                throw new IOException("Quality outside the selected Phred+" + offset + " encoding in record " + n);
        }
        return new String[]{header.substring(1), seq};
    }

    private static String identity(String header, int mate) throws IOException {
        String[] parts = header.split("\\s+", 2);
        String id = parts[0];
        if (id.endsWith("/1") || id.endsWith("/2")) {
            if (!id.endsWith("/" + mate)) throw new IOException("FASTQ mate suffix disagrees with selected read " + mate);
            id = id.substring(0, id.length() - 2);
        }
        if (id.isEmpty()) throw new IOException("FASTQ record has no mate identifier");
        if (parts.length > 1 && parts[1].matches("[12]:.*") && !parts[1].startsWith(mate + ":"))
            throw new IOException("FASTQ CASAVA mate indicator disagrees with selected read " + mate);
        return id;
    }

    private static long[] validate(Path first, Path second, int offset) throws IOException {
        long records = 0, bases1 = 0, bases2 = 0;
        try (BufferedReader a = reader(first); BufferedReader b = second == null ? null : reader(second)) {
            while (true) {
                String[] x = record(a, records + 1, offset), y = b == null ? null : record(b, records + 1, offset);
                if (b != null && (x == null) != (y == null)) throw new IOException("Mate files have different record counts");
                if (x == null) break;
                if (b != null && !identity(x[0], 1).equals(identity(y[0], 2)))
                    throw new IOException("Mate identifiers or order differ at record " + (records + 1));
                records++; bases1 += x[1].length(); if (y != null) bases2 += y[1].length();
            }
        }
        if (records == 0) throw new IOException("FASTQ input has no records");
        return new long[]{records, bases1, bases2};
    }

    private static String extract(ZipFile archive, String suffix, Path target) throws IOException {
        ZipEntry selected = null;
        Enumeration<? extends ZipEntry> entries = archive.entries();
        while (entries.hasMoreElements()) {
            ZipEntry e = entries.nextElement();
            if (!e.isDirectory() && e.getName().endsWith("/" + suffix)) {
                if (selected != null) throw new IOException("Ambiguous FastQC result: " + suffix);
                selected = e;
            }
        }
        if (selected == null || selected.getSize() > MAX_REPORT_TEXT) throw new IOException("Missing/oversized FastQC result: " + suffix);
        ByteArrayOutputStream data = new ByteArrayOutputStream();
        try (InputStream in = archive.getInputStream(selected)) {
            byte[] buffer = new byte[65536]; int n;
            while ((n = in.read(buffer)) != -1) {
                if ((long)data.size() + n > MAX_REPORT_TEXT) throw new IOException("Oversized FastQC result: " + suffix);
                data.write(buffer, 0, n);
            }
        }
        Files.write(target, data.toByteArray(), StandardOpenOption.CREATE_NEW);
        return new String(data.toByteArray(), StandardCharsets.UTF_8).replace("\r\n", "\n");
    }

    private static void analyze(Path input, Path output, int threads, int memory, int offset, long count) throws Exception {
        Files.createDirectories(output);
        Path scratch = output.resolve("upstream"); Files.createDirectory(scratch);
        String java = Paths.get(System.getProperty("java.home"), "bin", System.getProperty("os.name").startsWith("Windows") ? "java.exe" : "java").toString();
        List<String> command = new ArrayList<String>(Arrays.asList(java, "-Xms64m", "-Xmx" + memory + "m",
                "-XX:+ExitOnOutOfMemoryError", "-XX:+DisableAttachMechanism", "-XX:-UsePerfData", "-XX:ParallelGCThreads=1",
                "-Djava.awt.headless=true", "-Duser.language=en", "-Duser.country=US", "-Duser.timezone=UTC", "-Dfile.encoding=UTF-8",
                "-Djava.io.tmpdir=" + scratch, "-Dfastqc.output_dir=" + scratch, "-Dfastqc.sequence_format=fastq",
                "-Dfastqc.threads=" + threads, "-Dfastqc.unzip=false", "-Dfastqc.phred64=" + (offset == 64),
                "-cp", System.getProperty("java.class.path"), "uk.ac.babraham.FastQC.FastQCApplication", input.toString()));
        ProcessBuilder builder = new ProcessBuilder(command).inheritIO();
        for (String name : Arrays.asList("JAVA_TOOL_OPTIONS", "JDK_JAVA_OPTIONS", "_JAVA_OPTIONS", "CLASSPATH")) builder.environment().remove(name);
        int status = builder.start().waitFor();
        if (status != 0) throw new IOException("FastQC failed with exit code " + status);
        Path html = null, zip = null;
        try (DirectoryStream<Path> files = Files.newDirectoryStream(scratch)) {
            for (Path p : files) {
                if (p.getFileName().toString().endsWith("_fastqc.html")) { if (html != null) throw new IOException("Multiple HTML results"); html = p; }
                if (p.getFileName().toString().endsWith("_fastqc.zip")) { if (zip != null) throw new IOException("Multiple ZIP results"); zip = p; }
            }
        }
        if (html == null || zip == null || Files.size(html) == 0 || Files.size(zip) == 0) throw new IOException("FastQC did not produce complete reports");
        try (ZipFile report = new ZipFile(zip.toFile())) {
            String data = extract(report, "fastqc_data.txt", output.resolve("fastqc_data.txt"));
            extract(report, "summary.txt", output.resolve("summary.txt"));
            if (!data.startsWith("##FastQC\t" + VERSION + "\n") || !data.contains("\nTotal Sequences\t" + count + "\n"))
                throw new IOException("FastQC version/read count differs from validated input");
        }
        Files.move(html, output.resolve("fastqc.html"));
        Files.move(zip, output.resolve("fastqc.zip"));
        Files.delete(scratch);
    }

    public static void main(String[] args) {
        try {
            if (args.length != 7 || !(args[0].equals("single") || args[0].equals("paired")))
                throw new IOException("Expected single|paired, reads1, reads2|-, output, threads, heap-MiB, quality-offset");
            Path first = Paths.get(args[1]).toAbsolutePath(), second = args[0].equals("paired") ? Paths.get(args[2]).toAbsolutePath() : null;
            // Upstream interprets ANY basename beginning with "stdin" as a stream
            // sentinel, even when a real selected file exists. Reject before reading
            // or launching rather than risking inherited stdin or a hidden data copy.
            for (Path path : second == null ? new Path[]{first} : new Path[]{first, second}) {
                if (path.getFileName().toString().startsWith("stdin"))
                    throw new IOException("FastQC reserves filenames beginning with 'stdin'. Rename the selected FASTQ file before running: " + path.getFileName());
            }
            Path out = Paths.get(args[3]).toAbsolutePath();
            int threads = integer(args[4], 1, 4, "threads"), memory = integer(args[5], 512, 16384, "Java heap MiB"), offset = Integer.parseInt(args[6]);
            if (offset != 33 && offset != 64) throw new IOException("Quality offset must be 33 or 64");
            if (second != null && Files.isSameFile(first, second)) throw new IOException("Mate inputs must be different files");
            long[] truth = validate(first, second, offset);
            Files.createDirectories(out);
            analyze(first, out.resolve("read1"), threads, memory, offset, truth[0]);
            if (second != null) analyze(second, out.resolve("read2"), threads, memory, offset, truth[0]);
            String text = "{\"valid\":true,\"recordsPerFile\":" + truth[0] + ",\"files\":" + (second == null ? 1 : 2)
                    + ",\"bases1\":" + truth[1] + ",\"bases2\":" + truth[2] + ",\"qualityOffset\":" + offset + "}\n";
            Files.write(out.resolve("input-validation.json"), text.getBytes(StandardCharsets.UTF_8), StandardOpenOption.CREATE_NEW);
        } catch (Exception e) { System.err.println("FastQC workbench: " + e.getMessage()); System.exit(1); }
    }
}
