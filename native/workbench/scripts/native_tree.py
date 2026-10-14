"""Read actual Win32 TreeView controls in native GUI gates.

TreeView messages with pointer arguments are not marshalled across processes.
Allocate only the small documented TVITEM/RECT buffers in the app process;
never inject notifications, application state, code, or private RPC handlers.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes


class NativeTree:
    def __init__(self, user, send, pid, hwnd):
        self.user, self.send, self.pid, self.hwnd = user, send, pid, hwnd

    def _buffer(self, payload, size, action):
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.VirtualAllocEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wintypes.DWORD, wintypes.DWORD]
        kernel.VirtualAllocEx.restype = ctypes.c_void_p
        kernel.VirtualFreeEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wintypes.DWORD]
        kernel.WriteProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
        kernel.ReadProcessMemory.argtypes = kernel.WriteProcessMemory.argtypes
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        process = kernel.OpenProcess(0x0038, False, self.pid)  # VM_OPERATION/READ/WRITE.
        if not process:
            raise ctypes.WinError(ctypes.get_last_error())
        address = None
        try:
            address = kernel.VirtualAllocEx(process, None, size, 0x3000, 0x04)
            if not address:
                raise ctypes.WinError(ctypes.get_last_error())
            raw = payload(address) if callable(payload) else payload
            count = ctypes.c_size_t()
            source = ctypes.create_string_buffer(raw)
            if not kernel.WriteProcessMemory(process, address, source, len(raw), ctypes.byref(count)) or count.value != len(raw):
                raise ctypes.WinError(ctypes.get_last_error())
            if not action(address):
                raise AssertionError("Native TreeView buffer query failed.")
            result = ctypes.create_string_buffer(size)
            if not kernel.ReadProcessMemory(process, address, result, size, ctypes.byref(count)) or count.value != size:
                raise ctypes.WinError(ctypes.get_last_error())
            return result.raw
        finally:
            if address:
                kernel.VirtualFreeEx(process, address, 0, 0x8000)
            kernel.CloseHandle(process)

    def next(self, item=0, relation=0):
        return self.send(self.hwnd, 0x110A, relation, item)  # TVM_GETNEXTITEM.

    def siblings(self, first):
        result = []
        while first:
            if first in result or len(result) >= 4096:
                raise AssertionError("Unexpected native TreeView sibling cycle/size.")
            result.append(first)
            first = self.next(first, 1)
        return result

    def roots(self):
        return self.siblings(self.next())

    def children(self, root):
        return self.siblings(self.next(root, 4))

    def tools(self):
        return [child for root in self.roots() for child in self.children(root)]

    def selected(self):
        return self.next(0, 9)

    def expanded(self, item):
        return bool(self.send(self.hwnd, 0x1127, item, 0x20) & 0x20)  # TVM_GETITEMSTATE/TVIS_EXPANDED.

    def inspect(self, item):
        class Item(ctypes.Structure):
            _fields_ = [("mask", wintypes.UINT), ("hItem", ctypes.c_void_p),
                        ("state", wintypes.UINT), ("stateMask", wintypes.UINT),
                        ("pszText", ctypes.c_void_p), ("cchTextMax", ctypes.c_int),
                        ("iImage", ctypes.c_int), ("iSelectedImage", ctypes.c_int),
                        ("cChildren", ctypes.c_int), ("lParam", wintypes.LPARAM)]
        offset, text_bytes = ctypes.sizeof(Item), 16384
        def payload(address):
            value = Item(mask=1 | 8, hItem=item, stateMask=0xffff,
                         pszText=address + offset, cchTextMax=text_bytes // 2)
            return bytes(value) + bytes(text_bytes)
        raw = self._buffer(payload, offset + text_bytes,
                           lambda address: self.send(self.hwnd, 0x113E, 0, address))
        state = Item.from_buffer_copy(raw).state
        return {"handle": item, "label": raw[offset:].decode("utf-16-le").split("\0", 1)[0],
                "itemState": state,
                "messageStateAll": self.send(self.hwnd, 0x1127, item, 0xffff),
                "messageStateExpanded": self.send(self.hwnd, 0x1127, item, 0x20)}

    def label(self, item):
        return self.inspect(item)["label"]

    def rect(self, item):
        # TVM_GETITEMRECT overlays HTREEITEM on the beginning of RECT.
        size = ctypes.sizeof(wintypes.RECT)
        raw = int(item).to_bytes(ctypes.sizeof(ctypes.c_void_p), "little").ljust(size, b"\0")
        raw = self._buffer(raw, size, lambda address: self.send(self.hwnd, 0x1104, 1, address))
        result = wintypes.RECT.from_buffer_copy(raw)
        origin = wintypes.POINT()
        if not self.user.ClientToScreen(self.hwnd, ctypes.byref(origin)):
            raise ctypes.WinError(ctypes.get_last_error())
        return [result.left + origin.x, result.top + origin.y,
                result.right + origin.x, result.bottom + origin.y]

    def item_height(self, item):
        """Read the native integral row height, including rows outside the clip."""
        class ItemEx(ctypes.Structure):
            _fields_ = [("mask", wintypes.UINT), ("hItem", ctypes.c_void_p),
                        ("state", wintypes.UINT), ("stateMask", wintypes.UINT),
                        ("pszText", ctypes.c_void_p), ("cchTextMax", ctypes.c_int),
                        ("iImage", ctypes.c_int), ("iSelectedImage", ctypes.c_int),
                        ("cChildren", ctypes.c_int), ("lParam", wintypes.LPARAM),
                        ("iIntegral", ctypes.c_int), ("uStateEx", wintypes.UINT),
                        ("hwnd", wintypes.HWND), ("iExpandedImage", ctypes.c_int),
                        ("iReserved", ctypes.c_int)]
        value = ItemEx(mask=0x80, hItem=item)  # TVIF_INTEGRAL.
        raw = self._buffer(bytes(value), ctypes.sizeof(value),
                           lambda address: self.send(self.hwnd, 0x113E, 0, address))
        integral = ItemEx.from_buffer_copy(raw).iIntegral
        base = self.send(self.hwnd, 0x111C)  # TVM_GETITEMHEIGHT.
        if integral < 1 or base < 1:
            raise AssertionError("Invalid native integral row height.")
        return integral * base

    def viewport(self):
        """The optional native pixel viewport owns clipping and its scrollbar."""
        self.user.GetParent.argtypes = [wintypes.HWND]
        self.user.GetParent.restype = wintypes.HWND
        parent = self.user.GetParent(self.hwnd)
        return parent if parent and self.user.GetDlgCtrlID(parent) == 430 else self.hwnd

    def client_bounds(self, hwnd=None):
        hwnd = hwnd or self.hwnd
        client, origin = wintypes.RECT(), wintypes.POINT()
        if not (self.user.GetClientRect(hwnd, ctypes.byref(client)) and
                self.user.ClientToScreen(hwnd, ctypes.byref(origin))):
            raise ctypes.WinError(ctypes.get_last_error())
        return [origin.x, origin.y, origin.x + client.right, origin.y + client.bottom]

    def visible_bounds(self):
        """Read real child/parent client intersection without changing scroll."""
        child, viewport = self.client_bounds(), self.client_bounds(self.viewport())
        result = [max(child[0], viewport[0]), max(child[1], viewport[1]),
                  min(child[2], viewport[2]), min(child[3], viewport[3])]
        if result[0] >= result[2] or result[1] >= result[3]:
            raise AssertionError("Native TreeView has no visible client intersection: "
                                 "child=%s viewport=%s" % (child, viewport))
        return result

    def first_visible(self):
        """Find the first actual row intersecting the clipping viewport.

        TVGN_FIRSTVISIBLE refers to the potentially oversized child window;
        native item rectangles determine what a user can actually see. These
        are passive documented queries, never EnsureVisible or paint repair.
        """
        bounds = self.visible_bounds()
        item, visited = self.next(0, 5), set()
        while item:
            if item in visited or len(visited) >= 4096:
                raise AssertionError("Unexpected native visible-row chain.")
            visited.add(item)
            row = self.rect(item)
            if row[1] < bounds[3] and row[3] > bounds[1]:
                return item
            if row[1] >= bounds[3]:
                return 0
            item = self.next(item, 6)  # TVGN_NEXTVISIBLE.
        return 0

    def point(self, item):
        self.send(self.hwnd, 0x1114, 0, item)  # TVM_ENSUREVISIBLE.
        left, top, right, bottom = self.rect(item)
        # Wrapped rows may be taller than the viewport. Choose an actual
        # visible portion after the same documented EnsureVisible request;
        # the mathematical row midpoint can be underneath another panel.
        client = self.visible_bounds()
        left, top = max(left, client[0]), max(top, client[1])
        right, bottom = min(right, client[2]), min(bottom, client[3])
        if right - left < 4 or bottom - top < 4:
            raise AssertionError("Native TreeView row has no usable visible click area.")
        return left + min(40, max(2, (right-left)//2)), (top+bottom)//2

    def first_tool_point(self):
        tools = self.tools()
        if len(tools) != 1:
            raise AssertionError("Expected exactly one filtered tool, got " + str(len(tools)))
        return self.point(tools[0])
