"""Executable regression tests for the one-method GATK local-path adaptation."""
import hashlib
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('build_mutect2_compat', ROOT/'scripts/build_mutect2_compat.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)
PROBE = r'''
import java.lang.reflect.Proxy;
import java.nio.file.*;
import java.net.URI;
import java.util.Map;
import org.broadinstitute.hellbender.utils.io.IOUtils;
import org.broadinstitute.hellbender.Main;
public final class WorkbenchPathProbe {
  static void check(boolean value, String message) { if (!value) throw new AssertionError(message); }
  static Path syntheticLocal(String value, String uri) {
    final Path[] holder = new Path[1];
    holder[0] = (Path)Proxy.newProxyInstance(WorkbenchPathProbe.class.getClassLoader(), new Class<?>[]{Path.class},
      (proxy, method, arguments) -> {
        switch (method.getName()) {
          case "getFileSystem": return FileSystems.getDefault();
          case "toAbsolutePath": return holder[0];
          case "toString": return value;
          case "toUri": return URI.create(uri);
          default: throw new UnsupportedOperationException(method.getName());
        }
      });
    return holder[0];
  }
  public static void main(String[] arguments) throws Exception {
    Path root = Path.of(arguments[0]).toAbsolutePath();
    Path local = root.resolve("spaces and caf\u00e9");
    Files.createDirectory(local);
    check(IOUtils.getAbsolutePathWithoutFileProtocol(local).equals(local.toString()), "Space/Unicode local path changed");
    String drive = "C:\\Users\\Work User\\caf\u00e9";
    check(IOUtils.getAbsolutePathWithoutFileProtocol(syntheticLocal(drive,"file:///C:/Users/Work%20User/caf%C3%A9")).equals(drive), "Drive syntax changed");
    String unc = "\\\\server\\share\\Work User";
    check(IOUtils.getAbsolutePathWithoutFileProtocol(syntheticLocal(unc,"file://server/share/Work%20User")).equals(unc), "UNC syntax changed");
    URI zipUri = URI.create("jar:" + root.resolve("nonlocal spaces.zip").toUri());
    try (FileSystem zip = FileSystems.newFileSystem(zipUri,Map.of("create","true"))) {
      Path entry = zip.getPath("/space and caf\u00e9");
      String expected = entry.toAbsolutePath().toUri().toString().replaceFirst("^file://", "");
      check(IOUtils.getAbsolutePathWithoutFileProtocol(entry).equals(expected), "Non-file provider behavior changed");
    }
    Path ioOrigin=Path.of(IOUtils.class.getProtectionDomain().getCodeSource().getLocation().toURI());
    Path mainOrigin=Path.of(Main.class.getProtectionDomain().getCodeSource().getLocation().toURI());
    check(ioOrigin.equals(root.resolve("gatk-path-compat.jar")), "Patched IOUtils not first: " + ioOrigin);
    check(mainOrigin.equals(root.resolve("gatk.jar")), "Main not from original GATK: " + mainOrigin);
    System.out.println("PASS local spaces/Unicode; synthetic Windows drive/UNC; non-file URI; patched IOUtils and original Main origins");
  }
}
'''


class Mutect2PathCompatibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.artifact = ROOT/'build/mutect2/path-compat/gatk-path-compat.jar'
        cls.original = ROOT/'vendor-expanded/gatk/gatk-package-4.7.0.0-local.jar'
        cls.jdk = ROOT/'vendor-expanded/gatk-compat/jdk-17.0.20.1+1'
        for file in [cls.artifact,cls.original,cls.jdk/'bin/javac']:
            if not file.is_file(): raise RuntimeError('Required pinned build input missing: '+str(file))

    def test_manifest_and_class_scope_preserve_original_launcher(self):
        with zipfile.ZipFile(self.artifact) as patch,zipfile.ZipFile(self.original) as original:
            manifest=patch.read('META-INF/MANIFEST.MF')
            expected=original.read('META-INF/MANIFEST.MF').rstrip(b'\r\n')+b'\r\nClass-Path: gatk.jar\r\n\r\n'
            self.assertEqual(manifest,expected)
            self.assertEqual(patch.namelist(),['META-INF/MANIFEST.MF','org/broadinstitute/hellbender/utils/io/IOUtils.class'])
            self.assertEqual(int.from_bytes(patch.read(patch.namelist()[1])[6:8],'big'),61)
        self.assertEqual(builder.digest(self.original),builder.ORIGINAL_JAR_SHA256)

    def test_local_paths_nonlocal_uris_and_class_origins(self):
        with tempfile.TemporaryDirectory(prefix='path probe caf\u00e9 ',dir=ROOT/'build/mutect2') as directory:
            root=Path(directory)
            shutil.copy2(self.artifact,root/'gatk-path-compat.jar')
            os.link(self.original,root/'gatk.jar')
            source=root/'WorkbenchPathProbe.java';source.write_text(PROBE,encoding='utf-8')
            env=dict(os.environ,LD_LIBRARY_PATH=str(self.jdk/'lib')+':'+str(self.jdk/'lib/server'))
            compiled=subprocess.run([str(self.jdk/'bin/javac'),'--release','17','-encoding','UTF-8','-proc:none','-cp',str(self.artifact)+':'+str(self.original),str(source)],env=env,capture_output=True,text=True)
            self.assertEqual(compiled.returncode,0,compiled.stdout+compiled.stderr)
            result=subprocess.run([str(self.jdk/'bin/java'),'-cp',str(root/'gatk-path-compat.jar')+':'+str(root),'WorkbenchPathProbe',str(root)],env=env,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn('PASS local spaces/Unicode',result.stdout)

    def test_build_is_byte_reproducible(self):
        with tempfile.TemporaryDirectory(prefix='compat-rebuild-',dir=ROOT/'build/mutect2') as directory:
            artifact=builder.build(Path(directory)/'rebuild')
            self.assertEqual(builder.digest(artifact),builder.digest(self.artifact))


if __name__=='__main__':unittest.main()
