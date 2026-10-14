/* What a file holds, for comparing two runs whose programs may compress differently: a compressed file (gzip, BGZF:
   BAM, .vcf.gz …) is unpacked, and in text what carries the time of the run, or of the computer, is masked. Used by
   native-programs.mjs and, for the files of the local runner's folder, by the parity suite (harness.mjs). */
import crypto from 'node:crypto';
import fs from 'node:fs';
import zlib from 'node:zlib';

export function maskText(t) {
  return t
    .replace(/Date=[A-Z][a-z]{2} [A-Z][a-z]{2} +\d+ \d\d:\d\d:\d\d \d{4}/g, 'Date=#') // bcftools' header lines
    .replace(/(\[M::[^\]]*?::)\d+\.\d+\*\d+\.\d+\]/g, '$1#]') // minimap2's timings
    .replace(/(Real time|CPU|Peak RSS|real sec|CPU sec|sec|seconds?)(:?\s*)[\d.]+/g, '$1$2#')
    .replace(/[\d.]+ (sec|CPU sec|real sec|seconds?)\b/g, '# $1')
    .replace(/time used: \d+ seconds?/g, 'time used: #')
    .replace(/\d{4}-\d\d-\d\d\s+\d\d:\d\d:\d\d/g, '#date#'); // fastp's report
}
const isGz = (b) => b.length > 2 && b[0] === 0x1f && b[1] === 0x8b;
const sha = (b) => crypto.createHash('sha256').update(b).digest('hex').slice(0, 24);
/** a file: the hash of its bytes (raw), and of what it holds, unpacked and with times masked (content) */
export function look(file) {
  const b = fs.readFileSync(file);
  let content = b, kind = 'raw';
  if (isGz(b)) {
    try {
      content = zlib.gunzipSync(b);
      kind = 'gz';
    } catch (e) {
      kind = 'gz?';
    }
  }
  let text = null;
  try {
    text = new TextDecoder('utf-8', { fatal: true }).decode(content);
  } catch (e) {
    /* binary */
  }
  if (text != null && text.indexOf('\0') < 0) content = Buffer.from(maskText(text));
  return { raw: sha(b), content: sha(content), size: b.length, kind };
}
