#!/usr/bin/env node
/* Aligned-looking reads in the order an aligner writes them (by read, not by place), as SAM on standard output: the
   input of the SAMtools prototype (sort-big-bam.mjs). The same numbers give the same reads, byte for byte.

     node make-unsorted-sam.mjs --reads 40000000 [--seed 1] | samtools view -b -o unsorted.bam -

   Each read has 150 bases, at a random place on one of the 25 chromosomes of GRCh38 (chosen by length); its bases
   are those of a made-up genome at that place, with 0–2 errors (NM and MD say which); its qualities are binned as a
   NovaSeq writes them; one read in 20 is soft-clipped, one in 100 is unmapped (and so goes to the end when sorted).
   Many reads start at the same place as another – as in real data – so the order of equal places is tested too. */
const argv = process.argv.slice(2);
const opt = (name, dflt) => {
  const i = argv.indexOf('--' + name);
  return i >= 0 ? argv[i + 1] : dflt;
};
const READS = Number(opt('reads', 1000000));
const SEED = Number(opt('seed', 1));
let x = SEED | 0 || 1;
const rnd = () => {
  x ^= x << 13;
  x ^= x >>> 17;
  x ^= x << 5;
  return x >>> 0;
};

const CHROMS = [
  ['chr1', 248956422], ['chr2', 242193529], ['chr3', 198295559], ['chr4', 190214555], ['chr5', 181538259],
  ['chr6', 170805979], ['chr7', 159345973], ['chr8', 145138636], ['chr9', 138394717], ['chr10', 133797422],
  ['chr11', 135086622], ['chr12', 133275309], ['chr13', 114364328], ['chr14', 107043718], ['chr15', 101991189],
  ['chr16', 90338345], ['chr17', 83257441], ['chr18', 80373285], ['chr19', 58617616], ['chr20', 64444167],
  ['chr21', 46709983], ['chr22', 50818468], ['chrX', 156040895], ['chrY', 57227415], ['chrM', 16569]
];
const LEN = 150;
// the places where a read can start, chromosome after chromosome
const cum = [0];
for (const [, n] of CHROMS) cum.push(cum[cum.length - 1] + n - LEN + 1);
const TOTAL = cum[cum.length - 1];

// the made-up genome: 16 MiB of bases, repeated (a place of the genome → its place mod 16 Mi)
const REF_LEN = 16 * 2 ** 20;
const ref = Buffer.alloc(REF_LEN + LEN);
for (let i = 0; i < ref.length; i++) ref[i] = 'ACGT'.charCodeAt(rnd() & 3);
// qualities as a NovaSeq bins them (F 37, : 25, , 11, # 2): mostly F, a few lower runs, sometimes a low end
const NQ = 4096;
const quals = Buffer.alloc(NQ * LEN, 'F');
for (let k = 0; k < NQ; k++) {
  const q = quals.subarray(k * LEN, (k + 1) * LEN);
  for (let r = rnd() % 6; r > 0; r--) {
    const at = rnd() % LEN, n = 1 + (rnd() % 4);
    q.fill(rnd() % 3 ? ':' : ',', at, Math.min(LEN, at + n));
  }
  if (rnd() % 10 === 0) q.fill('#', LEN - 1 - (rnd() % 20));
}
const OTHER = { 65: 'CGT', 67: 'AGT', 71: 'ACT', 84: 'ACG' };
for (const k in OTHER) OTHER[k] = Buffer.from(OTHER[k]);

const header = ['@HD\tVN:1.6\tSO:unsorted'];
for (const [name, n] of CHROMS) header.push(`@SQ\tSN:${name}\tLN:${n}`);
header.push('@RG\tID:sample1\tSM:sample1\tPL:ILLUMINA\tLB:lib1');
header.push(`@PG\tID:make-unsorted-sam\tPN:make-unsorted-sam.mjs\tVN:1\tCL:make-unsorted-sam.mjs --reads ${READS} --seed ${SEED}`);
process.stdout.write(header.join('\n') + '\n');

const BATCH = 20000;
let buf, o;
const put = (s) => {
  o += buf.write(s, o, 'latin1');
};
const at = [0, 0];
function read(i) {
  put(`A00123:8:H7LMNDSXY:${1 + (i & 3)}:${1101 + ((i >>> 2) % 78)}:${(i * 7919) % 32000}:${i}\t`);
  const q = (rnd() & (NQ - 1)) * LEN;
  if (rnd() % 100 === 0) {
    // unmapped: no place
    put('4\t*\t0\t0\t*\t*\t0\t0\t');
    const g = (rnd() % TOTAL) % REF_LEN;
    o += ref.copy(buf, o, g, g + LEN);
    buf[o++] = 9;
    o += quals.copy(buf, o, q, q + LEN);
    put('\tRG:Z:sample1\n');
    return;
  }
  const r = rnd() % TOTAL;
  let lo = 0, hi = CHROMS.length - 1;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (cum[mid] <= r) lo = mid;
    else hi = mid - 1;
  }
  const flag = rnd() & 1 ? 16 : 0;
  const mapq = rnd() % 10 ? 60 : rnd() % 60;
  // soft clip at the start of the read: its place is that of its first aligned base
  const clip = rnd() % 20 === 0 ? 1 + (rnd() % 30) : 0;
  const pos = r - cum[lo] + 1 + clip;
  put(`${flag}\t${CHROMS[lo][0]}\t${pos}\t${mapq}\t${clip ? clip + 'S' + (LEN - clip) + 'M' : LEN + 'M'}\t*\t0\t0\t`);
  // the bases of the genome there, with 0–2 errors; MD names the base of the genome at each
  const s = o, g = r % REF_LEN;
  o += ref.copy(buf, o, g, g + LEN);
  const errs = rnd() % 10 < 7 ? 0 : rnd() % 10 < 8 ? 1 : 2;
  let n = 0;
  for (let k = 0; k < errs; k++) {
    const p = clip + (rnd() % (LEN - clip));
    if (n === 0 || at[0] !== p) at[n++] = p;
  }
  if (n === 2 && at[0] > at[1]) [at[0], at[1]] = [at[1], at[0]];
  let md = '', last = clip;
  for (let k = 0; k < n; k++) {
    const p = at[k], was = buf[s + p];
    md += String(p - last) + String.fromCharCode(was);
    buf[s + p] = OTHER[was][rnd() % 3];
    last = p + 1;
  }
  md += String(LEN - last);
  buf[o++] = 9;
  o += quals.copy(buf, o, q, q + LEN);
  put(`\tNM:i:${n}\tMD:Z:${md}\tAS:i:${LEN - clip - 5 * n}\tXS:i:${rnd() % 40}\tRG:Z:sample1\n`);
}

let i = 0;
function more() {
  while (i < READS) {
    buf = Buffer.allocUnsafe(BATCH * 600);
    o = 0;
    for (const end = Math.min(READS, i + BATCH); i < end; i++) read(i);
    if (!process.stdout.write(buf.subarray(0, o))) return process.stdout.once('drain', more);
  }
}
process.stdout.on('error', (e) => {
  if (e.code === 'EPIPE') process.exit(0);
  throw e;
});
more();
