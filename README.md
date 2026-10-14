# Bioinformatics workbench

**A workbench in the browser for students who have done the practicals: Jupyter-style notebooks in Python and R, a Linux terminal with real bioinformatics programs, Galaxy, public databases, a 3D structure viewer, a genome browser, a network viewer and an AI assistant – with a guide to every tool in the help pane.**

Everything runs in the student's browser. The programs are the real ones – fastp, Cutadapt, minimap2, Bowtie 2, BWA, BWA-MEM2, HISAT2, samtools, mosdepth, featureCounts, StringTie, kallisto, Salmon, bcftools, FreeBayes, LoFreq, SomaticSniper, Strelka2, Kraken2, Bracken, bustools, MACS3, Prodigal, HMMER, PLINK 2, bedtools, seqtk, Kalign, MUSCLE, FastTree, gffread, LASTZ and the GNU text tools – compiled to WebAssembly; Python is Pyodide (CPython 3.13), R is webR (R 4.6). Nothing is installed, there is no server-side code, and students' files are kept in their own browser. The site is static (HTML, CSS, JavaScript), so it can be hosted free on **GitHub Pages** or on any web server.

---

## Contents

1. [What is in it](#what-is-in-it)
2. [Before students use it](#before-students-use-it)
3. [Put it on GitHub Pages](#put-it-on-github-pages)
4. [Try it on your own computer](#try-it-on-your-own-computer)
5. [Settings: `config.js`](#settings-configjs)
6. [Python and R from your own server](#python-and-r-from-your-own-server)
7. [Editing the help, the starter notebooks and the examples](#editing-the-help-the-starter-notebooks-and-the-examples)
8. [What students keep](#what-students-keep)
9. [Privacy](#privacy)
10. [Browser support and limits](#browser-support-and-limits)
11. [How it was tested](#how-it-was-tested)
12. [Where the programs run: execution backends](#where-the-programs-run-execution-backends)
13. [Files](#files)
14. [Credits and licences](#credits-and-licences)

---

## What is in it

One page, `index.html`: the **help** on the left, the **workbench** on the right. The help can be hidden (button, or <kbd>Ctrl</kbd>+<kbd>\</kbd>) and the workbench made full screen.

| Tab | What it is |
| --- | --- |
| **Notebook** | Jupyter-style notebooks (`.ipynb`) in Python or R: code and Markdown cells, plots, tables, `%pip install`, `install.packages()` (Bioconductor too – DESeq2, edgeR, limma), `%%bash` and `!` cells with the terminal's programs. Download as `.ipynb`, `.py`/`.R` or `.html`. Two starter notebooks are put in `~/notebooks` on the first visit |
| **Terminal** | bash with the bioinformatics programs, `python`, `Rscript`, Snakemake (a browser edition), Graphviz `dot`, `curl`/`wget` for web services; *Save session* turns the commands typed into a notebook or a script. Its user is `user` (`user@workbench:~$`) – the button with that name at the top of the page puts a person's own name in its place |
| **Files** | the home folder (`~`, `/home/user`) and the read-only example data: an editor, viewers for tables, FASTA, alignments, trees, pictures, PDFs (drawn by the page itself, with PDF.js – no browser plug-in) and HTML reports; upload, download (a folder as `.zip`) |
| **Galaxy** | a Galaxy in the style of usegalaxy.org: 56 tools (QC with fastp and Cutadapt, mapping – minimap2, Bowtie2, BWA-MEM, BWA-MEM2, HISAT2 –, SAM/BAM with mosdepth, RNA-seq – featureCounts, StringTie, kallisto, Salmon –, single-cell – bustools sort, correct, count, inspect, text –, peak calling – MACS3 callpeak –, variant calling – bcftools, FreeBayes, LoFreq, Strelka Somatic –, genotypes – PLINK 2 –, metagenomics – Kraken2, Bracken –, annotation – Prodigal, hmmbuild, hmmsearch, hmmscan, phmmer, nhmmer, hmmalign –, intervals, alignments and trees, text) with Tool Shed IDs (the workbench's own for Kalign, MUSCLE, bustools, MACS3 and PLINK 2, which the Tool Shed does not have) and, at the end of each form, the papers to cite, as on a Galaxy server; a history kept in the browser, dataset details, a workflow editor, `.ga` import and export, and *history as a notebook* |
| **Databases** | 17 cards: UniProt and the PDB (full explorers), AlphaFold DB, InterPro, Ensembl (gene, sequence, VEP, orthologues, region), NCBI E-utilities, UCSC, ENA, BLAST at EBI, STRING (networks and enrichment), IntAct, NDEx, Reactome, Gene Ontology (QuickGO, OLS), g:Profiler, Europe PMC, PubChem. Every answer can be saved to the files or sent to a notebook as Python or R code; *Your queries* become one notebook |
| **3D viewer** | NGL: PDB entries, AlphaFold models, files; styles, colours, selections, binding sites and contacts, distances, labels, superposition, saved views, a command language; pictures to the files or to the computer |
| **Genome browser** | igv.js: the example genome (two slices of chromosome 10, with genes), hosted genomes (hg38, hg19, mouse, zebrafish, fly, worm, yeast) or a FASTA file; BAM, VCF, BED, GFF and bigWig tracks |
| **Networks** | a network viewer in the manner of Cytoscape, drawn with Cytoscape.js: SIF, GraphML, XGMML, GML, Cytoscape JSON, CX2 and tables of edges; networks from STRING, IntAct and NDEx, and from a table of genes (DESeq2's results onto their STRING network); styles mapped from the columns (continuous, discrete, charts on the nodes) with a legend; node and edge tables, filters, merging, undo; layouts (fCoSE, hierarchical, groups …); the statistics of NetworkAnalyzer, the hub rankings of cytoHubba, MCODE, MCL and Louvain clusters, k-cores, shortest paths and functional enrichment; pictures (PNG, SVG), Cytoscape JSON, GraphML, SIF and code for a notebook (networkx, igraph). Files, Galaxy, the Databases tab, the terminal (`network`) and notebooks (`!network`) send networks to it |
| **AI assistant** | a chat that sees what the student chooses (the open notebook's code, file names, last commands, the open network) and puts code into the notebook or terminal; an **agent** that carries out a task in the terminal in a folder of its own and keeps a record as a notebook. The student connects a model of their own (Gemini, Claude, or any OpenAI-compatible service) |

**The help** has 54 pages in 12 groups – a first session, every tab, every program, recipes and reference (programs and versions, keyboard shortcuts, limits, troubleshooting, privacy, credits). Each program's page ends with the papers to cite (*References*), and *Programs and versions* has a column of them. Code boxes have *Run in the terminal* or *Add to notebook*; ▶ buttons do what the text describes (open a card with a query, load a structure, go to a locus …). The seven **recipes** – reads to variants, RNA-seq reads to differential expression (HISAT2, featureCounts, DESeq2, edgeR), expression data on an interaction network (STRING, hubs, MCODE, enrichment), from a protein to its structure, a table in Python and in R, databases from code, keeping your work – each open as a notebook with one button.

**Everything a student runs can become a notebook**: notebooks themselves, terminal sessions, Galaxy histories, database queries, the AI agent's runs and the recipes.

## Before students use it

1. **Computers and browsers.** A laptop or desktop with a current Chrome, Edge, Firefox or Safari; 8 GB of memory is comfortable. The 3D viewer needs WebGL (hardware acceleration on). Phones work, cramped.
2. **Network.** Besides your site, the students' browsers must reach:
   - `cdn.jsdelivr.net` (Python: the page downloads it in the background as soon as a Python notebook is open – and when it starts, the page opens the last notebook the student had open, a Python one on the first visit), `webr.r-wasm.org`, `repo.r-wasm.org`, `bioc-release.r-universe.dev`, `cran.r-universe.dev` and `r2.ropensci.org` (R and its packages), `pypi.org` and `files.pythonhosted.org` (`%pip install`);
   - the databases: `www.ebi.ac.uk`, `rest.uniprot.org`, `alphafold.ebi.ac.uk`, `rest.ensembl.org` (and `grch37.rest.ensembl.org`), `eutils.ncbi.nlm.nih.gov`, `pubchem.ncbi.nlm.nih.gov`, `data.rcsb.org`, `search.rcsb.org`, `files.rcsb.org`, `models.rcsb.org`, `cdn.rcsb.org`, `api.genome.ucsc.edu`, `string-db.org`, `reactome.org`, `www.ndexbio.org`, `biit.cs.ut.ee` (g:Profiler), `ftp.sra.ebi.ac.uk` (IntAct is on `www.ebi.ac.uk`);
   - for the hosted genomes of the genome browser: the IGV team's list of genomes (`igv.org`) and the files it points to (`hgdownload.soe.ucsc.edu`, or – when that does not answer – its copy `genome-browser.s3.us-east-1.amazonaws.com`);
   - the AI service each student uses (for Gemini: `generativelanguage.googleapis.com`).
3. **AI keys.** The assistant uses a key that each student enters; it is kept only in the browser tab (never in a file or in the browser's long-term storage). Decide which service the students use, and tell them before:
   - **Google Gemini**: a free key from [aistudio.google.com/apikey](https://aistudio.google.com/apikey) (a Google account; 18 or over). The free tier allows a few requests per minute and a limited number per day for each model; when a model is busy or over its limit, the page asks the next model of `geminiFallbackModels`. Read Google's [Gemini API Additional Terms](https://ai.google.dev/gemini-api/terms) first. On the free tier Google may use what is sent to improve its products, and people may read it – but for users in the European Economic Area, Switzerland and the United Kingdom the data terms of the paid service apply to the free tier too. The same terms say that API clients made available to users in those regions may use only the paid service: whether a course page on which each student uses a key of their own counts as such a client is for your institution to decide.
   - **Anthropic (Claude)** – a paid key; or **any OpenAI-compatible service** that allows requests from web pages (CORS), such as one your university provides: the address, the model and, if it needs one, a key.
   - Check that the model names in `config.js` are current ([Gemini models](https://ai.google.dev/gemini-api/docs/models)).
4. **Shared computers.** Students' files are kept in the browser profile. Computers that wipe profiles at log-out lose them: tell students to download their work (*My files → Download all my files*), and to use *Start afresh* when they leave a shared computer.
5. **Personal and patient data.** The workbench is for public data. The help and the AI settings tell students never to put personal or patient data into it or into an AI tool.

## Put it on GitHub Pages

**First put the two parts together.** The workbench comes as two zip files: `bioinformatics-workbench.zip`, the site, and `bioinformatics-workbench-sources.zip`, the source code of the bundled programs that are under the GNU General Public License or the Mozilla Public License (twenty-six archives, 139 MB). Unzip both, and move the twenty-six archives from the folder `sources` into `bioinformatics-workbench/assets/vendor/licenses/sources/` (a `README.txt` in that folder lists them). The site works without them, but the licence asks whoever publishes those programs to offer their source code with them – see [Credits and licences](#credits-and-licences).

1. On GitHub, create a **new repository** (for example `bioinformatics-workbench`). It must be public unless your plan supports Pages for private repositories.
2. Upload the site: `index.html` must be at the **top level**, with `assets/` and `data/` beside it.
   - **With [GitHub Desktop](https://desktop.github.com/)** (easiest): *File → Add local repository* (choose the unzipped folder and let it create a repository), *Commit*, then *Publish repository* with “Keep this code private” unticked. GitHub's upload page in the browser is not suitable: it takes at most 100 files at a time, and the site has more than 1,300.
   - **Or with git:**
     ```bash
     cd bioinformatics-workbench
     git init && git add . && git commit -m "Bioinformatics workbench"
     git branch -M main
     git remote add origin https://github.com/<you>/bioinformatics-workbench.git
     git push -u origin main
     ```
3. *Settings → Pages → Build and deployment*: Source **Deploy from a branch**, branch **main**, folder **/ (root)**. Save.
4. After a minute the site is at `https://<you>.github.io/bioinformatics-workbench/`. Share that address. The first time a browser opens it, the page loads once more by itself: it installs a small service worker (`isolation-sw.js`, next to `index.html`) that makes the page *cross-origin isolated*, which featureCounts, Salmon and PLINK 2 need for their threads (see [Browser support and limits](#browser-support-and-limits)).

The empty file `.nojekyll` stops GitHub from processing the site. The folder `build/` is not needed by the site (it builds `index.html`); keep `assets/vendor/licenses/`. On any other web server: copy the folder; it needs no server-side code, but it must answer HTTP range requests (all common servers do), which the genome browser uses.

**Students' files belong to the address.** They are kept by the browser for the site's address: if the workbench moves to another address, students start with an empty home folder there (their files stay at the old address). Two copies of the workbench on one address share their files unless their `storePrefix` differs.

## Try it on your own computer

Opening `index.html` directly (`file://…`) does not work – browsers block the Web Workers and the data files. Serve the folder instead:

```bash
cd bioinformatics-workbench
python3 serve.py 8000        # then open http://localhost:8000
```

`serve.py` answers range requests and sends the headers of cross-origin isolation itself. Any other local server works too (the service worker isolates the page), as long as the address is `localhost` or `https`.

## Settings: `config.js`

`assets/js/config.js` is the only file to edit for most changes. **Never put an API key in it**: anyone can read the files of a public site.

| Setting | What it does |
| --- | --- |
| `courseTitle`, `courseSubtitle` | the name at the top of the page (and in the browser's tab) and the line under it |
| `hostname` | the computer's name in the terminal's prompt (`user@workbench`) |
| `storePrefix` | the prefix of everything kept in the browser (files, notebooks, settings). Change it only if two copies of the workbench on one address must not share their files |
| `pyodideBase`, `pythonPreload` | where Python comes from, and the packages loaded when it starts |
| `webrBase`, `rRepos`, `rLocalRepo` | where R comes from, the repositories of R packages (CRAN for webR; the current Bioconductor release and CRAN on r-universe), and the site's own packages, looked in first (`assets/vendor/r-packages/`: locfit, for DESeq2 and edgeR) |
| `biowasmBase` | the folder of the WebAssembly programs |
| `threadsBase` | the folder of the programs of the genomics-wasm project that run in a worker of their own – featureCounts, Salmon and PLINK 2 (on several threads), Cutadapt, MACS3, LoFreq, SomaticSniper, Strelka2, Kraken2, Bracken, bustools, Prodigal, HMMER (`assets/vendor/genomics-wasm/`) |
| `liveProvider`, `geminiModel`, `geminiFallbackModels`, `anthropicModel` | the AI service offered first and its models. Models are retired from time to time: put current ones here |
| `aiWaitSeconds` | how long the assistant waits for an answer before it asks the next model |
| `agentCommandSeconds` | after how many seconds a step of the AI agent that has not ended is stopped |
| `storageWarnMB` | from how many megabytes of files the page warns the student (the indicator at the top, and a message once a visit) |

## Python and R from your own server

By default the browser downloads Python (Pyodide, about 30 MB for the core and the first packages) from jsDelivr as soon as a Python notebook is open, and R (webR) from `webr.r-wasm.org` when an R notebook is open – the page opens the last notebook the student had open (a Python one on the first visit); it keeps a copy in its cache for the next visits. To serve them with the site instead – for a network that blocks those servers:

- **Python**: download the Pyodide 0.29.5 release (`pyodide-0.29.5.tar.bz2` from [github.com/pyodide/pyodide/releases](https://github.com/pyodide/pyodide/releases)), unpack it as `assets/vendor/pyodide/`, and set `pyodideBase: 'assets/vendor/pyodide/'`. The full release is large (several hundred MB in thousands of files): copy only the packages you need if you host on GitHub Pages (a repository should stay under 1 GB).
- **R**: download the webR 0.6.0 release, unpack it as `assets/vendor/webr/`, and set `webrBase: 'assets/vendor/webr/'`. R packages still come from `rRepos`; mirroring them is possible with the [rwasm](https://r-wasm.github.io/rwasm/) tools.

## Editing the help, the starter notebooks and the examples

The page is built from parts in `build/`. After any change there, run:

```bash
python3 build/make_page.py        # writes index.html; warns about links to pages that do not exist
```

- **Help pages**: `build/help/NN-name.html`, one file per page, in the order of their names. A page whose first line says `index: yes` is the index of its group (what *Recipes* and *Reference* in the path at the top of a page open); `<!--GROUP-->` lists the group's other pages. `<!--CITE: name name-->` at the end of a page lists the papers to cite for those programs, and `<!--CITE-SHORT: name-->` names them shortly; the programs and their references are in `build/citations.json` (the Galaxy tools name theirs in `assets/js/galaxy.js`, `cite:`). The first line names the page: `<!-- id: h-name | title: … | group: … | summary: … | keys: words for the search -->`; the groups are listed in `make_page.py`. Links between pages: `<a href="#h-name">` (or `#h-name/anchor` for a heading with `data-anchor="anchor"`). Code: `<pre class="code" data-run="term|py|r"><code>…</code></pre>` gets *Run in the terminal* or *Add to notebook*, and *Copy*. Buttons (`<button class="do" type="button" …>`) act through attributes: `data-term-run` (run a command), `data-term` (type it), `data-bench` (open a tab), `data-goto` (open a help page), `data-open` (open a file), `data-new-nb="python|r"`, `data-open-nb` (a notebook), `data-cmd` (a script of the 3D viewer), `data-igv` (a locus), `data-api="card:form:value"` (a query in the Databases tab), `data-net="…"` (the Networks tab: `example:airway`, `genetable:PATH`, `analyse:hubs`, `layout:groups`, `enrich:cluster1` … – see `action()` in `assets/js/networks.js`) and `data-recipe="python|r"` (the page as a notebook). `<!--ICON:name-->` puts in an icon of `assets/js/icons.js`.
- **Starter notebooks**: `python3 build/make_starters.py` writes `data/starter/*.ipynb` from the text in that script. They are copied into `~/notebooks` on a student's first visit (a file of the same name is left alone).
- **Example data**: `data/examples/` – read-only for students, with a `README.md` that describes every file. After adding or changing a file, run `make_page.py` (the page lists the files and their sizes).
- **Programs**: after a change in `assets/vendor/`, run `python3 build/vendor_sums.py` to write the checksum lists again.

## What students keep

Students' files – notebooks, results, uploads, Galaxy's history – are kept in their browser's storage for the site (IndexedDB), on their computer, and are there when they come back in the same browser. They are not on any server, and nobody else can see them. Another browser, another computer or a private window has none of them, and clearing the browser's site data deletes them. *My files → Download all my files* downloads everything as a `.zip`; every notebook downloads as `.ipynb`. The help page *Keep and share your work* explains this to students.

**The home folder is `/home/user`** (until October 2026 it was `/home/student`). Files that a browser kept under the old name move to the new one the first time the workbench is opened again, with the paths the page remembers (open files, the terminal's history, Galaxy's history); a path written with the old name, in a notebook or a script of that time, still leads to the home folder. The name a person gives the workbench (the button at the top) is kept in their browser with the other settings; it changes the terminal's prompt, `whoami`, `$USER`, the owner in `ls -l` and Python's and R's `USER`, not the home folder.

## Privacy

The site sets no cookies and has no tracking or analytics. What leaves a student's computer: requests for the page and its programs (your server), Python and R and their packages (the CDNs above), the queries the student makes to public databases (and, for BLAST, an e-mail address that EBI asks for), the gene and protein names the Networks tab sends to STRING, IntAct, NDEx and g:Profiler (never the values of a table), structures and genome regions the student opens (RCSB PDB, AlphaFold DB, the hosted genomes), and – only when the student connects a model – the questions, and what the student chooses to send with them, to the AI service of their choice, with their own key. The name a person gives the workbench is not sent: the AI agent's commands run as `user`, and in the terminal output that goes to the AI service the name is replaced by `user` where it names the user (the prompt, `whoami`, `id`, the owner in `ls -l`). The help page *Your data and privacy* lists it for students.

## Browser support and limits

Current Chrome, Edge, Firefox and Safari. Each program runs on one processor core with a few gigabytes of memory at most (featureCounts counts on up to four threads, Salmon runs helper threads, and PLINK 2 reads its files on threads of their own): regions of a genome, exomes of a few genes, bacterial and viral genomes work; a whole human genome does not. Web services must allow requests from web pages (CORS): the big bioinformatics services do; KEGG and most web pages do not. R in the browser can only make GET requests. Some R packages have no build for webR yet; DESeq2 and edgeR work (locfit, which they need, comes with the site). Cutadapt starts a Python of its own for each command (a few seconds); LoFreq has no `call-parallel` or `vcfplot`; Strelka2 has its somatic workflow, which the terminal runs itself (there is no Python 2), with `-m local` only. Kraken2 works with small databases – a few hundred megabytes at most, which must fit in the browser's memory (the standard databases, of tens of gigabytes, do not) – and `kraken2-build` cannot download; Bracken's Python programs start a Python of their own for each command (a few seconds). HMMER runs on one thread (no `--cpu`), cannot read `.gz` files (it would start gzip) and needs WebAssembly SIMD; profile databases as big as the whole of Pfam do not fit. bustools sorts on one thread, in at most 1 GB of memory. MACS3 starts the Python of Cutadapt, with NumPy, SciPy, scikit-learn and pandas, for each command (a few seconds; the first time about 45 MB are loaded), runs as one process and keeps the reads in memory: the reads of a chromosome or a small genome, not a whole human experiment. PLINK 2 is a build without LAPACK – no `--pca` or `--pheno-svd` – and works in 640 to 1024 MiB (the terminal adds `--threads 1 --memory 640 require` unless they are given); `--script` and `--rerun` are not available. The help page *What is different in the browser* explains the limits to students.

**Cross-origin isolation.** featureCounts, Salmon and PLINK 2 start threads that share memory (`SharedArrayBuffer`), which browsers allow only in a page served with the headers `Cross-Origin-Opener-Policy: same-origin` and `Cross-Origin-Embedder-Policy: require-corp`. GitHub Pages cannot send them, so `assets/js/isolation.js` registers `isolation-sw.js`, a service worker that adds them to the page and its workers (it caches nothing): on the first visit the page loads once more by itself, and is isolated from then on. Under these headers a page may show pictures of other sites only if those sites allow it; the service worker asks for them in the way that lets them (CORS) – the RCSB and Reactome do. Isolation needs `https` (or `localhost`) and a browser that allows service workers there (some private windows do not); where it is missing, featureCounts, Salmon and PLINK 2 say so and the rest of the workbench works as before. `?isolation=off` at the end of the address removes the service worker. It was tested in Chromium; test Firefox and Safari on your students' computers.

## How it was tested

The workbench was tested in Chromium (Playwright) on 10 October 2026, again after BWA, HISAT2, FreeBayes and DESeq2 were added on 11 October 2026, and again – twice: as an ordinary page, and cross-origin isolated – after BWA-MEM2, featureCounts, StringTie, kallisto, Salmon and mosdepth were added later that day: every code block and every button of the help pages (terminal blocks run in order, Python and R blocks in notebooks), the recipes as notebooks from the first cell to the last (six notebooks, among them the RNA-seq recipe with featureCounts, DESeq2 and edgeR), the 36 Galaxy tools and a workflow (with the history-as-notebook re-made byte for byte), the Files viewers, the 3D viewer and the genome browser, the programs of the genomics-wasm project against native builds of the same sources (index files, SAM, VCF and GTF records, count tables, depths, abundances), the service worker that isolates the page (installed on the first visit, the page loaded once more, featureCounts run, pictures of the RCSB shown, `?isolation=off`), every database card against the real services (BLAST against a stand-in, so as not to send jobs to EBI), and the layout at phone and desktop widths. The PDF viewer of the Files tab and the user's name were added on 11 October 2026 and tested the same way, and the PDFs also in Google Chrome 155 and Microsoft Edge 155 (as an ordinary page, isolated by the server's headers, and isolated by the service worker): plots from R and matplotlib, a 60-page PDF with a landscape page and links, a PDF with a password, a damaged and an empty file, and a PDF opened, or written again, while the Files tab was hidden; for the name: the prompt, `whoami`, `id`, `ls -l`, `tar`, Python and R, the AI agent's commands (as `user`), and files and settings kept under `/home/student` moved to `/home/user`. Cutadapt, LoFreq, SomaticSniper and Strelka2 were added on the evening of 11 October 2026, and everything was tested again, as an ordinary page and cross-origin isolated – with every block of the new help page *Somatic variants*, the four new Galaxy tools, and the results of the new programs compared with native builds of the same sources (Cutadapt's trimmed reads byte for byte; the VCF records of LoFreq, SomaticSniper and Strelka2 – Strelka2 against its own Python 2 workflow); Cutadapt and Strelka2 also in a page opened with plain `http://` from another computer, where the browser has no `crypto.subtle`. Kraken2 and Bracken were added on 12 October 2026, and everything was tested again, as an ordinary page and cross-origin isolated – with every block of the new help page *Metagenomics*, the two new Galaxy tools, and the results compared with the native programs run by their own Perl and shell scripts, byte for byte (Kraken2's reports, classifications and classified and unclassified reads, `kraken2-inspect`'s table, the hash table and taxonomy that `kraken2-build` writes, Bracken's tables and reports, the distributions of `bracken-build`); Bracken also in a page opened with plain `http://`. bustools, Prodigal and HMMER were added on 13 October 2026, and everything was tested again, as an ordinary page and cross-origin isolated – with every block of the two new help pages *Single-cell RNA-seq* and *Genes and protein domains* (the Python block of the first in a notebook, after the page's terminal blocks), the seven new Galaxy tools, and the results compared with the native programs, byte for byte (but for HMMER's dates, times, working folder and command line, and bustools sort's times): Prodigal's genes, proteins, gene sequences, starts and training files, the profiles, pressed databases, outputs and tables of all thirteen HMMER programs, and bustools' records, matrices, lists and compressed files. PLINK 2, the Galaxy tools for bustools and PLINK 2 and the references of the help pages and of the Galaxy tools were added later on 13 October 2026, with the help page *Genotypes and association*, and everything was tested again, as an ordinary page and cross-origin isolated: every block of the new page (its Python block in a notebook), more commands (`--make-bed` and `--bfile`, `--keep`, `--make-king-table`, `--export vcf`, `--pmerge-list`, two threads, the errors) and the six new Galaxy tools, compared with the native programs – the same files, byte for byte (the logs but for the host, the folder, the times, the random seed and the memory found); the references of every Galaxy tool against the citations of its Tool Shed XML; and every help page with its references. The Networks tab was added later on 13 October 2026, and everything was tested again, as an ordinary page and cross-origin isolated – with every block and button of its help pages (*The Networks tab*, *Network analysis*, *Interactions and networks*), the recipe *Expression data on an interaction network* as a notebook (asking STRING itself), and a test of the tab (87 checks): the statistics on Zachary's karate club against networkx 3.4.2 (degrees, distances, closeness, betweenness and edge betweenness, clustering coefficients, eccentricities, neighbour degrees, core numbers, modularity), the hub rankings, MCODE, MCL and Louvain against fixed values; files written and read again (Cytoscape JSON, GraphML, SIF) and read (XGMML, GML, NDEx's CX2), tables of edges and of values, the terminal's `network`, Files, Galaxy, the Databases cards, the UniProt explorer, the recipe's buttons, pictures, notebooks (networkx in Python, igraph in R) and the networks kept across a reload – with STRING, IntAct, NDEx and g:Profiler answered by stand-ins in their own formats, so that the results are fixed. The analyses themselves were compared with networkx, the Python package markov_clustering and line-by-line Python versions of clusterMaker2's MCODE and of networkx's Louvain on five networks: 215 comparisons, all equal. MACS3 was added later on 13 October 2026, with the help page *Peaks: ChIP-seq and ATAC-seq*, the Galaxy tool MACS3 callpeak and the example data of `chipseq/` and `atacseq/`, and everything was tested again, as an ordinary page and cross-origin isolated: every block of the new page (its Python block in a notebook, its Rscript drawing the model, its peaks and tracks in the genome browser on hg19 and sacCer3), `bdgopt`, the Galaxy tool (narrow peaks; broad peaks without a model) and MACS3's errors, compared with MACS3 built for Linux from the same source – the same peaks, summits, bedGraph tracks, tables and accessible regions, byte for byte (the tables but for the paths of the data, which MACS3 writes as typed; the models but for their last decimals), and the peaks of the help page are those of MACS's own test; MACS3 also in a page opened with plain `http://`. The AI assistant's chat and agent were tested against stand-ins of the AI services with a dummy key: before you rely on them, try them with a real key on the network the students use. Public services are sometimes slow or down – on the day of testing, EMBL-EBI's services answered with errors for a while, and at the last run Ensembl's orthologue service (`/homology`) did not answer at all; the cards then say that the service is not answering.

## Where the programs run: execution backends

The terminal's programs, and the bytes of the files they write, are reached through one interface, `MG.exec`
(`assets/js/exec.js`). Behind it the **browser backend** (`assets/js/exec-browser.js`) runs the programs in the page,
compiled to WebAssembly, as described above; it is the default. The **local backend** (`assets/js/exec-local.js`)
runs them on the user's own computer, in a companion program, the **local runner** (`runner/`, Node.js, nothing to
install), with the files of an analysis in a folder on disk – so that neither the memory of a browser tab nor the size
of a file limits an analysis:

```
node runner/runner.mjs --workspace ~/my-analysis      # then open the address it prints
```

The folder is the terminal's home folder; the programs run there, reading and writing the files on disk; the page
holds none of their bytes, and finds the files again after a reload. SAMtools, BCFtools, bgzip, tabix, minimap2, BWA,
FreeBayes, fastp and seqtk run as native programs, built for the computer itself (`native/bin`: one executable each
for Windows, Linux and macOS, from Native Workbench's recipes – `native/README.md`), with no limit of memory but the
computer's; the rest are the browser's WebAssembly builds, run by the runner (`--no-native`: all of them). The programs with a worker of their own (featureCounts,
Salmon, Kraken2 …) are not in the runner yet. Without a runner, `?backend=local` says so and runs the programs in the
page. `runner/README.md` explains the runner; `docs/execution-backends.md` the interface, the two backends, the
runner's protocol and the measurements of the first prototype (SAMtools sorting a 5 GiB BAM file from the page);
`tests/` checks that the browser backend behaves exactly as before and the local one as the browser (see
`tests/README.md`).

## Files

```
index.html             the page (built by build/make_page.py)
isolation-sw.js        the service worker that makes the page cross-origin isolated (keep it next to index.html)
assets/js/             the workbench: config.js (settings), the tabs, the shell, the kernels, the AI assistant;
                       exec.js, exec-engine.js, exec-browser.js, exec-local.js: where the programs run
                       (docs/execution-backends.md)
assets/css/            styles
assets/py/smk.py       the browser edition of Snakemake
assets/vendor/         bundled programs and libraries, with their licences (see THIRD_PARTY.md); genomics-wasm/: the
                       programs that run in a worker of their own (featureCounts, Salmon, PLINK 2, Cutadapt, MACS3,
                       LoFreq, SomaticSniper, Strelka2, Kraken2, Bracken, bustools, Prodigal, HMMER), and pyodide/: the
                       Python of Cutadapt, Bracken and MACS3, with the packages of Pyodide that MACS3 needs
data/examples/         the example data (read-only for students) and its README.md
data/starter/          the starter notebooks
build/                 make_page.py, help/ (the help pages), citations.json (the references), template.html,
                       make_starters.py, vendor_sums.py
serve.py               a small local web server (optional)
runner/                the local runner: the programs on this computer, the files in a folder on disk (runner/README.md)
native/                the native programs: bin/ (what the local runner runs), build.py (which builds them), and the
                       code and recipes taken from Native Workbench (native/README.md, native/TOOLS.md)
docs/                  execution-backends.md: how the programs are run, in the browser and with the local runner
tests/                 headless checks (Playwright): the parity suite, the execution-backend checks, the local runner,
                       and the SAMtools prototype (tests/prototype/)
THIRD_PARTY.md         the third-party software and data, their licences and sources
```

## Credits and licences

The workbench is built from open-source programs and libraries and open data – fastp, Cutadapt (with dnaio and xopen), seqtk, wgsim, minimap2, Bowtie 2, BWA, BWA-MEM2, HISAT2, SAMtools, mosdepth, featureCounts (Subread), StringTie, kallisto, Salmon, BCFtools, FreeBayes, LoFreq, SomaticSniper, Strelka2, Kraken2, Bracken, bustools, MACS3 (with hmmlearn), Prodigal, HMMER, PLINK 2, HTSlib, bedtools, gffread, Kalign, MUSCLE, FastTree, seq-align, LASTZ, jq and the GNU tools (compiled by the Biowasm project, by the genomics-wasm project or for the course); the R package locfit (built for the site with genomics-wasm's recipe); Pyodide (and, for Cutadapt, Bracken and MACS3, Pyodide 314 with CPython 3.14 – and NumPy, SciPy, scikit-learn, pandas, h5py and AnnData for MACS3) and webR; NGL, igv.js, Cytoscape.js (with the fCoSE and dagre layouts), CodeMirror, marked, DOMPurify, JSZip, PDF.js and Viz.js (Graphviz). Each keeps its own licence; **[THIRD_PARTY.md](THIRD_PARTY.md)** lists them all, with versions, licences, origins and the local changes. Several programs are under the GNU General Public License, and Pyodide 314 (with hiwire and the recipes of its packages) and the Eigen in bustools under the Mozilla Public License: their source code is in `assets/vendor/licenses/sources/` (handed over as the second zip file) – keep it with the site.

The example data are public: 1000 Genomes Project reads of NA12878, the UCSC hg19 reference, Ensembl annotation, GenBank and UniProt sequences, a yeast gene table from SGD, PaxDb, BioGRID, UniProt and AlphaFold DB, the PDB structure 1MBN, and RNA-seq data – yeast reads from nf-core/test-datasets and the airway gene counts from Bioconductor –, tumour and normal reads of the cell lines HCC1395 and HCC1395BL with the SEQC2 truth set, reads of a mock microbial community (ENA) with a small Kraken2 database made from NCBI RefSeq and Taxonomy, two bacterial chromosome windows from NCBI RefSeq, the tutorial files of HMMER (with Pfam, Dfam and UniProt data), single-cell RNA-seq data of mouse cells (SRA, as test files of kb_python and the BUStools getting_started release), genotypes of the 1000 Genomes Project (Phase 3, as the test file of PLINK 2) with synthetic files from PLINK 2's tests, and the ChIP-seq and ATAC-seq test data of MACS (CTCF on human chromosome 22; yeast, SRA run SRR1822137) – see `data/examples/README.md`.
