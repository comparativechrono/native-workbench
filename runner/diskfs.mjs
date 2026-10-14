/* A file system for Emscripten programs that is a folder on disk: every read, write, seek and listing of the program
   is the same operation on the real file, through Node's fs module. Nothing is copied into the program's memory or
   held whole: a program reads a 10 GB file as it would on Linux, a block at a time.

   It is Emscripten's NODEFS, written for the file-system interface of the Biowasm builds (Emscripten 2), which were
   made for web pages and do not have NODEFS in them: the builds export FS, and this is mounted with FS.mount.
     makeDiskFS(FS, { readOnly, hide })  → a file-system type;  FS.mount(type, { root: '/abs/folder' }, '/where')
   readOnly: the program can read, list and stat, but not create, change, rename or remove anything ("Permission
   denied", as in a folder of root's on Linux). hide: names at the top of the folder that the program does not see.
   A symbolic link on disk is what it points to (a workspace may link to large data kept elsewhere); other special
   files (pipes, sockets, devices) are not there for the program. */
import fs from 'node:fs';
import path from 'node:path';

// Emscripten's error numbers (WASI's), by the names Node gives errors
const ERRNO = { EACCES: 2, EAGAIN: 6, EBADF: 8, EBUSY: 10, EEXIST: 20, EINVAL: 28, EIO: 29, EISDIR: 31, ELOOP: 32, EMFILE: 33, ENAMETOOLONG: 37, ENODEV: 43, ENOENT: 44, ENOSPC: 51, ENOSYS: 52, ENOTDIR: 54, ENOTEMPTY: 55, ENOTTY: 59, ENXIO: 60, EOVERFLOW: 61, EPERM: 63, EROFS: 69, ESPIPE: 70, EXDEV: 75, ENOTSUP: 138, EFBIG: 22, EMLINK: 34 };
const S_IFMT = 0o170000, S_IFDIR = 0o040000, S_IFREG = 0o100000, S_IFLNK = 0o120000;

export function makeDiskFS(FS, { readOnly = false, hide = [] } = {}) {
  const hidden = new Set(hide);
  const fail = (e) => {
    if (e instanceof FS.ErrnoError) throw e;
    throw new FS.ErrnoError(ERRNO[e && e.code] || 29);
  };
  const tryFS = (f) => {
    try {
      return f();
    } catch (e) {
      return fail(e);
    }
  };
  const denyWrite = () => {
    if (readOnly) throw new FS.ErrnoError(ERRNO.EACCES);
  };
  /** the path on disk of a node: its names up to the root of the mount, below the folder that was mounted */
  const realPath = (node) => {
    const parts = [];
    while (node.parent !== node) {
      parts.push(node.name);
      node = node.parent;
    }
    parts.push(node.mount.opts.root);
    return path.join(...parts.reverse());
  };
  const D = {
    mount(mount) {
      const st = tryFS(() => fs.statSync(mount.opts.root));
      if (!st.isDirectory()) throw new FS.ErrnoError(ERRNO.ENOTDIR);
      return D.createNode(null, '/', st.mode, 0);
    },
    createNode(parent, name, mode) {
      const t = mode & S_IFMT;
      if (t !== S_IFDIR && t !== S_IFREG && t !== S_IFLNK) throw new FS.ErrnoError(ERRNO.EINVAL);
      const node = FS.createNode(parent, name, mode);
      node.mode = mode;
      node.node_ops = D.node_ops;
      node.stream_ops = D.stream_ops;
      return node;
    },
    node_ops: {
      getattr(node) {
        const p = realPath(node);
        const s = tryFS(() => fs.statSync(p));
        node.mode = s.mode;
        return { dev: s.dev, ino: s.ino, mode: s.mode, nlink: s.nlink, uid: 0, gid: 0, rdev: s.rdev, size: s.size, atime: s.atime, mtime: s.mtime, ctime: s.ctime, blksize: s.blksize || 4096, blocks: s.blocks != null ? s.blocks : Math.ceil(s.size / 512) };
      },
      setattr(node, attr) {
        denyWrite();
        const p = realPath(node);
        tryFS(() => {
          if (attr.mode !== undefined) {
            fs.chmodSync(p, attr.mode & 0o7777);
            node.mode = attr.mode;
          }
          if (attr.timestamp !== undefined) {
            const t = new Date(attr.timestamp);
            fs.utimesSync(p, t, t);
          }
          if (attr.size !== undefined) fs.truncateSync(p, attr.size);
        });
      },
      lookup(parent, name) {
        if (parent.parent === parent && hidden.has(name)) throw new FS.ErrnoError(ERRNO.ENOENT);
        const p = path.join(realPath(parent), name);
        const s = tryFS(() => fs.statSync(p));
        return D.createNode(parent, name, s.mode);
      },
      mknod(parent, name, mode) {
        denyWrite();
        const node = D.createNode(parent, name, mode);
        const p = realPath(node);
        tryFS(() => {
          if ((mode & S_IFMT) === S_IFDIR) fs.mkdirSync(p, mode & 0o777);
          else fs.writeFileSync(p, '', { mode: mode & 0o777 });
        });
        return node;
      },
      rename(oldNode, newDir, newName) {
        denyWrite();
        const from = realPath(oldNode), to = path.join(realPath(newDir), newName);
        tryFS(() => fs.renameSync(from, to));
        oldNode.name = newName;
        oldNode.parent = newDir;
      },
      unlink(parent, name) {
        denyWrite();
        tryFS(() => fs.unlinkSync(path.join(realPath(parent), name)));
      },
      rmdir(parent, name) {
        denyWrite();
        tryFS(() => fs.rmdirSync(path.join(realPath(parent), name)));
      },
      readdir(node) {
        const names = tryFS(() => fs.readdirSync(realPath(node)));
        return ['.', '..', ...(node.parent === node && hidden.size ? names.filter((n) => !hidden.has(n)) : names)];
      },
      symlink(parent, newName, oldPath) {
        denyWrite();
        // (the target is kept as the program wrote it: the program's file system follows it, in its own names)
        tryFS(() => fs.symlinkSync(oldPath, path.join(realPath(parent), newName)));
      },
      readlink(node) {
        return tryFS(() => fs.readlinkSync(realPath(node)));
      }
    },
    stream_ops: {
      open(stream) {
        if ((stream.node.mode & S_IFMT) !== S_IFREG) return;
        const acc = stream.flags & 3;
        if (acc !== 0) denyWrite();
        // (O_CREAT, O_EXCL and O_TRUNC were done by the file system already: the file is there, and empty if it was to be)
        let flags = acc === 0 ? fs.constants.O_RDONLY : acc === 1 ? fs.constants.O_WRONLY : fs.constants.O_RDWR;
        if (stream.flags & 1024) flags |= fs.constants.O_APPEND;
        stream.nfd = tryFS(() => fs.openSync(realPath(stream.node), flags));
      },
      close(stream) {
        if (stream.nfd != null) {
          const fd = stream.nfd;
          stream.nfd = null;
          tryFS(() => fs.closeSync(fd));
        }
      },
      read(stream, buffer, offset, length, position) {
        if (length === 0) return 0;
        return tryFS(() => fs.readSync(stream.nfd, buffer, offset, length, position));
      },
      write(stream, buffer, offset, length, position) {
        if (length === 0) return 0;
        return tryFS(() => fs.writeSync(stream.nfd, buffer, offset, length, position));
      },
      llseek(stream, offset, whence) {
        let position = offset;
        if (whence === 1) position += stream.position;
        else if (whence === 2 && (stream.node.mode & S_IFMT) === S_IFREG) position += tryFS(() => fs.fstatSync(stream.nfd)).size;
        if (position < 0) throw new FS.ErrnoError(ERRNO.EINVAL);
        return position;
      }
    }
  };
  return D;
}

export { ERRNO };
