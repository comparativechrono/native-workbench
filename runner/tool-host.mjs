/* One program, run in a worker thread of the local runner: a Biowasm build (the same .js and .wasm files the page
   runs), with its files on disk (diskfs.mjs) – what execIO does in the page's Aioli worker (see
   assets/vendor/biowasm/execio-source.txt), in Node:
   - standard input, output and error are real files, bound to descriptors 0, 1 and 2 ("2>&1": both on one file, for
     appending);
   - the run reports its exit status, where the program left its input (stdinPos) and the furthest byte it read
     (stdinMax), and the order in which it wrote to its output and to its errors;
   - the input can be handed over a line at a time (sed in a block that reads a file), and seen as a pipe (wc);
   - the links /home/user → the folder of the person's files, and /data → the example data; /dev/zero;
   - the environment the shell exports, and the clock of another time zone (date, awk, diff);
   - a module of its own for every run, as a process is on Linux.
   workerData: { jsPath, dataPath, wasmModule (compiled), thisProgram, args, io, cwd, mounts: [{ at, dir, readOnly, hide }] } */
import { workerData, parentPort } from 'node:worker_threads';
import fs from 'node:fs';
import { makeDiskFS } from './diskfs.mjs';

const { jsPath, dataPath, wasmModule, thisProgram, args, io, cwd, mounts } = workerData;

async function main() {
  // the loader of a Biowasm build assigns its factory to Module: evaluated here, in this worker's own scope
  const factory = new Function(fs.readFileSync(jsPath, 'utf8') + '\nreturn Module;')();
  const data = dataPath && fs.existsSync(dataPath) ? fs.readFileSync(dataPath) : null;
  // (the environment: the program's C library asks for its size first; room is made for the variables of the run –
  // as in execIO, where the same is done)
  const EV = { arr: 0, buf: 0, n: 0, size: 0, mem: null };
  const memOf = (o) => {
    try {
      for (const v of Object.values(o || {})) if (v instanceof WebAssembly.Memory) return v;
    } catch (x) {
      /* (none) */
    }
    return null;
  };
  const mod = await factory({
    thisProgram,
    instantiateWasm(info, done) {
      try {
        const seen = new Set();
        for (const ns of Object.values(info)) {
          if (!ns || typeof ns !== 'object' || seen.has(ns)) continue;
          seen.add(ns);
          EV.mem = EV.mem || memOf(ns);
          let kg = null, ks = null;
          for (const k of Object.keys(ns)) {
            const v = ns[k];
            if (typeof v !== 'function') continue;
            if (k === 'environ_get' || v.name === '_environ_get') kg = k;
            else if (k === 'environ_sizes_get' || v.name === '_environ_sizes_get') ks = k;
          }
          if (kg === null || ks === null) continue;
          const sg = ns[ks], g = ns[kg];
          ns[ks] = (pc, pb) => {
            const r = sg(pc, pb);
            try {
              const H = new Uint32Array(EV.mem.buffer);
              EV.n = H[pc >> 2];
              EV.size = H[pb >> 2];
              H[pc >> 2] = EV.n + 1000;
              H[pb >> 2] = EV.size + 131072;
            } catch (x) {
              /* (as it was) */
            }
            return r;
          };
          ns[kg] = (arr, buf) => {
            const r = g(arr, buf);
            try {
              new Uint32Array(EV.mem.buffer)[(arr >> 2) + EV.n] = 0;
              EV.arr = arr;
              EV.buf = buf;
            } catch (x) {
              /* (as it was) */
            }
            return r;
          };
        }
      } catch (x) {
        /* (without the environment) */
      }
      WebAssembly.instantiate(wasmModule, info).then((inst) => {
        try {
          EV.mem = memOf(inst.exports) || EV.mem;
        } catch (x) {
          /* (none) */
        }
        done(inst, wasmModule);
      });
      return {};
    },
    getPreloadedPackage: () => (data ? data.buffer.slice(data.byteOffset, data.byteOffset + data.byteLength) : null),
    // (what the program writes goes to its files; these are only for a terminal, which there is not)
    print: () => {},
    printErr: () => {}
  });
  const FS = mod.FS;

  // the folders on disk, at the paths the page's programs know them by (the outer ones first)
  for (const m of mounts) {
    FS.mkdirTree(m.at);
    FS.mount(makeDiskFS(FS, { readOnly: !!m.readOnly, hide: m.hide || [] }), { root: m.dir }, m.at);
  }
  for (const [target, link] of io.links || []) {
    try {
      FS.lookupPath(link);
    } catch (e) {
      try {
        FS.mkdirTree(link.slice(0, link.lastIndexOf('/')) || '/');
      } catch (e2) {
        /* (there) */
      }
      try {
        FS.symlink(target, link);
      } catch (e2) {
        /* (there) */
      }
    }
  }
  try {
    FS.lookupPath('/dev/zero');
  } catch (e) {
    try {
      const dv = FS.makedev(1, 5);
      FS.registerDevice(dv, {
        read(q, b, o, l) {
          b.fill(0, o, o + l);
          return l;
        },
        write(q, b, o, l) {
          return l;
        }
      });
      FS.mkdev('/dev/zero', dv);
    } catch (e2) {
      /* (without) */
    }
  }
  FS.chdir(cwd);
  mod.__exitStatus = null;

  // standard input, output and error: real files on descriptors 0, 1 and 2
  const paths = [io.stdin || '/dev/null', io.stdout || '/dev/stdout', io.stderr || '/dev/stderr'];
  let in0 = null, inMax = 0;
  const outOrder = [];
  for (let fd = 0; fd < 3; fd++) {
    try {
      if (FS.streams[fd]) FS.close(FS.streams[fd]);
    } catch (e) {
      /* (closed) */
    }
    const st = FS.open(paths[fd], fd === 0 ? 'r' : io.merge ? 'a' : 'w');
    if (st.fd !== fd) throw new Error('Cannot bind standard file descriptor ' + fd);
    // wc: its input is a pipe (the width of its columns)
    if (fd === 0 && io.stdin && io.fifo && st.node && st.node.node_ops && st.node.node_ops.getattr) {
      const o = st.node.node_ops, ga = o.getattr;
      st.node.node_ops = Object.assign({}, o, {
        getattr(n) {
          const a = ga.call(o, n);
          a.mode = (a.mode & ~61440) | 4096;
          return a;
        }
      });
    }
    // how far the program reads its input – and, for sed in a block, a line at a time
    if (fd === 0 && io.stdin) {
      in0 = st;
      const ops = st.stream_ops, rd = ops && ops.read;
      if (rd)
        st.stream_ops = Object.assign({}, ops, {
          read(q, b, o, l, p) {
            let c = rd.call(ops, q, b, o, io.lines && l > 256 ? 256 : l, p);
            if (io.lines && c > 1) {
              const i = b.subarray(o, o + c).indexOf(10);
              if (i >= 0 && i < c - 1) c = i + 1;
            }
            if (c > 0 && p + c > inMax) inMax = p + c;
            return c;
          }
        });
    }
    // the order in which the program writes to its output and to its errors
    if (fd > 0 && !io.merge) {
      const ops = st.stream_ops, wr = ops && ops.write;
      if (wr)
        st.stream_ops = Object.assign({}, ops, {
          write(q, b, o, l, p, c) {
            const k = wr.call(ops, q, b, o, l, p, c);
            if (k > 0) {
              const z = outOrder.length;
              if (z && outOrder[z - 2] === fd) outOrder[z - 1] += k;
              else outOrder.push(fd, k);
            }
            return k;
          }
        });
    }
  }

  // the clock of another time zone: the JavaScript Date that the program's runtime uses gives that zone's time
  const clock = globalThis.Date;
  if (io.zone || io.zoneName) globalThis.Date = zonedDate(clock, io.zone || null);
  // the environment that the shell exports
  if (io.env && EV.arr && EV.mem) {
    try {
      const U8 = new Uint8Array(EV.mem.buffer), U32 = new Uint32Array(EV.mem.buffer), enc = new TextEncoder();
      let p = EV.buf, k = 0;
      const end = EV.buf + EV.size + 131072, max = EV.n + 1000;
      for (const v of io.env) {
        const b = enc.encode(v);
        if (k >= max - 1 || p + b.length + 1 > end) break;
        U8.set(b, p);
        U8[p + b.length] = 0;
        U32[(EV.arr >> 2) + k++] = p;
        p += b.length + 1;
      }
      U32[(EV.arr >> 2) + k] = 0;
    } catch (e) {
      /* (the program's own environment) */
    }
  }
  let failure = null;
  try {
    mod.callMain(args);
  } catch (e) {
    failure = e;
    if (typeof e.status === 'number') mod.__exitStatus = e.status;
  } finally {
    globalThis.Date = clock;
  }
  try {
    if (mod._fflush) mod._fflush(0);
  } catch (e) {
    /* (nothing to write) */
  }
  for (let fd = 0; fd < 3; fd++) {
    try {
      if (FS.streams[fd]) FS.close(FS.streams[fd]);
    } catch (e) {
      /* (closed) */
    }
  }
  const status = Number.isInteger(mod.__exitStatus) ? mod.__exitStatus : failure ? 1 : null;
  return {
    code: status,
    error: failure && typeof failure.status !== 'number' ? String((failure && failure.message) || failure) : null,
    stdinPos: in0 && in0.position > 0 ? in0.position : 0,
    stdinMax: inMax,
    order: outOrder,
    memory: mod.HEAPU8 ? mod.HEAPU8.length : null
  };
}

/* the Date of a time zone (execIO's, unchanged): for UTC the UTC parts; for a named zone the parts that Intl gives
   for it; and toTimeString with the short name of the zone (BST, CEST, EDT …) */
function zonedDate(R, Z) {
  let F = null;
  if (Z && Z !== 'UTC')
    try {
      F = new Intl.DateTimeFormat('en-US', { timeZone: Z, hourCycle: 'h23', year: 'numeric', month: 'numeric', day: 'numeric', hour: 'numeric', minute: 'numeric', second: 'numeric', weekday: 'short' });
    } catch (e) {
      F = null;
    }
  const WD = { Sun: 0, Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6 };
  const parts = (t) => {
    const o = {};
    for (const p of F.formatToParts(new R(t))) o[p.type] = p.value;
    const f = { y: +o.year, mo: +o.month - 1, d: +o.day, h: +o.hour % 24, mi: +o.minute, s: +o.second, wd: WD[o.weekday] };
    f.off = Math.round((R.UTC(f.y, f.mo, f.d, f.h, f.mi, f.s) - Math.floor(t / 1e3) * 1e3) / 6e4);
    return f;
  };
  const zone = (d) => {
    if (Z === 'UTC' || Z === 'GMT') return Z;
    try {
      const off = F ? parts(d.getTime()).off : -R.prototype.getTimezoneOffset.call(d);
      for (const l of ['en-GB', 'en-US', 'en-AU', 'en-NZ', 'en-IN', 'en-CA', 'en-ZA', 'ja-JP', 'ko-KR']) {
        const p = new Intl.DateTimeFormat(l, Object.assign({ timeZoneName: 'short' }, F ? { timeZone: Z } : {})).formatToParts(d).find((q) => q.type === 'timeZoneName');
        if (p && /^[A-Za-z]{2,6}$/.test(p.value) && (!/^(GMT|UTC)$/.test(p.value) || off === 0)) return p.value;
      }
    } catch (e) {
      /* (no name) */
    }
    return null;
  };
  class D extends R {
    constructor(...a) {
      if (a.length > 1 && Z === 'UTC') super(R.UTC(...a));
      else if (a.length > 1 && F) {
        const g = R.UTC(...a);
        let t = g - parts(g).off * 6e4;
        t = g - parts(t).off * 6e4;
        super(t);
      } else super(...a);
    }
    toTimeString() {
      const s = R.prototype.toTimeString.call(this);
      if (isNaN(this.getTime())) return s;
      const z = zone(this);
      return z ? s.replace(/\(.*\)$/, '(' + z + ')') : s;
    }
  }
  if (Z === 'UTC') {
    for (const k of ['FullYear', 'Month', 'Date', 'Day', 'Hours', 'Minutes', 'Seconds', 'Milliseconds'])
      D.prototype['get' + k] = function () {
        return R.prototype['getUTC' + k].call(this);
      };
    D.prototype.getTimezoneOffset = function () {
      return 0;
    };
  } else if (F) {
    const G = { FullYear: 'y', Month: 'mo', Date: 'd', Day: 'wd', Hours: 'h', Minutes: 'mi', Seconds: 's' };
    for (const k in G)
      D.prototype['get' + k] = function () {
        const t = this.getTime();
        return isNaN(t) ? NaN : parts(t)[G[k]];
      };
    D.prototype.getTimezoneOffset = function () {
      const t = this.getTime();
      return isNaN(t) ? NaN : -parts(t).off;
    };
  }
  return D;
}

main().then(
  (r) => parentPort.postMessage({ ok: true, result: r }),
  (e) => parentPort.postMessage({ ok: false, error: String((e && e.stack) || e) })
);
