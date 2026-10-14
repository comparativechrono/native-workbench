#define WIN32_LEAN_AND_MEAN
#define _WIN32_WINNT 0x0602
#include <windows.h>
#include <commdlg.h>
#include <shellapi.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <wchar.h>
#include "../include/bw_api.h"

/* This host runs a trusted, prepared native module. It is not an ELF loader,
   Linux kernel, instruction emulator, or security sandbox. */
extern const unsigned char bw_module_start[];
extern const unsigned char bw_module_end[];

#ifndef BW_BUILD_VERSION
#define BW_BUILD_VERSION "0.1.0-experiment"
#endif

typedef struct {
    HANDLE input, output, error;
    SRWLOCK output_lock, error_lock;
    volatile LONG first_error;
    volatile LONG in_parallel;
    char diagnostics[4096];
    size_t diagnostics_size;
} HostContext;

static volatile LONG stop_requested;

static int handle_valid(HANDLE h) {
    return h != NULL && h != INVALID_HANDLE_VALUE;
}

static void remember_error(HostContext *c, DWORD error) {
    if (error == ERROR_SUCCESS) error = ERROR_GEN_FAILURE;
    InterlockedCompareExchange(&c->first_error, (LONG)error, 0);
}

static BOOL WINAPI console_control(DWORD event) {
    if (event != CTRL_C_EVENT && event != CTRL_BREAK_EVENT) return FALSE;
    InterlockedExchange(&stop_requested, 1);
    return TRUE;
}

typedef struct {
    HANDLE main_thread;
    HANDLE completed;
} CancellationWatch;

static DWORD WINAPI cancellation_watchdog(void *opaque) {
    CancellationWatch *watch = (CancellationWatch *)opaque;
    /* A single cancellation call could run just before ReadFile/WriteFile
       enters the kernel. Repeating after a timed event wait closes that race.
       The handler only writes the flag; it never borrows teardown handles. */
    while (WaitForSingleObject(watch->completed, 50) == WAIT_TIMEOUT) {
        if (InterlockedCompareExchange(&stop_requested, 0, 0))
            CancelSynchronousIo(watch->main_thread);
    }
    return 0;
}

static int64_t BW_ABI host_read(void *context, void *buffer, uint64_t capacity) {
    HostContext *c = (HostContext *)context;
    if (InterlockedCompareExchange(&stop_requested, 0, 0)) {
        remember_error(c, ERROR_OPERATION_ABORTED);
        return -1;
    }
    DWORD got = 0;
    DWORD count = (DWORD)(capacity > 0x40000000ULL ? 0x40000000ULL : capacity);
    if (!count) return 0;
    if (ReadFile(c->input, buffer, count, &got, NULL)) return (int64_t)got;
    DWORD e = GetLastError();
    if (e == ERROR_BROKEN_PIPE || e == ERROR_HANDLE_EOF) return 0;
    remember_error(c, e);
    return -1;
}

static int64_t BW_ABI host_write(void *context, uint32_t stream,
                               const void *buffer, uint64_t size) {
    HostContext *c = (HostContext *)context;
    if (stream != 1 && stream != 2) return -1;
    if (stream == 1 && InterlockedCompareExchange(&stop_requested, 0, 0)) {
        remember_error(c, ERROR_OPERATION_ABORTED);
        return -1;
    }
    SRWLOCK *lock = stream == 1 ? &c->output_lock : &c->error_lock;
    HANDLE output = stream == 1 ? c->output : c->error;
    DWORD count = (DWORD)(size > 0x40000000ULL ? 0x40000000ULL : size);
    DWORD written = 0;
    AcquireSRWLockExclusive(lock);
    if (stream == 2) {
        size_t available = sizeof(c->diagnostics) - c->diagnostics_size - 1;
        size_t copied = count < available ? count : available;
        memcpy(c->diagnostics + c->diagnostics_size, buffer, copied);
        c->diagnostics_size += copied;
        c->diagnostics[c->diagnostics_size] = 0;
        if (!handle_valid(output)) {
            ReleaseSRWLockExclusive(lock);
            return count;
        }
    }
    BOOL ok = WriteFile(output, buffer, count, &written, NULL);
    if (!ok) remember_error(c, GetLastError());
    ReleaseSRWLockExclusive(lock);
    return ok ? (int64_t)written : -1;
}

static void *BW_ABI host_alloc(void *context, uint64_t size) {
    HostContext *c = (HostContext *)context;
    void *p = HeapAlloc(GetProcessHeap(), 0, (SIZE_T)(size ? size : 1));
    if (!p) remember_error(c, ERROR_NOT_ENOUGH_MEMORY);
    return p;
}

static void BW_ABI host_free(void *context, void *buffer) {
    (void)context;
    if (buffer) HeapFree(GetProcessHeap(), 0, buffer);
}

typedef struct {
    volatile LONG64 next;
    uint32_t count;
    bw_task task;
    void *context;
} ParallelJob;

static DWORD WINAPI work_queue(void *opaque) {
    ParallelJob *job = (ParallelJob *)opaque;
    for (;;) {
        LONG64 index = InterlockedIncrement64(&job->next) - 1;
        if ((uint64_t)index >= job->count) break;
        job->task(job->context, (uint32_t)index);
    }
    return 0;
}

static int32_t BW_ABI host_parallel(void *context, uint32_t count,
                                   uint32_t max_threads, bw_task task,
                                   void *task_context) {
    HostContext *c = (HostContext *)context;
    if (!task || !max_threads || max_threads > 64) return -1;
    if (InterlockedCompareExchange(&c->in_parallel, 1, 0)) return -1;
    if (!count) {
        InterlockedExchange(&c->in_parallel, 0);
        return 0;
    }
    uint32_t threads = max_threads < count ? max_threads : count;
    ParallelJob job = {0, count, task, task_context};
    HANDLE workers[63];
    uint32_t created = 0;
    for (uint32_t i = 1; i < threads; ++i) {
        HANDLE h = CreateThread(NULL, 0, work_queue, &job, 0, NULL);
        /* Resource pressure reduces parallelism; the calling thread still
           processes all remaining work, preserving exactly-once semantics. */
        if (!h) break;
        workers[created++] = h;
    }
    work_queue(&job);
    int result = 0;
    for (uint32_t i = 0; i < created; ++i) {
        DWORD waited = WaitForSingleObject(workers[i], INFINITE);
        if (waited != WAIT_OBJECT_0) {
            /* Our own valid thread handle should never fail to wait. Do not
               return while a worker might still use the stack-allocated job. */
            DWORD code = STILL_ACTIVE;
            while (GetExitCodeThread(workers[i], &code) && code == STILL_ACTIVE)
                SwitchToThread();
            result = -1;
        }
        CloseHandle(workers[i]);
    }
    InterlockedExchange(&c->in_parallel, 0);
    return result;
}

static int32_t BW_ABI host_cancelled(void *context) {
    (void)context;
    return InterlockedCompareExchange(&stop_requested, 0, 0) != 0;
}

static void write_console_text(HANDLE h, const char *text) {
    if (!handle_valid(h)) return;
    size_t left = strlen(text);
    while (left) {
        DWORD written = 0;
        DWORD part = (DWORD)(left > 0x40000000U ? 0x40000000U : left);
        if (!WriteFile(h, text, part, &written, NULL) || !written) return;
        text += written;
        left -= written;
    }
}

static void report(int gui, const wchar_t *message, DWORD error) {
    wchar_t detail[1024] = L"";
    wchar_t combined[2304];
    if (error) FormatMessageW(FORMAT_MESSAGE_FROM_SYSTEM | FORMAT_MESSAGE_IGNORE_INSERTS,
                             NULL, error, 0, detail, 1024, NULL);
    if (error)
        swprintf(combined, 2304, L"%ls\nWindows error %lu: %ls", message,
                 (unsigned long)error, detail);
    else
        swprintf(combined, 2304, L"%ls", message);
    if (gui) MessageBoxW(NULL, combined, L"Native FASTQ experiment", MB_OK | MB_ICONERROR);
    char utf8[9216];
    int n = WideCharToMultiByte(CP_UTF8, 0, combined, -1, utf8, sizeof(utf8), NULL, NULL);
    if (n > 0) {
        write_console_text(GetStdHandle(STD_ERROR_HANDLE), utf8);
        write_console_text(GetStdHandle(STD_ERROR_HANDLE), "\r\n");
    }
}

static void usage(void) {
    write_console_text(GetStdHandle(STD_ERROR_HANDLE),
        "Native FASTQ experiment " BW_BUILD_VERSION " (ABI 1, x86-64)\r\n"
        "Usage: bwfastq.exe stats|revcomp --input PATH --output PATH [--threads 1..64]\r\n"
        "Use '-' for stdin or stdout. Input must be uncompressed FASTQ.\r\n"
        "Output files must be new; existing files are never overwritten.\r\n"
        "No arguments: choose input/output files for a statistics run.\r\n");
}

static int choose_files(wchar_t *input, wchar_t *output) {
    OPENFILENAMEW dialog;
    memset(&dialog, 0, sizeof(dialog));
    dialog.lStructSize = sizeof(dialog);
    dialog.lpstrFile = input;
    dialog.nMaxFile = 32768;
    dialog.lpstrTitle = L"Choose uncompressed FASTQ input";
    dialog.lpstrFilter = L"FASTQ files (*.fastq;*.fq)\0*.fastq;*.fq\0All files\0*.*\0\0";
    dialog.Flags = OFN_FILEMUSTEXIST | OFN_PATHMUSTEXIST | OFN_NOCHANGEDIR | OFN_EXPLORER;
    if (!GetOpenFileNameW(&dialog)) return CommDlgExtendedError() ? -1 : 0;
    wcscpy(output, L"fastq-statistics.json");
    dialog.lpstrFile = output;
    dialog.lpstrTitle = L"Choose a NEW statistics output file (existing files are protected)";
    dialog.lpstrFilter = L"JSON statistics (*.json)\0*.json\0All files\0*.*\0\0";
    dialog.lpstrDefExt = L"json";
    dialog.Flags = OFN_PATHMUSTEXIST | OFN_NOCHANGEDIR | OFN_EXPLORER;
    if (!GetSaveFileNameW(&dialog)) return CommDlgExtendedError() ? -1 : 0;
    return 1;
}

static int run_module(const char *operation, const char *threads,
                      const wchar_t *input_path, const wchar_t *output_path,
                      int gui) {
    HostContext context;
    memset(&context, 0, sizeof(context));
    context.input = INVALID_HANDLE_VALUE;
    context.output = INVALID_HANDLE_VALUE;
    context.error = GetStdHandle(STD_ERROR_HANDLE);
    int input_owned = wcscmp(input_path, L"-") != 0;
    int output_owned = wcscmp(output_path, L"-") != 0;
    int output_created = 0;
    int output_committed = 0;
    wchar_t *temporary_output = NULL;
    int result = 3;
    context.input = input_owned
        ? CreateFileW(input_path, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING,
                      FILE_ATTRIBUTE_NORMAL | FILE_FLAG_SEQUENTIAL_SCAN, NULL)
        : GetStdHandle(STD_INPUT_HANDLE);
    if (!handle_valid(context.input)) {
        report(gui, L"Cannot open the input file or stdin.", GetLastError());
        goto cleanup;
    }
    if (output_owned) {
        DWORD attributes = GetFileAttributesW(output_path);
        DWORD error = attributes == INVALID_FILE_ATTRIBUTES ? GetLastError() : ERROR_FILE_EXISTS;
        if (attributes != INVALID_FILE_ATTRIBUTES ||
            (error != ERROR_FILE_NOT_FOUND && error != ERROR_PATH_NOT_FOUND)) {
            report(gui, L"Cannot create output. Choose a new filename; existing files are never replaced.", error);
            goto cleanup;
        }
        size_t capacity = wcslen(output_path) + 96;
        temporary_output = malloc(capacity * sizeof(wchar_t));
        if (!temporary_output) {
            report(gui, L"Cannot allocate an output filename.", ERROR_NOT_ENOUGH_MEMORY);
            goto cleanup;
        }
        for (unsigned attempt = 0; attempt < 100; ++attempt) {
            swprintf(temporary_output, capacity, L"%ls.partial.%lu.%llu.%u", output_path,
                     (unsigned long)GetCurrentProcessId(),
                     (unsigned long long)GetTickCount64(), attempt);
            context.output = CreateFileW(temporary_output, GENERIC_WRITE, 0, NULL,
                                         CREATE_NEW, FILE_ATTRIBUTE_NORMAL |
                                         FILE_FLAG_SEQUENTIAL_SCAN, NULL);
            if (handle_valid(context.output)) break;
            if (GetLastError() != ERROR_FILE_EXISTS && GetLastError() != ERROR_ALREADY_EXISTS) break;
        }
    } else {
        context.output = GetStdHandle(STD_OUTPUT_HANDLE);
    }
    if (!handle_valid(context.output)) {
        report(gui, L"Cannot create the temporary output file or open stdout.",
               GetLastError());
        goto cleanup;
    }
    output_created = output_owned;
    SIZE_T module_size = (SIZE_T)((uintptr_t)bw_module_end - (uintptr_t)bw_module_start);
    if (!module_size) {
        report(gui, L"The embedded analysis module is empty.", 0);
        goto cleanup;
    }
    bw_host host = {
        BW_ABI_VERSION, sizeof(bw_host), BW_CAP_PARALLEL, &context,
        host_read, host_write, host_alloc, host_free, host_parallel, host_cancelled
    };
    const char *arguments[] = {operation, threads};
    /* module_embed.S places these exact bytes in an executable PE section.
       No writable/executable allocation or runtime code modification is used. */
    bw_entry_fn entry = (bw_entry_fn)(uintptr_t)bw_module_start;
    result = entry(&host, 2, arguments);
    if (host_cancelled(&context)) result = 130;
    if (!result && output_owned && !FlushFileBuffers(context.output)) {
        remember_error(&context, GetLastError());
        result = 3;
    }
    if (host_cancelled(&context)) result = 130;
    if (output_owned) {
        BOOL closed = CloseHandle(context.output);
        context.output = INVALID_HANDLE_VALUE;
        if (!closed && !result) {
            remember_error(&context, GetLastError());
            result = 3;
        }
        if (host_cancelled(&context)) result = 130;
        if (!result) {
            /* Flags 0 intentionally forbids replacing an existing destination,
               including a file created after the earlier existence check. */
            if (MoveFileExW(temporary_output, output_path, 0)) output_committed = 1;
            else {
                remember_error(&context, GetLastError());
                result = 3;
            }
        }
    }
    if (result) {
        wchar_t reason[4096];
        if (context.diagnostics_size &&
            MultiByteToWideChar(CP_UTF8, 0, context.diagnostics, -1, reason, 4096))
            report(gui, reason, (DWORD)context.first_error);
        else if (result == 130)
            report(gui, L"Analysis cancelled. Incomplete output files are removed.", 0);
        else
            report(gui, L"Analysis failed. Incomplete output files are removed.",
                   (DWORD)context.first_error);
    }
cleanup:
    if (input_owned && handle_valid(context.input)) CloseHandle(context.input);
    if (output_owned && handle_valid(context.output)) {
        if (!CloseHandle(context.output) && result == 0) result = 3;
    }
    if (!output_committed && output_created && !DeleteFileW(temporary_output))
        report(gui, L"The incomplete output could not be removed. Do not use it as a completed result.", GetLastError());
    free(temporary_output);
    if (!result && gui)
        MessageBoxW(NULL, L"Statistics saved successfully.", L"Native FASTQ experiment", MB_OK | MB_ICONINFORMATION);
    return result;
}

int main(void) {
    int argc = 0;
    wchar_t **argv = CommandLineToArgvW(GetCommandLineW(), &argc);
    if (!argv) return 3;
    int gui = argc == 1;
    int result = 4;
    const wchar_t *input = NULL, *output = NULL;
    const char *operation = NULL;
    char threads[3] = "1";
    wchar_t *selected_input = NULL, *selected_output = NULL;
    CancellationWatch watch = {NULL, NULL};
    HANDLE watchdog_thread = NULL;
    BOOL handler_installed = FALSE;
    if (argc == 2 && wcscmp(argv[1], L"--version") == 0) {
        write_console_text(GetStdHandle(STD_OUTPUT_HANDLE),
            "bwfastq " BW_BUILD_VERSION " | ABI 1 | Windows x86-64 | trusted native module\r\n");
        result = 0;
        goto done;
    }
    if (argc == 2 && (wcscmp(argv[1], L"--help") == 0 || wcscmp(argv[1], L"-h") == 0)) {
        usage(); result = 0; goto done;
    }
    if (gui) {
        selected_input = calloc(32768, sizeof(wchar_t));
        selected_output = calloc(32768, sizeof(wchar_t));
        if (!selected_input || !selected_output) { result = 3; goto done; }
        int chosen = choose_files(selected_input, selected_output);
        if (chosen <= 0) {
            if (chosen < 0) report(1, L"The Windows file dialog failed.", CommDlgExtendedError());
            result = chosen ? 3 : 0;
            goto done;
        }
        input = selected_input; output = selected_output; operation = "stats";
    } else {
        if (argc < 2) { usage(); goto done; }
        if (!wcscmp(argv[1], L"stats")) operation = "stats";
        else if (!wcscmp(argv[1], L"revcomp")) operation = "revcomp";
        else { usage(); goto done; }
        int seen_threads = 0;
        for (int i = 2; i < argc; ++i) {
            if (!wcscmp(argv[i], L"--input") && i + 1 < argc && !input) input = argv[++i];
            else if (!wcscmp(argv[i], L"--output") && i + 1 < argc && !output) output = argv[++i];
            else if (!wcscmp(argv[i], L"--threads") && i + 1 < argc && !seen_threads) {
                const wchar_t *number = argv[++i];
                unsigned value = 0;
                if (!*number) { usage(); goto done; }
                for (; *number; ++number) {
                    if (*number < L'0' || *number > L'9' || value > 64) { usage(); goto done; }
                    value = value * 10 + (unsigned)(*number - L'0');
                }
                if (!value || value > 64) { usage(); goto done; }
                snprintf(threads, sizeof(threads), "%u", value);
                seen_threads = 1;
            } else { usage(); goto done; }
        }
        if (!input || !output || !*input || !*output) { usage(); goto done; }
    }
    if (!DuplicateHandle(GetCurrentProcess(), GetCurrentThread(), GetCurrentProcess(),
                         &watch.main_thread, 0, FALSE, DUPLICATE_SAME_ACCESS)) {
        report(gui, L"Cannot initialize cancellable I/O.", GetLastError());
        result = 3;
        goto done;
    }
    watch.completed = CreateEventW(NULL, TRUE, FALSE, NULL);
    if (!watch.completed) {
        report(gui, L"Cannot initialize the cancellation event.", GetLastError());
        result = 3;
        goto done;
    }
    watchdog_thread = CreateThread(NULL, 0, cancellation_watchdog, &watch, 0, NULL);
    if (!watchdog_thread) {
        report(gui, L"Cannot initialize the cancellation monitor.", GetLastError());
        result = 3;
        goto done;
    }
    handler_installed = SetConsoleCtrlHandler(console_control, TRUE);
    result = run_module(operation, threads, input, output, gui);
done:
    if (handler_installed) SetConsoleCtrlHandler(console_control, FALSE);
    if (watchdog_thread) {
        SetEvent(watch.completed);
        WaitForSingleObject(watchdog_thread, INFINITE);
        CloseHandle(watchdog_thread);
    }
    if (watch.completed) CloseHandle(watch.completed);
    if (watch.main_thread) CloseHandle(watch.main_thread);
    free(selected_input);
    free(selected_output);
    LocalFree(argv);
    return result;
}
