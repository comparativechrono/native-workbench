/*
 * paircheck 1.0.1 -- strict, streaming paired FASTQ validation.
 * Copyright (c) 2026 Native Workbench contributors. MIT license.
 *
 * Permission is hereby granted, free of charge, to any person obtaining a
 * copy of this software and associated documentation files (the "Software"),
 * to deal in the Software without restriction, including without limitation
 * the rights to use, copy, modify, merge, publish, distribute, sublicense,
 * and/or sell copies of the Software, and to permit persons to whom the
 * Software is furnished to do so, subject to the following conditions:
 * The above copyright notice and this permission notice shall be included
 * in all copies or substantial portions of the Software.
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
 * THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
 * FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
 * DEALINGS IN THE SOFTWARE.
 *
 * The parser supports LF/CRLF, wrapped sequence and quality lines, ordinary
 * or concatenated gzip streams, and first-token read IDs. Only terminal
 * /1 and /2 are normalized; if present they must agree with the mate slot.
 * Limits: 64 MiB per physical line and 64 KiB per read identifier.
 * Every gzip member must finish with a valid CRC/size trailer. Unlike gzread,
 * trailing garbage or an incomplete next member is rejected, not ignored.
 * It validates structure/pairing, not biological quality or library design.
 */
#include <errno.h>
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <zlib.h>

#define VERSION "1.0.0"
#define BUFFER_BYTES 65536u
#define MAX_LINE_BYTES (64u * 1024u * 1024u)
#define MAX_NAME_BYTES 65536u

typedef struct {
    FILE *file;
    const char *path;
    unsigned char buffer[BUFFER_BYTES];
    unsigned char compressed[BUFFER_BYTES];
    z_stream stream;
    int format_known, gzip, inflate_initialized, member_complete, raw_eof;
    size_t at, count;
    char *line;
    size_t length, capacity;
    uint64_t line_number;
    int ended;
    char error[512];
} Reader;

typedef struct {
    char *name;
    size_t name_length, name_capacity;
    uint64_t bases;
} Record;

static int error_message(Reader *reader, const char *message) {
    snprintf(reader->error, sizeof(reader->error), "%s", message);
    return -1;
}

static int compressed_input(Reader *reader) {
    size_t count;
    if (reader->stream.avail_in || reader->raw_eof) return 0;
    count = fread(reader->compressed, 1, sizeof(reader->compressed), reader->file);
    if (ferror(reader->file)) return error_message(reader, "input file read failed");
    reader->stream.next_in = reader->compressed;
    reader->stream.avail_in = (unsigned)count;
    reader->raw_eof = feof(reader->file) != 0;
    return 0;
}

/* Fill decoded bytes. Reaching physical EOF is only success after a complete
 * gzip member, including its CRC32 and ISIZE trailer. No trailing bytes are
 * silently discarded, including a partial next gzip header. */
static int fill_buffer(Reader *reader) {
    reader->at = reader->count = 0;
    if (!reader->format_known) {
        size_t count = fread(reader->compressed, 1, sizeof(reader->compressed), reader->file);
        if (ferror(reader->file)) return error_message(reader, "input file read failed");
        reader->raw_eof = feof(reader->file) != 0;
        reader->format_known = 1;
        reader->gzip = count && reader->compressed[0] == 0x1f &&
            (count == 1 || reader->compressed[1] == 0x8b);
        if (!reader->gzip) {
            memcpy(reader->buffer, reader->compressed, count);
            reader->count = count;
            if (!count) reader->ended = 1;
            return 0;
        }
        if (inflateInit2(&reader->stream, 15 + 16) != Z_OK)
            return error_message(reader, "cannot initialize gzip decompression");
        reader->inflate_initialized = 1;
        reader->stream.next_in = reader->compressed;
        reader->stream.avail_in = (unsigned)count;
    }
    if (!reader->gzip) {
        reader->count = fread(reader->buffer, 1, sizeof(reader->buffer), reader->file);
        if (ferror(reader->file)) return error_message(reader, "input file read failed");
        if (!reader->count) reader->ended = 1;
        return 0;
    }
    reader->stream.next_out = reader->buffer;
    reader->stream.avail_out = sizeof(reader->buffer);
    for (;;) {
        unsigned before_in, before_out;
        int status;
        if (compressed_input(reader) < 0) return -1;
        if (reader->member_complete) {
            size_t input_offset = (const unsigned char *)reader->stream.next_in - reader->compressed;
            unsigned char *next_out = reader->stream.next_out;
            unsigned avail_in = reader->stream.avail_in, avail_out = reader->stream.avail_out;
            if (!avail_in && reader->raw_eof) { reader->ended = 1; break; }
            if (inflateReset2(&reader->stream, 15 + 16) != Z_OK)
                return error_message(reader, "cannot initialize the next gzip member");
            reader->stream.next_in = reader->compressed + input_offset; reader->stream.avail_in = avail_in;
            reader->stream.next_out = next_out; reader->stream.avail_out = avail_out;
            reader->member_complete = 0;
        }
        if (!reader->stream.avail_in && reader->raw_eof)
            return error_message(reader, "truncated gzip member: missing end marker or CRC/size trailer");
        before_in = reader->stream.avail_in;
        before_out = reader->stream.avail_out;
        status = inflate(&reader->stream, Z_NO_FLUSH);
        if (status == Z_STREAM_END) reader->member_complete = 1;
        else if (status != Z_OK && status != Z_BUF_ERROR) {
            snprintf(reader->error, sizeof(reader->error), "gzip integrity error: %s",
                reader->stream.msg ? reader->stream.msg : "invalid compressed stream");
            return -1;
        }
        if (!reader->stream.avail_out) break;
        if (status != Z_STREAM_END && before_in == reader->stream.avail_in && before_out == reader->stream.avail_out)
            return error_message(reader, "gzip decompression made no progress");
    }
    reader->count = sizeof(reader->buffer) - reader->stream.avail_out;
    return 0;
}

static int next_byte(Reader *reader) {
    if (reader->at == reader->count) {
        if (reader->ended) return -1;
        if (fill_buffer(reader) < 0) return -2;
        if (!reader->count) return -1;
    }
    return reader->buffer[reader->at++];
}

/* 1: physical line, 0: clean EOF, -1: input/size/allocation error. */
static int read_line(Reader *reader) {
    int byte;
    reader->length = 0;
    for (;;) {
        byte = next_byte(reader);
        if (byte == -2) return -1;
        if (byte == -1) {
            if (!reader->length) return 0;
            break;
        }
        if (byte == '\n') break;
        if (byte == 0) return error_message(reader, "NUL byte in FASTQ input");
        if (reader->length == MAX_LINE_BYTES)
            return error_message(reader, "physical FASTQ line exceeds the 64 MiB limit");
        if (reader->length + 1 >= reader->capacity) {
            size_t capacity = reader->capacity ? reader->capacity * 2 : 1024;
            char *line;
            if (capacity > (size_t)MAX_LINE_BYTES + 1) capacity = (size_t)MAX_LINE_BYTES + 1;
            line = (char *)realloc(reader->line, capacity);
            if (!line) return error_message(reader, "out of memory reading a FASTQ line");
            reader->line = line;
            reader->capacity = capacity;
        }
        reader->line[reader->length++] = (char)byte;
    }
    ++reader->line_number;
    if (reader->length && reader->line[reader->length - 1] == '\r') --reader->length;
    if (reader->line) reader->line[reader->length] = '\0';
    return 1;
}

static int identifier(Reader *reader, Record *record, unsigned mate) {
    size_t end = 1, length, i;
    if (reader->length < 2 || reader->line[0] != '@')
        return error_message(reader, "expected an @ header at the beginning of a FASTQ record");
    while (end < reader->length && reader->line[end] != ' ' && reader->line[end] != '\t') ++end;
    length = end - 1;
    if (!length || length > MAX_NAME_BYTES)
        return error_message(reader, "read identifier is empty or exceeds 64 KiB");
    for (i = 1; i < reader->length; ++i) {
        const unsigned char byte = (unsigned char)reader->line[i];
        if (byte < 32 && byte != '\t') return error_message(reader, "control character in FASTQ header");
        if (byte == 127) return error_message(reader, "control character in FASTQ header");
    }
    if (length >= 2 && reader->line[end - 2] == '/' &&
        (reader->line[end - 1] == '1' || reader->line[end - 1] == '2')) {
        if (mate && (unsigned)(reader->line[end - 1] - '0') != mate)
            return error_message(reader, "terminal /1 or /2 identifier suffix is in the wrong mate file");
        length -= 2;
    }
    if (!length) return error_message(reader, "read identifier has no name before its mate suffix");
    if (length + 1 > record->name_capacity) {
        char *name = (char *)realloc(record->name, length + 1);
        if (!name) return error_message(reader, "out of memory reading an identifier");
        record->name = name;
        record->name_capacity = length + 1;
    }
    memcpy(record->name, reader->line + 1, length);
    record->name[length] = '\0';
    record->name_length = length;
    return 0;
}

/* 1: complete FASTQ record, 0: clean EOF, -1: malformed input. */
static int read_record(Reader *reader, Record *record, unsigned mate) {
    uint64_t qualities = 0;
    int status = read_line(reader);
    size_t i;
    if (status <= 0) return status;
    if (identifier(reader, record, mate) < 0) return -1;
    record->bases = 0;
    for (;;) {
        status = read_line(reader);
        if (status < 0) return -1;
        if (!status) return error_message(reader, "truncated record: missing + separator and quality");
        if (reader->length && reader->line[0] == '+') break;
        if (!reader->length) return error_message(reader, "empty sequence line in FASTQ record");
        for (i = 0; i < reader->length; ++i)
            if (!strchr("ACGTURYSWKMBDHVNacgturyswkmbdhvn", (unsigned char)reader->line[i]))
                return error_message(reader, "sequence contains a non-IUPAC nucleotide character");
        if (record->bases > UINT64_MAX - reader->length)
            return error_message(reader, "sequence length exceeds the supported counter range");
        record->bases += reader->length;
    }
    if (!record->bases) return error_message(reader, "empty sequence in FASTQ record");
    while (qualities < record->bases) {
        status = read_line(reader);
        if (status < 0) return -1;
        if (!status) return error_message(reader, "truncated record: quality is shorter than the sequence");
        if (!reader->length) return error_message(reader, "empty quality line in FASTQ record");
        if ((uint64_t)reader->length > record->bases - qualities)
            return error_message(reader, "quality is longer than the sequence");
        for (i = 0; i < reader->length; ++i) {
            unsigned char byte = (unsigned char)reader->line[i];
            if (byte < 33 || byte > 126)
                return error_message(reader, "quality contains a character outside printable Phred33 ASCII");
        }
        qualities += reader->length;
    }
    return 1;
}

static void describe_error(const Reader *reader, unsigned mate, uint64_t pair) {
    fprintf(stderr, "paircheck: mate %u, pair %" PRIu64 ", near line %" PRIu64 ": %s\n",
        mate, pair, reader->line_number, reader->error);
}

static void usage(FILE *stream) {
    fputs("paircheck " VERSION "\nUsage: paircheck --reads1 FILE --reads2 FILE\n"
        "Validates plain/gzip paired FASTQ and writes a JSON summary.\n", stream);
}

static int paired_main(int argc, char **argv) {
    const char *paths[2] = {NULL, NULL};
    Reader readers[2];
    Record records[2];
    uint64_t pairs = 0, bases[2] = {0, 0};
    unsigned mate;
    int i, failed = 0;
    memset(readers, 0, sizeof(readers));
    memset(records, 0, sizeof(records));
    if (argc == 2 && !strcmp(argv[1], "--version")) { puts("paircheck " VERSION); return 0; }
    if (argc == 2 && !strcmp(argv[1], "--help")) { usage(stdout); return 0; }
    for (i = 1; i < argc; ++i) {
        unsigned index;
        if (!strcmp(argv[i], "--reads1")) index = 0;
        else if (!strcmp(argv[i], "--reads2")) index = 1;
        else { fprintf(stderr, "paircheck: unknown option: %s\n", argv[i]); usage(stderr); return 2; }
        if (paths[index] || i + 1 == argc || !*argv[i + 1]) {
            fputs("paircheck: each mate option requires exactly one nonempty filename\n", stderr); return 2;
        }
        paths[index] = argv[++i];
    }
    if (!paths[0] || !paths[1]) { usage(stderr); return 2; }
    for (mate = 0; mate < 2; ++mate) {
        readers[mate].path = paths[mate];
        readers[mate].file = fopen(paths[mate], "rb");
        if (!readers[mate].file) {
            fprintf(stderr, "paircheck: cannot open mate %u: %s\n", mate + 1, strerror(errno));
            failed = 1; goto cleanup;
        }
    }
    for (;;) {
        int first = read_record(&readers[0], &records[0], 1);
        int second;
        if (first < 0) { describe_error(&readers[0], 1, pairs + 1); failed = 1; break; }
        second = read_record(&readers[1], &records[1], 2);
        if (second < 0) { describe_error(&readers[1], 2, pairs + 1); failed = 1; break; }
        if (!first && !second) break;
        if (first != second) {
            fprintf(stderr, "paircheck: unequal read counts at pair %" PRIu64 "\n", pairs + 1);
            failed = 1; break;
        }
        if (records[0].name_length != records[1].name_length ||
            memcmp(records[0].name, records[1].name, records[0].name_length)) {
            fprintf(stderr, "paircheck: read identifiers differ at pair %" PRIu64 ": %.160s / %.160s\n",
                pairs + 1, records[0].name, records[1].name);
            failed = 1; break;
        }
        if (pairs == UINT64_MAX / 2 || bases[0] > UINT64_MAX - records[0].bases ||
            bases[1] > UINT64_MAX - records[1].bases) {
            fputs("paircheck: record/base counters exceed the supported range\n", stderr); failed = 1; break;
        }
        ++pairs;
        bases[0] += records[0].bases;
        bases[1] += records[1].bases;
    }
    if (!failed && !pairs) { fputs("paircheck: paired FASTQ inputs are empty\n", stderr); failed = 1; }
    if (!failed && bases[0] > UINT64_MAX - bases[1]) {
        fputs("paircheck: combined base count exceeds the supported range\n", stderr); failed = 1;
    }
cleanup:
    for (mate = 0; mate < 2; ++mate) {
        if (readers[mate].inflate_initialized && inflateEnd(&readers[mate].stream) != Z_OK) {
            fprintf(stderr, "paircheck: decompressor cleanup failed for mate %u\n", mate + 1); failed = 1;
        }
        if (readers[mate].file && fclose(readers[mate].file) != 0) {
            fprintf(stderr, "paircheck: input stream close failed for mate %u\n", mate + 1); failed = 1;
        }
        free(readers[mate].line); free(records[mate].name);
    }
    if (failed) return 1;
    if (printf("{\"valid\":true,\"pairs\":%" PRIu64 ",\"reads\":%" PRIu64 ",\"bases\":%" PRIu64
        ",\"bases_r1\":%" PRIu64 ",\"bases_r2\":%" PRIu64 "}\n", pairs, pairs * 2,
        bases[0] + bases[1], bases[0], bases[1]) < 0 || fflush(stdout) || ferror(stdout)) {
        fputs("paircheck: could not write validation JSON\n", stderr); return 1;
    }
    return 0;
}

/* Native RNA pack extension: the same strict parser for one FASTQ file. */
int main(int argc, char **argv) {
    Reader reader = {0}; Record record = {0}; uint64_t count = 0, bases = 0;
    int status, failed = 0;
    if (argc != 3 || strcmp(argv[1], "--single")) return paired_main(argc, argv);
    reader.path = argv[2]; reader.file = fopen(reader.path, "rb");
    if (!reader.file) { perror("readcheck: cannot open FASTQ"); return 1; }
    while ((status = read_record(&reader, &record, 0)) > 0) {
        if (count == UINT64_MAX || bases > UINT64_MAX - record.bases) { failed = 1; break; }
        ++count; bases += record.bases;
    }
    if (status < 0) { describe_error(&reader, 0, count + 1); failed = 1; }
    if (!count) { fputs("readcheck: empty FASTQ\n", stderr); failed = 1; }
    if (reader.inflate_initialized && inflateEnd(&reader.stream) != Z_OK) failed = 1;
    if (fclose(reader.file)) failed = 1;
    free(reader.line); free(record.name);
    if (failed) return 1;
    if (printf("{\"valid\":true,\"reads\":%" PRIu64 ",\"bases\":%" PRIu64 "}\n", count, bases) < 0 || fflush(stdout) || ferror(stdout)) return 1;
    return 0;
}
