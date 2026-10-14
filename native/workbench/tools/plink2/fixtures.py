"""Small genotype-count truth constructed independently of PLINK and its adapter."""
import json
from pathlib import Path

SAMPLES = ["z-last", "001", "a.dot", "under_score"]
# Genotypes are assigned before any scientific executable is invoked.
VARIANTS = [
    ("1", 101, "reference_only", "A", "G", ["0/0", "0|0", "0/0", "0/0"]),
    ("1", 202, "alternate_only", "C", "T", ["1/1", "1|1", "1/1", "1/1"]),
    ("2", 303, "one_third", "G", "A", ["0/0", "0/1", "1|0", "./."]),
    ("2", 404, "all_missing", "T", "C", ["./.", ".|.", "./.", ".|."]),
    ("22", 505, "balanced", "A", "C", ["1/1", "0/1", ".|.", "0/0"]),
    ("22", 606, "five_sixths", "C", "G", ["1|1", "./.", "0|1", "1/1"]),
]


def vcf(samples=SAMPLES, variants=VARIANTS, version="4.2"):
    lines = [f"##fileformat=VCFv{version}", "##source=NativeWorkbench-independent-synthetic-genotypes",
             '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">',
             "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\t" + "\t".join(samples)]
    for chrom, pos, identity, ref, alt, genotypes in variants:
        lines.append("\t".join([chrom, str(pos), identity, ref, alt, ".", "PASS", ".", "GT", *genotypes]))
    return "\n".join(lines) + "\n"


def fixtures(destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    sample_missing = [0] * len(SAMPLES)
    records = []
    for chrom, pos, identity, ref, alt, genotypes in VARIANTS:
        counts = {"homRef": 0, "heterozygous": 0, "homAlt": 0, "missing": 0}
        alt_count = 0
        for sample, gt in enumerate(genotypes):
            alleles = gt.replace("|", "/").split("/")
            if "." in alleles:
                counts["missing"] += 1
                sample_missing[sample] += 1
            else:
                alternate = sum(int(allele) for allele in alleles)
                alt_count += alternate
                counts[["homRef", "heterozygous", "homAlt"][alternate]] += 1
        called = len(SAMPLES) - counts["missing"]
        records.append({"chromosome": chrom, "position": pos, "id": identity,
                        "reference": ref, "alternate": alt, "genotypes": genotypes,
                        **counts, "calledGenotypes": called, "observedAlleles": 2 * called,
                        "alternateAlleles": alt_count,
                        "alternateFrequency": alt_count / (2 * called) if called else None,
                        "missingFraction": counts["missing"] / len(SAMPLES)})
    truth = {"schema": 1, "source": "Assigned synthetic diploid genotypes; integer allele and genotype arithmetic independent of PLINK or its adapter.",
             "samples": SAMPLES, "variants": records, "genotypes": 24,
             "calledGenotypes": 17, "missingGenotypes": 7,
             "observedAlleles": 34, "alternateAlleles": 18,
             "sampleMissing": {sample: missing for sample, missing in zip(SAMPLES, sample_missing)},
             "interpretation": "ALT frequency uses called alleles only; all-missing frequency is undefined, not zero. Missingness denominators include every retained variant or sample. No QC pass thresholds, association, PCA, ancestry or clinical interpretation."}
    (destination / "genotypes.vcf").write_bytes(vcf().encode("ascii"))
    (destination / "truth.json").write_bytes((json.dumps(truth, indent=2) + "\n").encode("utf-8"))
    return truth


if __name__ == "__main__":
    fixtures(Path(__file__).parent / "fixtures")
