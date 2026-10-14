/* The parity suite: commands that between them cross every point where the shell, the terminal and the rest of the
   page meet the programs – running a program, its output into a pipe, a file or the screen; < FILE; blocks, functions
   and loops reading program output; the shell's own commands writing bytes; copies and moves of program-written
   files; the programs that run in a worker of their own (featureCounts, Salmon, PLINK 2, Cutadapt, MACS3, Prodigal,
   HMMER, bustools, LoFreq), the workflows (Kraken2, Strelka2); and forced stops. The steps are run in order in one
   page: later steps use what earlier ones made. Outputs are compared between two versions of the workbench, not
   with fixed expected values (see compare.mjs).
   own: the step needs a program that runs in a worker of its own in the browser (not in the local runner yet);
   allPrograms: a forced stop of the browser's shared program worker, which loses the programs' files (the local
   runner stops one run, and loses nothing). run-suite.mjs --subset local leaves both out. */
const EX = '/data/examples';

/* Files that carry the time of the run: compared by kind and permissions only (compare.mjs). What else is in them is
   checked by the step that makes them, through its output. */
export const timeStamped = [
  [/\/strelka_run\/results\/variants\/somatic\.(snvs|indels)\.vcf\.gz(\.tbi)?$/, "Strelka2's ##startTime header line (compressed: the size changes too)"],
  [/\/strelka_run\/results\/stats\/runStats\.tsv$/, "Strelka2's wall-clock time (TotalHours)"]
];

export const suite = [
  // ---- the shell's own commands, text files, redirections
  { id: 'setup', cmd: 'cd ~ && mkdir -p t && cd t && pwd' },
  { id: 'printf-redirect', cmd: "printf 'b\\na\\nc\\na\\n' > a.txt && cat a.txt" },
  { id: 'stdin-from-file', cmd: 'sort < a.txt' },
  { id: 'program-pipes', cmd: 'sort a.txt | uniq -c | sort -k1,1nr -k2' },
  { id: 'builtin-into-program', cmd: 'echo hello | tr a-z A-Z' },
  { id: 'program-into-read-loop', cmd: 'seq 1 5 | while read x; do echo "n=$x"; done' },
  { id: 'program-into-builtin', cmd: 'seq 3 | tac' },
  { id: 'pipe-into-block', cmd: 'seq 10 | { head -n 2; tail -n 1; }' },
  { id: 'file-into-block', cmd: '{ head -n 1; sort; } < a.txt' },
  { id: 'script-from-pipe', cmd: 'echo "echo from-stdin; seq 2" | bash' },
  { id: 'source-from-pipe', cmd: "echo 'echo sourced-from-pipe' | source /dev/stdin" },
  { id: 'mapfile-psub', cmd: 'mapfile -t arr < <(seq 3); echo "${#arr[@]} ${arr[2]}"' },
  { id: 'read-from-program', cmd: 'read -r first < <(sort a.txt); echo "first=$first"; seq 4 | { read -r one; echo "one=$one"; cat; }' },
  { id: 'wc-file-vs-pipe', cmd: 'wc < a.txt; cat a.txt | wc' },
  { id: 'stderr-redirects', cmd: 'ls nosuch 2> err.txt; cat err.txt; ls nosuch 2>&1 | wc -l' },
  { id: 'stdout-stderr-order', cmd: 'grep -c a a.txt nosuch.txt; echo status=$?' },
  { id: 'merge-into-file', cmd: 'grep -c a a.txt nosuch.txt > both.txt 2>&1; cat both.txt' },
  { id: 'cat-same-file', cmd: 'cat a.txt a.txt >> a2.txt; cat a2.txt a2.txt >> a2.txt; echo s=$?; wc -l a2.txt' },
  { id: 'cat-input-is-output', cmd: 'cp a.txt d.txt; cat < d.txt >> d.txt; echo s=$?; wc -l < d.txt; wc -l < <(cat d.txt d.txt)' },
  { id: 'tee-dev-stdout', cmd: 'seq 3 | tee /dev/stdout copy3.txt | wc -l; cat copy3.txt' },
  // ---- a large text file (kept as the programs' bytes, not as text in the page)
  { id: 'large-file', cmd: 'seq 1 100000 > big.txt && wc -l big.txt && tac big.txt | head -2' },
  { id: 'large-sorted-redirect', cmd: 'sort -rn big.txt > sorted.txt; head -2 sorted.txt; sort -n big.txt >> sorted.txt; wc -l sorted.txt' },
  { id: 'copy-move-held', cmd: 'cp big.txt big2.txt && mv big2.txt big3.txt && wc -c big3.txt && cmp big.txt big3.txt && echo same' },
  { id: 'remove-held', cmd: 'rm big3.txt; ls' },
  { id: 'read-held-builtins', cmd: 'head -c 20 sorted.txt | od -c | head -2; nl big.txt | tail -1; md5sum big.txt' },
  // ---- gzip and its relatives (done by bgzip)
  { id: 'gzip-keep', cmd: 'gzip -k a.txt && ls && zcat a.txt.gz' },
  { id: 'zcat-two', cmd: 'cp a.txt.gz b.txt.gz && zcat a.txt.gz b.txt.gz | wc -l' },
  { id: 'zgrep', cmd: 'zgrep -c a a.txt.gz; zgrep -c a < a.txt.gz' },
  { id: 'gunzip-c', cmd: 'gunzip -c a.txt.gz | sort -u' },
  { id: 'gzip-file', cmd: 'cp a.txt c.txt && gzip c.txt && ls c.txt* && gunzip c.txt.gz && cat c.txt' },
  // ---- the shell's own commands that write bytes (split, truncate)
  { id: 'split', cmd: 'split -l 2 a.txt part_ && ls part_* && cat part_ab' },
  { id: 'truncate', cmd: 'cp big.txt cut.txt && truncate -s 10 cut.txt && od -c cut.txt' },
  { id: 'dates', cmd: 'date -d "2024-03-05 12:00" +%Y-%m-%d && touch -d "2024-01-02 03:04:05" stamp.txt && date -r stamp.txt +%Y-%m-%d' },
  // ---- reads, a reference, SAM and BAM
  { id: 'faidx', cmd: `cp ${EX}/reads/reference.fa . && samtools faidx reference.fa && cat reference.fa.fai` },
  { id: 'minimap2', cmd: `minimap2 -ax sr reference.fa ${EX}/reads/NA12878_R1.fastq ${EX}/reads/NA12878_R2.fastq > mapped.sam 2> mm.log; echo code=$?; grep -c . mapped.sam` },
  { id: 'sort-index-flagstat', cmd: 'samtools sort -o mapped.bam mapped.sam && samtools index mapped.bam && samtools flagstat mapped.bam' },
  { id: 'bam-pipe', cmd: 'samtools view -b mapped.bam | samtools view -c -' },
  { id: 'bam-redirect', cmd: 'samtools view -b mapped.bam > copy.bam; samtools view -c copy.bam; cmp mapped.bam copy.bam; echo cmp=$?' },
  { id: 'bam-stdin-file', cmd: 'samtools view -c - < copy.bam' },
  { id: 'bam-into-block', cmd: 'samtools view -b mapped.bam | { samtools view -c -; }' },
  { id: 'function-bytes-pipe', cmd: 'f() { samtools view -b mapped.bam; }; f | samtools view -c -' },
  { id: 'block-bytes-file', cmd: '{ samtools view -b mapped.bam; } > blk.bam; samtools view -c blk.bam' },
  { id: 'bam-to-screen', cmd: 'samtools view -b mapped.bam' },
  { id: 'sam-head', cmd: 'samtools view mapped.bam | head -3 | cut -f1-6' },
  { id: 'bcftools-call', cmd: 'bcftools mpileup -f reference.fa mapped.bam 2>/dev/null | bcftools call -mv -Oz -o calls.vcf.gz 2>/dev/null; bcftools view -H calls.vcf.gz | cut -f1-5 | head -5' },
  { id: 'bgzip-tabix', cmd: 'bgzip -c reference.fa > ref.fa.gz && zcat ref.fa.gz | head -1 && tabix -p vcf calls.vcf.gz && ls calls.vcf.gz*' },
  { id: 'read-in-loop-program', cmd: 'while read -r name len rest; do echo "$name $len"; samtools faidx reference.fa "$name:1-10" | tail -1; done < reference.fa.fai' },
  { id: 'bowtie2', cmd: `bowtie2-build -q reference.fa ref > /dev/null && bowtie2 -x ref -1 ${EX}/reads/NA12878_R1.fastq -2 ${EX}/reads/NA12878_R2.fastq -S bt2.sam 2> bt2.log; tail -1 bt2.log; samtools view -c bt2.sam` },
  // ---- RNA-seq: hisat2 (its wrapper unpacks .gz reads through pipe files), featureCounts (threads), salmon (threads)
  { id: 'hisat2-build', cmd: `hisat2-build -q ${EX}/rnaseq/yeast_chrI.fa yeast > /dev/null; ls yeast.*.ht2 | wc -l` },
  { id: 'hisat2-gz', cmd: `head -n 4000 ${EX}/rnaseq/SRR6357070_1.fastq | gzip > r1.fq.gz && head -n 4000 ${EX}/rnaseq/SRR6357070_2.fastq | gzip > r2.fq.gz && hisat2 -x yeast -1 r1.fq.gz -2 r2.fq.gz -S rna.sam 2> rna.log; tail -1 rna.log` },
  { id: 'featurecounts', own: true, cmd: `samtools sort -o rna.bam rna.sam && featureCounts -p --countReadPairs -a ${EX}/rnaseq/yeast_chrI.gtf -o counts.txt rna.bam > fc.log 2>&1; echo code=$?; tail -n +3 counts.txt | sort -k7,7nr -k1,1 | head -3 | cut -f1,7; cat counts.txt.summary | head -3` },
  { id: 'salmon', own: true, cmd: `gffread -w tx.fa -g ${EX}/rnaseq/yeast_chrI.fa ${EX}/rnaseq/yeast_chrI.gtf && salmon index -t tx.fa -i salmon_idx > sidx.log 2>&1; echo idx=$?; salmon quant -i salmon_idx -l A -1 r1.fq.gz -2 r2.fq.gz -o salmon_out > sq.log 2>&1; echo quant=$?; head -3 salmon_out/quant.sf | cut -f1,2` },
  // ---- programs in a worker of their own, and workflows
  { id: 'prodigal', own: true, cmd: `prodigal -i ${EX}/bacteria/ecoli.fna -o ecoli.gff -f gff -a ecoli.faa -q && grep -c ">" ecoli.faa` },
  { id: 'prodigal-pipe', own: true, cmd: `cat ${EX}/bacteria/ecoli.fna | prodigal -o p2.gff -f gff 2> p2.log; echo code=$?; grep -c CDS p2.gff; grep -c Piped p2.log` },
  { id: 'hmmer', own: true, cmd: `hmmbuild g4.hmm ${EX}/hmmer/globins4.sto > /dev/null && hmmsearch --tblout hits.tbl g4.hmm ${EX}/hmmer/globins45.fa > /dev/null; grep -vc "^#" hits.tbl; hmmsearch --cpu 2 g4.hmm ${EX}/hmmer/globins45.fa | grep -c '^>>'` },
  { id: 'bustools', own: true, cmd: `bustools sort -o sorted.bus ${EX}/singlecell/input.bus 2>/dev/null && bustools text -p sorted.bus | head -3` },
  { id: 'plink2', own: true, cmd: `plink2 --vcf ${EX}/plink2/synthetic_glm.vcf --freq --out f > /dev/null 2>&1; echo code=$?; head -3 f.afreq` },
  { id: 'lofreq', own: true, cmd: `lofreq call -f ${EX}/somatic/reference.fa -o tumor_calls.vcf ${EX}/somatic/tumor.bam 2> lofreq.log; echo code=$?; grep -vc '^#' tumor_calls.vcf` },
  { id: 'strelka2', own: true, cmd: `configureStrelkaSomaticWorkflow.py --normalBam ${EX}/somatic/normal.bam --tumorBam ${EX}/somatic/tumor.bam --referenceFasta ${EX}/somatic/reference.fa --callRegions ${EX}/somatic/regions.bed.gz --runDir strelka_run > cfg.log 2>&1; echo cfg=$?; strelka_run/runWorkflow.py -m local -j 1 > wf.log 2>&1; echo wf=$?; bcftools view -H strelka_run/results/variants/somatic.snvs.vcf.gz | wc -l; for f in strelka_run/results/variants/somatic.*.vcf.gz; do zcat $f | grep -v '^##startTime' | md5sum; done; grep -v TotalHours strelka_run/results/stats/runStats.tsv` },
  { id: 'kraken2', own: true, cmd: `kraken2 --db ${EX}/metagenomics/db --paired --report sample.report --output sample.kraken ${EX}/metagenomics/reads_1.fastq.gz ${EX}/metagenomics/reads_2.fastq.gz 2> k2.log; echo code=$?; head -4 sample.report; tail -2 k2.log` },
  { id: 'cutadapt', own: true, cmd: `cutadapt -a AGATCGGAAGAGC -o trimmed.fastq ${EX}/trimming/SRR6357070_adapters_1.fastq > cut.log 2>&1; echo code=$?; grep -c '^@' trimmed.fastq` },
  { id: 'macs3', own: true, cmd: `macs3 callpeak -t ${EX}/chipseq/CTCF_SE_ChIP_chr22_50k.bed.gz -c ${EX}/chipseq/CTCF_SE_CTRL_chr22_50k.bed.gz -f BED -g 52000000 -n ctcf --outdir ctcf > macs.log 2>&1; echo code=$?; wc -l < ctcf/ctcf_peaks.narrowPeak` },
  // ---- the page's own view of a program's file (what the editor, the viewers and downloads read)
  {
    id: 'vfs-reads',
    js: `const fs = MG.app.term.fs, out = {};
      for (const p of ['big.txt', 'sorted.txt', 'mapped.bam', 'a.txt']) {
        const abs = fs.home + '/t/' + p, e = fs.get(abs);
        const r = { kind: e && e.kind };
        try { r.text = (await fs.readText(abs)).length; } catch (x) { r.text = 'ERR ' + x.message; }
        try { r.bytes = (await fs.readBytes(abs)).length; } catch (x) { r.bytes = 'ERR ' + x.message; }
        try { r.blob = (await fs.toBlob(abs)).size; } catch (x) { r.blob = 'ERR ' + x.message; }
        out[p] = r;
      }
      return out;`
  },
  // ---- forced stops: a program in a worker of its own (only that worker goes), then the shared programs' worker
  // (every file that programs wrote goes with it, unless the page has a copy)
  { id: 'kill-own-worker', own: true, kill: `cutadapt -a AGATCGGAAGAGC -o t2.fastq ${EX}/trimming/SRR6357070_adapters_1.fastq`, afterMs: 1500 },
  { id: 'after-own-kill', own: true, cmd: 'samtools view -c mapped.bam; ls t2.fastq 2>&1' },
  { id: 'kill-runner', allPrograms: true, kill: "awk 'BEGIN { for (i = 0; i < 1e12; i++) x += i; print x }'", afterMs: 2500, settleMs: 4000 },
  { id: 'after-runner-kill', allPrograms: true, cmd: 'ls; samtools view -c mapped.bam 2>&1; echo done' }
];
