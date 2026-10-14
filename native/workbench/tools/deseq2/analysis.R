# Workbench adapter only; DESeq2/tximport algorithms are unmodified upstream code.
options(warn=1, repos=NULL)
.libPaths(file.path(R.home(), 'library'))
suppressPackageStartupMessages(library(jsonlite))
suppressPackageStartupMessages(library(DESeq2))
suppressPackageStartupMessages(library(tximport))
stopifnot(as.character(packageVersion('DESeq2')) == '1.52.0', as.character(packageVersion('tximport')) == '1.40.0')
args <- commandArgs(trailingOnly=TRUE)
if (length(args) != 1L) stop('Exactly one request file is required')
req <- fromJSON(args[[1]], simplifyVector=TRUE)
set.seed(810431)
fail <- function(x) stop(x, call.=FALSE)
identifier <- function(x) all(!is.na(x) & grepl('^[A-Za-z][A-Za-z0-9_.-]{0,63}$', x))
read_tsv <- function(path) {
  x <- read.delim(path, header=TRUE, sep='\t', quote='', comment.char='', check.names=FALSE,
                  stringsAsFactors=FALSE, colClasses='character', na.strings=NULL)
  if (!nrow(x) || anyDuplicated(names(x))) fail('TSV requires records and distinct column headers')
  if (anyNA(x)) fail('Missing or ragged TSV values are not accepted')
  x
}
number <- function(x, integer=FALSE) {
  if (integer && any(!grepl('^[0-9]+$', x))) fail('Counts must be raw non-negative integers, not TPM/FPKM or normalized values')
  y <- suppressWarnings(as.numeric(x))
  if (anyNA(y) || any(!is.finite(y)) || any(y<0) || any(y>.Machine$integer.max)) fail('Counts/lengths require finite non-negative values within the integer range')
  y
}
samples <- read_tsv(req$samples)
required <- c('sample_id','condition','biological_replicate')
if (!all(required %in% names(samples))) fail('Sample sheet needs sample_id, condition and biological_replicate columns')
if (nrow(samples)<4 || nrow(samples)>64) fail('Provide 4 to 64 independent biological samples')
for (column in required) if (!identifier(samples[[column]])) fail(paste('Invalid identifier in',column))
if (anyDuplicated(samples$sample_id) || anyDuplicated(samples$biological_replicate)) fail('Sample and biological replicate IDs must be globally unique; technical/paired replicates are not supported')
if (any(table(samples$condition)<2)) fail('Each condition needs at least two independent biological replicates; three or more are preferable')
if (!all(c(req$numerator,req$denominator) %in% samples$condition) || req$numerator==req$denominator) fail('Contrast must name two different observed conditions')
samples$condition <- relevel(factor(samples$condition), ref=req$denominator)
if (req$design == 'batch-condition') {
  if (!'batch' %in% names(samples) || !identifier(samples$batch) || length(unique(samples$batch))<2) fail('Batch-adjusted design requires at least two valid batch levels')
  samples$batch <- factor(samples$batch)
  design <- ~ batch + condition
} else if (req$design == 'condition') design <- ~ condition else fail('Unsupported design')
rownames(samples) <- samples$sample_id
model <- model.matrix(design, samples)
if (qr(model)$rank != ncol(model)) fail('Design is confounded or not full rank; batch cannot be completely confounded with condition')
if (nrow(model)-qr(model)$rank < 2) fail('Design needs at least two residual degrees of freedom')
rownames(samples) <- samples$sample_id
check_ids <- function(ids, what) {
  if (anyNA(ids) || any(ids=='') || anyDuplicated(ids) || any(grepl('[\r\n\t]',ids))) fail(paste(what,'identifiers must be nonempty and unique'))
}
if (req$mode == 'counts') {
  x <- read_tsv(req$files[[1]])
  if (names(x)[1] != 'gene_id') fail('Count matrix first column must be gene_id; TPM and featureCounts tables require their appropriate operation')
  check_ids(x[[1]], 'Gene')
  if (!setequal(names(x)[-1],samples$sample_id) || ncol(x)!=nrow(samples)+1) fail('Matrix sample columns must exactly match sample_id values')
  counts <- vapply(x[samples$sample_id], number, numeric(nrow(x)), integer=TRUE)
  rownames(counts) <- x[[1]]
} else {
  if (!'input_index' %in% names(samples) || any(!grepl('^[1-9][0-9]*$',samples$input_index))) fail('Fan-in sample sheet requires input_index for each selected count file')
  index <- as.integer(samples$input_index)
  if (length(req$files)!=nrow(samples) || !setequal(index,seq_len(nrow(samples)))) fail('input_index must map every selected file exactly once')
  files <- req$files[index]
  names(files) <- samples$sample_id
  if (req$mode == 'featurecounts') {
    matrices <- lapply(files, function(f) {
      z <- read.delim(f,header=TRUE,sep='\t',comment.char='#',quote='',check.names=FALSE,colClasses='character',na.strings=NULL)
      if (ncol(z)!=7 || !identical(names(z)[1:6],c('Geneid','Chr','Start','End','Strand','Length')) || nrow(z)<1) fail('Select one-sample featureCounts raw gene-count tables, not assignment summaries')
      check_ids(z$Geneid,'Gene')
      number(z[[7]],integer=TRUE)
      z
    })
    reference <- matrices[[1]][1:6]
    for (z in matrices) if (!identical(z[1:6],reference)) fail('featureCounts files must use identical genes, coordinates, lengths and gene ordering from the same annotation')
    counts <- vapply(matrices,function(z) number(z[[7]],integer=TRUE),numeric(nrow(reference)))
    rownames(counts) <- reference$Geneid
  } else if (req$mode == 'kallisto') {
    mapping <- read_tsv(req$tx2gene)
    if (!identical(names(mapping),c('transcript_id','gene_id'))) fail('tx2gene requires transcript_id and gene_id columns')
    check_ids(mapping$transcript_id,'Transcript mapping')
    if (any(mapping$gene_id=='')) fail('Mapping gene identifiers cannot be empty')
    ids <- NULL; lengths <- NULL
    for (f in files) {
      z <- read_tsv(f)
      if (!identical(names(z),c('target_id','length','eff_length','est_counts','tpm'))) fail('kallisto input must be an abundance.tsv table with estimated counts, TPM and effective lengths')
      check_ids(z$target_id,'Transcript')
      if (is.null(ids)) { ids<-z$target_id; lengths<-z$length }
      if (!identical(z$target_id,ids) || !identical(z$length,lengths)) fail('kallisto files must use identical transcript IDs, order and transcript lengths')
      for (col in c('length','eff_length','est_counts','tpm')) number(z[[col]])
      if (any(number(z$length)==0) || any(number(z$eff_length)==0)) fail('Transcript and effective lengths must be positive')
    }
    if (!all(ids %in% mapping$transcript_id)) fail('Every quantified transcript must have an exact tx2gene mapping; identifier versions are not silently removed')
    txi <- tximport(files,type='kallisto',tx2gene=mapping,countsFromAbundance='no',dropInfReps=TRUE,
                    importer=function(path,...) read.delim(path,check.names=FALSE,stringsAsFactors=FALSE))
    counts <- txi$counts
  } else fail('Unsupported input operation')
}
if (nrow(counts)>250000) fail('This local operation supports at most 250000 genes')
if (any(colSums(counts)<=0)) fail('Every sample needs a positive count library')
if (req$mode == 'kallisto') {
  dds <- DESeqDataSetFromTximport(txi,colData=samples,design=design)
} else {
  storage.mode(counts) <- 'integer'
  dds <- DESeqDataSetFromMatrix(countData=counts,colData=samples,design=design)
}
keep <- rowSums(counts(dds)) >= req$minCount
if (sum(keep)<20) fail('At least 20 genes must pass the minimum total-count filter for this operation')
dds <- dds[keep,]
# Serial upstream Wald inference; standard outlier and independent-filter rules remain active.
dds <- DESeq(dds,test='Wald',fitType='parametric',sfType='ratio',betaPrior=FALSE,
             minReplicatesForReplace=Inf,parallel=FALSE,quiet=FALSE)
res <- results(dds,contrast=c('condition',req$numerator,req$denominator),alpha=req$alpha,
               independentFiltering=TRUE,cooksCutoff=TRUE,pAdjustMethod='BH',parallel=FALSE)
result <- as.data.frame(res)
result$status <- ifelse(is.na(result$pvalue),'not_tested_or_cooks_outlier',ifelse(is.na(result$padj),'independent_filtered',ifelse(result$padj<req$alpha,'significant','not_significant')))
# Include filtered genes explicitly; never confuse absent/NA inference with non-significance.
allresult <- data.frame(gene_id=rownames(counts),baseMean=NA_real_,log2FoldChange=NA_real_,lfcSE=NA_real_,stat=NA_real_,pvalue=NA_real_,padj=NA_real_,status='prefiltered',check.names=FALSE)
matchidx <- match(rownames(result),allresult$gene_id)
allresult[matchidx,names(result)] <- result
write.table(allresult,file.path(req$run,'differential-expression.tsv'),sep='\t',quote=FALSE,row.names=FALSE,na='NA')
write.table(data.frame(gene_id=rownames(dds),counts(dds,normalized=TRUE),check.names=FALSE),file.path(req$run,'normalized-counts.tsv'),sep='\t',quote=FALSE,row.names=FALSE)
write.table(data.frame(sample_id=rownames(model),model,check.names=FALSE),file.path(req$run,'design-matrix.tsv'),sep='\t',quote=FALSE,row.names=FALSE)
write.table(data.frame(gene_id=rownames(counts),counts,check.names=FALSE),file.path(req$run,'imported-gene-counts.tsv'),sep='\t',quote=FALSE,row.names=FALSE)
vsd <- varianceStabilizingTransformation(dds,blind=FALSE)
v <- apply(assay(vsd),1,var)
p <- prcomp(t(assay(vsd)[order(v,decreasing=TRUE)[seq_len(min(500,length(v)))],,drop=FALSE]))
percent <- p$sdev^2 / sum(p$sdev^2)
pdf(file.path(req$run,'pca.pdf'),width=8,height=6)
plot(p$x[,1],p$x[,2],col=as.integer(samples$condition),pch=19,xlab=sprintf('PC1 (%.1f%%)',100*percent[1]),ylab=sprintf('PC2 (%.1f%%)',100*percent[2]),main='Design-aware VST; top 500 variable genes')
text(p$x[,1],p$x[,2],labels=samples$sample_id,pos=3,cex=.7)
legend('topright',legend=levels(samples$condition),col=seq_along(levels(samples$condition)),pch=19)
dev.off()
pdf(file.path(req$run,'ma.pdf'),width=8,height=6)
plotMA(res,alpha=req$alpha,main=paste(req$numerator,'vs',req$denominator,'(unshrunk log2 fold change)'))
dev.off()
write.table(data.frame(sample_id=rownames(p$x),p$x[,1:2,drop=FALSE]),file.path(req$run,'pca-coordinates.tsv'),sep='\t',quote=FALSE,row.names=FALSE)
summary <- list(schema=1,tool='DESeq2',version=as.character(packageVersion('DESeq2')),tximportVersion=as.character(packageVersion('tximport')),R=R.version.string,
 mode=req$mode,samples=nrow(samples),genesInput=nrow(counts),genesTested=nrow(dds),genesPrefiltered=sum(!keep),significant=sum(res$padj<req$alpha,na.rm=TRUE),
 positiveSignificant=sum(res$padj<req$alpha & res$log2FoldChange>0,na.rm=TRUE),negativeSignificant=sum(res$padj<req$alpha & res$log2FoldChange<0,na.rm=TRUE),
 design=paste(deparse(design),collapse=''),contrast=c(req$numerator,req$denominator),alpha=req$alpha,minTotalCount=req$minCount,
 test='Wald',normalization=if(req$mode=='kallisto') 'DESeqDataSetFromTximport counts with average-transcript-length offsets' else 'DESeq2 median-of-ratios size factors',
 dispersionFitRequested='parametric',dispersionFitUsed=attr(dispersionFunction(dds),'fitType'),pAdjustment='BH',independentFiltering=TRUE,cooksCutoff=TRUE,
 automaticOutlierReplacement=FALSE,foldChangeShrinkage=FALSE,replicates='Independent biological samples asserted by explicit metadata; identity cannot establish biological independence',
 inputOrder=data.frame(sample_id=samples$sample_id,input_index=if('input_index'%in%names(samples)) samples$input_index else NA_character_),
 runtimePackages=as.list(setNames(as.character(packageVersion('DESeq2')),'DESeq2')))
write_json(summary,file.path(req$run,'analysis-summary.json'),auto_unbox=TRUE,pretty=TRUE,na='null')
capture.output(sessionInfo(),file=file.path(req$run,'R-session.txt'))
methods <- c(paste('Differential gene expression was tested with DESeq2',packageVersion('DESeq2'),'under',R.version.string),
 paste('Input operation:',req$mode,'; formula:',summary$design,'; contrast:',req$numerator,'versus',req$denominator),
 paste('Genes with total counts below',req$minCount,'were prefiltered. Wald tests used median-of-ratios normalization (with tximport length offsets for kallisto), parametric dispersion fitting with upstream fallback, Cook distance filtering, independent filtering and Benjamini-Hochberg adjustment at alpha',req$alpha),
 'Fold changes are unshrunk maximum-likelihood log2 estimates. Automatic count replacement is disabled. PCA uses design-aware variance stabilization and up to 500 variable genes.',
 'Two or more explicitly asserted independent biological replicates per condition were required; this does not establish adequate power or verify sample independence.')
writeLines(methods,file.path(req$run,'analysis-methods.txt'))
