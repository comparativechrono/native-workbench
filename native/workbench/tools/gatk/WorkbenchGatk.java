import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import java.util.zip.GZIPInputStream;
import htsjdk.samtools.*;
import htsjdk.samtools.reference.*;
import htsjdk.variant.vcf.*;
import htsjdk.variant.variantcontext.*;

/** Local-file orchestration only; all scientific calculations use unmodified GATK. */
public final class WorkbenchGatk {
    private final Path run, scratch, gatk;
    private final int memory;
    private final List<List<String>> commands = new ArrayList<>();
    private final Map<String,List<String>> options = new LinkedHashMap<>();
    private SAMSequenceDictionary referenceDictionary;
    private WorkbenchGatk(String[] args) throws Exception {
        if (args.length < 4) throw new IOException("Expected operation, run directory, Java heap MiB, and named inputs");
        run = Paths.get(args[1]).toAbsolutePath().normalize();
        memory = integer(args[2], 512, 65536, "Java heap MiB");
        Files.createDirectories(run);
        scratch = run.resolve("work"); Files.createDirectory(scratch);
        gatk = Paths.get(WorkbenchGatk.class.getProtectionDomain().getCodeSource().getLocation().toURI()).getParent().resolve("gatk-path-compat.jar");
        String key = null;
        for (int i=3; i<args.length; i++) {
            if (args[i].startsWith("--")) {
                key = args[i].substring(2);
                if (!Set.of("reference","bam","targets","sample","known-sites","gvcfs","gvcf","variants","ploidy","min-mapq","min-baseq","variant-type","filter-annotation","filter-comparison","filter-threshold","filter-name").contains(key) || options.containsKey(key))
                    throw new IOException("Unknown or repeated adapter option: " + key);
                options.put(key, new ArrayList<>());
            } else {
                if (key == null) throw new IOException("Expected named adapter option");
                options.get(key).add(args[i]);
            }
        }
        for (Map.Entry<String,List<String>> e : options.entrySet()) {
            if (e.getValue().isEmpty() || (!Set.of("known-sites","gvcfs").contains(e.getKey()) && e.getValue().size()!=1))
                throw new IOException("Invalid number of values for " + e.getKey());
        }
    }
    private String option(String key) throws IOException {
        if (!options.containsKey(key)) throw new IOException("Missing required option: " + key);
        return options.get(key).get(0);
    }
    private static int integer(String text, int min, int max, String label) throws IOException {
        try { int value=Integer.parseInt(text); if(value>=min && value<=max) return value; }
        catch (NumberFormatException ignored) {}
        throw new IOException(label + " must be an integer from " + min + " to " + max);
    }
    private static String quote(String s) {
        StringBuilder b=new StringBuilder("\"");
        for(char c:s.toCharArray()) switch(c) {
            case '"':b.append("\\\"");break;case '\\':b.append("\\\\");break;case '\n':b.append("\\n");break;case '\r':b.append("\\r");break;case '\t':b.append("\\t");break;
            default:if(c<32)b.append(String.format("\\u%04x",(int)c));else b.append(c);
        }
        return b.append('"').toString();
    }
    private void commandLog() throws IOException {
        List<String> rows=new ArrayList<>();
        for(List<String> command:commands) rows.add("[" + String.join(",",command.stream().map(WorkbenchGatk::quote).toList()) + "]");
        Files.writeString(run.resolve("commands.json"),"{\"schema\":1,\"commands\":["+String.join(",",rows)+"]}\n",StandardCharsets.UTF_8);
    }
    private void gatk(String tool, List<String> arguments, boolean picard) throws Exception {
        String java=Paths.get(System.getProperty("java.home"),"bin",System.getProperty("os.name").startsWith("Windows")?"java.exe":"java").toString();
        List<String> cmd=new ArrayList<>(List.of(java,"-Xms64m","-Xmx"+memory+"m","-XX:+ExitOnOutOfMemoryError","-XX:+DisableAttachMechanism","-XX:-UsePerfData",
            "-Djava.awt.headless=true","-Duser.language=en","-Duser.country=US","-Duser.timezone=UTC","-Dfile.encoding=UTF-8","-Djava.io.tmpdir="+scratch,
            "-Dsamjdk.use_jdk_inflater=true","-Dsamjdk.use_jdk_deflater=true","-Dsamjdk.use_libdeflate=false","-Dsamjdk.snappy.disable=true","-jar",gatk.toString(),tool));
        if(picard) cmd.addAll(List.of("--TMP_DIR",scratch.toString(),"--USE_JDK_INFLATER","true","--USE_JDK_DEFLATER","true"));
        else cmd.addAll(List.of("--tmp-dir",scratch.toString(),"--use-jdk-inflater","true","--use-jdk-deflater","true"));
        cmd.addAll(arguments); commands.add(List.copyOf(cmd)); commandLog();
        ProcessBuilder process=new ProcessBuilder(cmd).directory(run.toFile()).inheritIO();
        for(String name:List.of("JAVA_TOOL_OPTIONS","JDK_JAVA_OPTIONS","_JAVA_OPTIONS","CLASSPATH"))process.environment().remove(name);
        int code=process.start().waitFor();
        if(code!=0)throw new IOException("GATK " + tool + " failed with exit code " + code);
    }
    private static Path local(String value) throws IOException {
        if(value.matches("^[A-Za-z][A-Za-z0-9+.-]*:.*") && !value.matches("^[A-Za-z]:[\\\\/].*"))
            throw new IOException("Only explicitly selected local files are supported; URL inputs are not accepted");
        Path path=Paths.get(value).toAbsolutePath().normalize();
        if(!Files.isRegularFile(path) || !Files.isReadable(path))throw new IOException("Input is not a readable local file: " + path);
        return path;
    }
    private Path copy(String key,String name) throws IOException {
        Path path=local(option(key)), destination=scratch.resolve(name);
        Files.copy(path,destination); return destination;
    }
    private Path reference() throws Exception {
        Path ref=copy("reference","reference.fa");
        try(InputStream in=Files.newInputStream(ref)) {
            if(in.read()!='>')throw new IOException("Reference must be an uncompressed FASTA beginning with >");
        }
        FastaSequenceIndexCreator.create(ref,true);
        gatk("CreateSequenceDictionary",List.of("-R",ref.toString(),"-O",scratch.resolve("reference.dict").toString()),true);
        try(ReferenceSequenceFile reader=ReferenceSequenceFileFactory.getReferenceSequenceFile(ref)) {
            referenceDictionary=reader.getSequenceDictionary();
        }
        if(referenceDictionary==null || referenceDictionary.isEmpty())throw new IOException("Reference dictionary is empty");
        return ref;
    }
    private void dictionary(SAMSequenceDictionary dictionary,String label) throws IOException {
        if(dictionary==null || dictionary.isEmpty())throw new IOException(label + " must declare contig names and lengths");
        for(SAMSequenceRecord sequence:dictionary.getSequences()) {
            SAMSequenceRecord ref=referenceDictionary.getSequence(sequence.getSequenceName());
            if(ref==null || sequence.getSequenceLength()!=ref.getSequenceLength())throw new IOException(label + " contig/length differs from selected reference: " + sequence.getSequenceName());
            String a=sequence.getMd5(),b=ref.getMd5();
            if(a!=null && b!=null && !a.equalsIgnoreCase(b))throw new IOException(label + " reference MD5 differs: " + sequence.getSequenceName());
        }
    }
    private Set<String> bamSamples(Path path,boolean reference,boolean matchSample) throws IOException {
        try(SamReader reader=SamReaderFactory.makeDefault().validationStringency(ValidationStringency.STRICT).open(path)) {
            SAMFileHeader header=reader.getFileHeader();
            if(header.getSortOrder()!=SAMFileHeader.SortOrder.coordinate)throw new IOException("BAM must declare coordinate sorting");
            if(reference) dictionary(header.getSequenceDictionary(),"BAM");
            Set<String> samples=new HashSet<>();
            for(SAMReadGroupRecord group:header.getReadGroups()) {
                if(group.getSample()==null || !group.getSample().matches("[A-Za-z0-9_.-]+"))throw new IOException("Every BAM read group needs an ASCII SM sample identifier");
                samples.add(group.getSample());
            }
            if(samples.size()!=1)throw new IOException("This operation requires one sample in the BAM read-group SM labels");
            if(matchSample && !samples.contains(option("sample")))throw new IOException("Selected sample name does not match BAM read-group SM");
            return samples;
        }
    }
    private void indexBam(Path bam,Path index) throws IOException {
        try(SamReader reader=SamReaderFactory.makeDefault().validationStringency(ValidationStringency.STRICT).enable(SamReaderFactory.Option.INCLUDE_SOURCE_IN_RECORDS).open(bam)) {
            BAMIndexer indexer=new BAMIndexer(index,reader.getFileHeader());
            for(SAMRecord record:reader) {
                // GATK otherwise silently drops missing-RG records as malformed,
                // even when the header declares one valid sample and HTSJDK is STRICT.
                if(record.getReadGroup()==null)throw new IOException("Every BAM record requires an RG tag resolving to a declared read group: " + record.getReadName());
                indexer.processAlignment(record);
            }
            indexer.finish();
        }
    }
    private Path bam(boolean withReference,boolean sample) throws IOException {
        Path bam=copy("bam","input.bam");bamSamples(bam,withReference,sample);indexBam(bam,scratch.resolve("input.bai"));return bam;
    }
    private Path targets() throws IOException {
        Path bed=copy("targets","targets.bed");long count=0;
        try(BufferedReader in=Files.newBufferedReader(bed,StandardCharsets.UTF_8)) {
            String line;while((line=in.readLine())!=null) {
                if(line.isBlank() || line.startsWith("#") || line.startsWith("track ") || line.startsWith("browser "))continue;
                String[] fields=line.split("\t");if(fields.length<3)throw new IOException("Calling intervals require tab-separated BED3 columns");
                SAMSequenceRecord ref=referenceDictionary.getSequence(fields[0]);
                try { long start=Long.parseLong(fields[1]),end=Long.parseLong(fields[2]);
                    if(ref==null || start<0 || end<=start || end>ref.getSequenceLength())throw new IOException("BED interval is outside selected reference bounds");
                } catch(NumberFormatException error) {throw new IOException("BED start/end must be integers");}
                count++;
            }
        }
        if(count==0)throw new IOException("Calling intervals contain no BED records");return bed;
    }
    private Path stageVcf(String value,String name,boolean gvcf,Set<String> sampleNames) throws Exception {
        Path input=local(value),out=scratch.resolve(name);
        try(InputStream source=Files.newInputStream(input);BufferedInputStream buffer=new BufferedInputStream(source)) {
            buffer.mark(2);int a=buffer.read(),b=buffer.read();buffer.reset();
            try(InputStream data=a==31&&b==139?new GZIPInputStream(buffer):buffer) {Files.copy(data,out);}
        }
        long records=0;boolean likelihoods=false;
        try(VCFFileReader reader=new VCFFileReader(out,false)) {
            VCFHeader header=reader.getFileHeader();dictionary(header.getSequenceDictionary(),"VCF");
            if(gvcf) {
                if(header.getNGenotypeSamples()==0 || header.getFormatHeaderLine("GT")==null || header.getFormatHeaderLine("PL")==null)
                    throw new IOException("GATK gVCF requires sample genotypes and PL likelihood declarations; ordinary VCF is not a gVCF");
                boolean nonRefHeader=header.getMetaDataInInputOrder().stream().anyMatch(x->x.toString().startsWith("ALT=<ID=NON_REF,"));
                if(!nonRefHeader)throw new IOException("GATK gVCF must declare the NON_REF symbolic allele");
                for(String sample:header.getGenotypeSamples()) {
                    if(!sample.matches("[A-Za-z0-9_.-]+"))throw new IOException("gVCF sample names must be ASCII identifiers");
                    if(!sampleNames.add(sample))throw new IOException("gVCF inputs repeat a sample name: " + sample);
                }
            }
            for(VariantContext record:reader) {
                boolean nonRef=record.getAlternateAlleles().stream().anyMatch(x->x.getDisplayString().equals("<NON_REF>") || x.getDisplayString().equals("<*>"));
                if(gvcf && !nonRef)throw new IOException("Every GATK gVCF record must retain NON_REF reference-confidence likelihoods");
                if(!gvcf && nonRef)throw new IOException("This operation needs ordinary VCF calls; genotype the gVCF first");
                for(Genotype gt:record.getGenotypes())if(gt.hasPL())likelihoods=true;
                records++;
            }
        }
        if(gvcf && (records==0 || !likelihoods))throw new IOException("GATK gVCF must contain reference-confidence records with PL likelihoods");
        gatk("IndexFeatureFile",List.of("-I",out.toString()),false);return out;
    }
    private List<Path> vcfs(String key,boolean gvcf,int minimum) throws Exception {
        List<String> values=options.get(key);
        if(values==null || values.size()<minimum || values.size()>32)throw new IOException(key+" requires "+minimum+" to 32 explicitly selected files");
        List<Path> original=new ArrayList<>(),staged=new ArrayList<>();Set<String> samples=new HashSet<>();
        for(String value:values) {
            Path path=local(value);for(Path previous:original)if(Files.isSameFile(path,previous))throw new IOException("Repeated physical input file: "+path);
            original.add(path);staged.add(stageVcf(value,key+"-"+original.size()+".vcf",gvcf,samples));
        }
        return staged;
    }
    private void bamSummary(Path bam) throws IOException {
        long records=0,duplicates=0,mapped=0;long[] quality=new long[256];
        try(SamReader reader=SamReaderFactory.makeDefault().validationStringency(ValidationStringency.STRICT).open(bam)) {
            for(SAMRecord record:reader) {
                records++;if(record.getDuplicateReadFlag())duplicates++;if(!record.getReadUnmappedFlag())mapped++;
                for(byte q:record.getBaseQualities())quality[Byte.toUnsignedInt(q)]++;
            }
        }
        List<String> histogram=new ArrayList<>();for(int i=0;i<quality.length;i++)if(quality[i]>0)histogram.add(quote(Integer.toString(i))+": "+quality[i]);
        Files.writeString(run.resolve("bam-summary.json"),"{\"records\": "+records+",\"duplicates\": "+duplicates+",\"mapped\": "+mapped+",\"baseQualityHistogram\": {"+String.join(",",histogram)+"}}\n",StandardCharsets.UTF_8);
    }
    private static List<String> args(String... values) {return new ArrayList<>(List.of(values));}
    private void run(String operation) throws Exception {
        if(operation.equals("mark-duplicates")) {
            Path bam=bam(false,false),output=run.resolve("output.bam");
            gatk("MarkDuplicates",args("-I",bam.toString(),"-O",output.toString(),"-M",run.resolve("duplicate-metrics.txt").toString(),"--CREATE_INDEX","false","--VALIDATION_STRINGENCY","STRICT","--REMOVE_DUPLICATES","false","--READ_NAME_REGEX","null"),true);
            indexBam(output,run.resolve("output.bam.bai"));bamSummary(output);
        } else {
            Path ref=reference();
            if(operation.equals("bqsr")) {
                Path bam=bam(true,true),bed=targets();List<Path> known=vcfs("known-sites",false,1);
                List<String> a=args("-R",ref.toString(),"-I",bam.toString(),"-L",bed.toString(),"-O",run.resolve("recalibration.table").toString());
                for(Path path:known)a.addAll(List.of("--known-sites",path.toString()));gatk("BaseRecalibrator",a,false);
                Path output=run.resolve("output.bam");
                gatk("ApplyBQSR",args("-R",ref.toString(),"-I",bam.toString(),"--bqsr-recal-file",run.resolve("recalibration.table").toString(),"-O",output.toString(),"--create-output-bam-index","false"),false);
                indexBam(output,run.resolve("output.bam.bai"));bamSummary(output);
            } else if(operation.startsWith("haplotypecaller-")) {
                if(!Set.of("haplotypecaller-vcf","haplotypecaller-gvcf").contains(operation))throw new IOException("Unknown HaplotypeCaller operation");
                Path bam=bam(true,true),bed=targets();boolean gvcf=operation.endsWith("-gvcf");
                List<String> a=args("-R",ref.toString(),"-I",bam.toString(),"-L",bed.toString(),"-O",run.resolve(gvcf?"output.g.vcf":"variants.vcf").toString(),
                    "--pair-hmm-implementation","LOGLESS_CACHING","--smith-waterman","JAVA","--sample-ploidy",Integer.toString(integer(option("ploidy"),1,32,"Ploidy")),
                    "--minimum-mapping-quality",Integer.toString(integer(option("min-mapq"),0,60,"Mapping quality")),"--min-base-quality-score",Integer.toString(integer(option("min-baseq"),6,93,"Base quality")),
                    "--create-output-variant-index","false","--add-output-vcf-command-line","false");
                if(gvcf)a.addAll(List.of("-ERC","GVCF"));gatk("HaplotypeCaller",a,false);
            } else if(operation.equals("combine-gvcfs")) {
                List<String> a=args("-R",ref.toString(),"-O",run.resolve("output.g.vcf").toString(),"--create-output-variant-index","false","--add-output-vcf-command-line","false");
                for(Path input:vcfs("gvcfs",true,2))a.addAll(List.of("-V",input.toString()));gatk("CombineGVCFs",a,false);
            } else {
                boolean genotype=operation.equals("genotype-gvcfs");
                Path input=stageVcf(option(genotype?"gvcf":"variants"),"variants-input.vcf",genotype,new HashSet<>());
                List<String> a=args("-R",ref.toString(),"-V",input.toString());
                if(operation.equals("validate-variants")) {
                    // Without dbSNP, exclude only the ID membership check; retain reference, allele and count checks.
                    a.addAll(List.of("--validation-type-to-exclude","IDS"));gatk("ValidateVariants",a,false);
                    Files.writeString(run.resolve("validation.json"),"{\"valid\": true,\"referenceAllelesChecked\":true,\"idsCheckedAgainstDbSnp\":false}\n",StandardCharsets.UTF_8);
                } else {
                    a.addAll(List.of("-O",run.resolve("variants.vcf").toString(),"--create-output-variant-index","false","--add-output-vcf-command-line","false"));
                    if(genotype)gatk("GenotypeGVCFs",a,false);
                    else if(operation.equals("select-variants")) {
                        String type=option("variant-type");if(!Set.of("ALL","SNP","INDEL").contains(type))throw new IOException("Variant type must be ALL, SNP or INDEL");
                        if(!type.equals("ALL"))a.addAll(List.of("--select-type-to-include",type));gatk("SelectVariants",a,false);
                    } else if(operation.equals("variant-filtration")) {
                        String annotation=option("filter-annotation"),comparison=option("filter-comparison"),thresholdText=option("filter-threshold"),name=option("filter-name");
                        if(!Set.of("QUAL","QD","FS","SOR","MQ","MQRankSum","ReadPosRankSum","DP").contains(annotation))throw new IOException("Unsupported filter annotation");
                        if(!Set.of("lt","gt").contains(comparison))throw new IOException("Filter comparison must be lt or gt");
                        if(!name.matches("[A-Za-z][A-Za-z0-9_.-]{0,49}") || Set.of("PASS",".").contains(name))throw new IOException("Filter name must be a distinct ASCII identifier, not PASS");
                        if(thresholdText.length()>64 || !thresholdText.matches("[+-]?(?:[0-9]+(?:\\.[0-9]*)?|\\.[0-9]+)"))throw new IOException("Filter threshold must be a finite decimal number");
                        java.math.BigDecimal threshold=new java.math.BigDecimal(thresholdText);
                        if(threshold.abs().compareTo(new java.math.BigDecimal("1000000000000"))>0)throw new IOException("Filter threshold exceeds supported bound");
                        a.addAll(List.of("--filter-name",name,"--filter-expression",annotation+(comparison.equals("lt")?" < ":" > ")+threshold.toPlainString(),"--missing-values-evaluate-as-failing","true"));gatk("VariantFiltration",a,false);
                    } else throw new IOException("Unknown operation: "+operation);
                }
            }
        }
        Files.writeString(run.resolve("input-validation.json"),"{\"valid\": true,\"operation\":"+quote(operation)+",\"localInputsOnly\":true}\n",StandardCharsets.UTF_8);
        commandLog();
    }
    public static void main(String[] args) {
        try {new WorkbenchGatk(args).run(args[0]);}
        catch(Exception e) {System.err.println("GATK Workbench: "+e.getMessage());System.exit(1);}
    }
}
