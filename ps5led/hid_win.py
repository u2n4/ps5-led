"""Windows HID transport over ctypes — setupapi for discovery, hid.dll for caps,
CreateFile/ReadFile/WriteFile for I/O.

Windows only. Import this from inside a function body, never at the module scope
of anything the Linux CI runner imports.

Every prototype below declares argtypes and restype. On 64-bit Windows an
undeclared handle return defaults to c_int and silently truncates.
"""

import ctypes
import ctypes.wintypes as wintypes
import threading
from typing import List, NamedTuple, Optional

# use_last_error=True on every library: ctypes only copies GetLastError() into
# its private per-thread slot for functions carrying that flag. Read
# ctypes.get_last_error() after a call into a library loaded without it and the
# number is whatever some earlier call left behind.
_hid = ctypes.WinDLL("hid", use_last_error=True)
_setupapi = ctypes.WinDLL("setupapi", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

HANDLE = ctypes.c_void_p
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
OPEN_EXISTING = 3
FILE_FLAG_OVERLAPPED = 0x40000000

DIGCF_PRESENT = 0x02
DIGCF_DEVICEINTERFACE = 0x10

ERROR_IO_INCOMPLETE = 996
ERROR_IO_PENDING = 997
ERROR_DEVICE_NOT_CONNECTED = 1167
WAIT_TIMEOUT = 0x102
WAIT_OBJECT_0 = 0
INFINITE = 0xFFFFFFFF

HIDP_STATUS_SUCCESS = 0x00110000

TRANSPORT_USB = "usb"
TRANSPORT_BT = "bt"
_TRANSPORT_BY_INPUT_LENGTH = {64: TRANSPORT_USB, 78: TRANSPORT_BT}


class HidError(OSError):
    """A HID operation failed; the message carries the Win32 error."""


class GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort),
                ("Data3", ctypes.c_ushort), ("Data4", ctypes.c_ubyte * 8)]


class SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("InterfaceClassGuid", GUID),
                ("Flags", wintypes.DWORD), ("Reserved", ctypes.c_size_t)]


class HIDD_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Size", wintypes.ULONG), ("VendorID", wintypes.USHORT),
                ("ProductID", wintypes.USHORT), ("VersionNumber", wintypes.USHORT)]


class HIDP_CAPS(ctypes.Structure):
    _fields_ = [("Usage", wintypes.USHORT), ("UsagePage", wintypes.USHORT),
                ("InputReportByteLength", wintypes.USHORT),
                ("OutputReportByteLength", wintypes.USHORT),
                ("FeatureReportByteLength", wintypes.USHORT),
                ("Reserved", wintypes.USHORT * 17), ("Counts", wintypes.USHORT * 13)]


class OVERLAPPED(ctypes.Structure):
    _fields_ = [("Internal", ctypes.c_void_p), ("InternalHigh", ctypes.c_void_p),
                ("Offset", wintypes.DWORD), ("OffsetHigh", wintypes.DWORD),
                ("hEvent", HANDLE)]


_hid.HidD_GetHidGuid.argtypes = [ctypes.POINTER(GUID)]
_hid.HidD_GetHidGuid.restype = None
_hid.HidD_GetAttributes.argtypes = [HANDLE, ctypes.POINTER(HIDD_ATTRIBUTES)]
_hid.HidD_GetAttributes.restype = wintypes.BOOLEAN
_hid.HidD_GetPreparsedData.argtypes = [HANDLE, ctypes.POINTER(ctypes.c_void_p)]
_hid.HidD_GetPreparsedData.restype = wintypes.BOOLEAN
_hid.HidD_FreePreparsedData.argtypes = [ctypes.c_void_p]
_hid.HidD_FreePreparsedData.restype = wintypes.BOOLEAN
_hid.HidP_GetCaps.argtypes = [ctypes.c_void_p, ctypes.POINTER(HIDP_CAPS)]
_hid.HidP_GetCaps.restype = ctypes.c_long
_hid.HidD_GetProductString.argtypes = [HANDLE, ctypes.c_void_p, wintypes.ULONG]
_hid.HidD_GetProductString.restype = wintypes.BOOLEAN
_hid.HidD_GetFeature.argtypes = [HANDLE, ctypes.c_void_p, wintypes.ULONG]
_hid.HidD_GetFeature.restype = wintypes.BOOLEAN

_setupapi.SetupDiGetClassDevsW.argtypes = [ctypes.POINTER(GUID), wintypes.LPCWSTR,
                                           wintypes.HWND, wintypes.DWORD]
_setupapi.SetupDiGetClassDevsW.restype = HANDLE
_setupapi.SetupDiEnumDeviceInterfaces.argtypes = [
    HANDLE, ctypes.c_void_p, ctypes.POINTER(GUID), wintypes.DWORD,
    ctypes.POINTER(SP_DEVICE_INTERFACE_DATA)]
_setupapi.SetupDiEnumDeviceInterfaces.restype = wintypes.BOOL
_setupapi.SetupDiGetDeviceInterfaceDetailW.argtypes = [
    HANDLE, ctypes.POINTER(SP_DEVICE_INTERFACE_DATA), ctypes.c_void_p,
    wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
_setupapi.SetupDiGetDeviceInterfaceDetailW.restype = wintypes.BOOL
_setupapi.SetupDiDestroyDeviceInfoList.argtypes = [HANDLE]
_setupapi.SetupDiDestroyDeviceInfoList.restype = wintypes.BOOL

_kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, HANDLE]
_kernel32.CreateFileW.restype = HANDLE
_kernel32.CloseHandle.argtypes = [HANDLE]
_kernel32.CloseHandle.restype = wintypes.BOOL
_kernel32.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL,
                                   wintypes.LPCWSTR]
_kernel32.CreateEventW.restype = HANDLE
_kernel32.ReadFile.argtypes = [HANDLE, ctypes.c_void_p, wintypes.DWORD,
                               ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(OVERLAPPED)]
_kernel32.ReadFile.restype = wintypes.BOOL
_kernel32.WriteFile.argtypes = [HANDLE, ctypes.c_void_p, wintypes.DWORD,
                                ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(OVERLAPPED)]
_kernel32.WriteFile.restype = wintypes.BOOL
_kernel32.GetOverlappedResult.argtypes = [HANDLE, ctypes.POINTER(OVERLAPPED),
                                          ctypes.POINTER(wintypes.DWORD), wintypes.BOOL]
_kernel32.GetOverlappedResult.restype = wintypes.BOOL
_kernel32.WaitForSingleObject.argtypes = [HANDLE, wintypes.DWORD]
_kernel32.WaitForSingleObject.restype = wintypes.DWORD
_kernel32.CancelIoEx.argtypes = [HANDLE, ctypes.POINTER(OVERLAPPED)]
_kernel32.CancelIoEx.restype = wintypes.BOOL


class DeviceInfo(NamedTuple):
    path: str
    vendor_id: int
    product_id: int
    product: str
    input_length: int
    output_length: int
    feature_length: int
    transport: str


def _interface_paths():
    guid = GUID()
    _hid.HidD_GetHidGuid(ctypes.byref(guid))
    devs = _setupapi.SetupDiGetClassDevsW(
        ctypes.byref(guid), None, None, DIGCF_PRESENT | DIGCF_DEVICEINTERFACE)
    if not devs or devs == INVALID_HANDLE_VALUE:
        raise HidError("SetupDiGetClassDevsW failed: %d" % ctypes.get_last_error())
    paths = []
    index = 0
    try:
        while True:
            data = SP_DEVICE_INTERFACE_DATA()
            data.cbSize = ctypes.sizeof(data)
            if not _setupapi.SetupDiEnumDeviceInterfaces(
                    devs, None, ctypes.byref(guid), index, ctypes.byref(data)):
                break
            index += 1
            needed = wintypes.DWORD(0)
            _setupapi.SetupDiGetDeviceInterfaceDetailW(
                devs, ctypes.byref(data), None, 0, ctypes.byref(needed), None)
            if not needed.value:
                continue
            buf = ctypes.create_string_buffer(needed.value)
            # cbSize is the size of the fixed part of the struct, not of the
            # buffer: 8 on 64-bit (4-byte size + WCHAR alignment), 6 on 32-bit.
            fixed = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6
            ctypes.memmove(buf, ctypes.byref(wintypes.DWORD(fixed)), 4)
            if _setupapi.SetupDiGetDeviceInterfaceDetailW(
                    devs, ctypes.byref(data), buf, needed, None, None):
                paths.append(ctypes.wstring_at(ctypes.addressof(buf) + 4))
    finally:
        _setupapi.SetupDiDestroyDeviceInfoList(devs)
    return paths


def _describe(handle, path):
    attrs = HIDD_ATTRIBUTES()
    attrs.Size = ctypes.sizeof(attrs)
    if not _hid.HidD_GetAttributes(handle, ctypes.byref(attrs)):
        return None
    preparsed = ctypes.c_void_p()
    if not _hid.HidD_GetPreparsedData(handle, ctypes.byref(preparsed)):
        return None
    caps = HIDP_CAPS()
    try:
        status = _hid.HidP_GetCaps(preparsed, ctypes.byref(caps))
    finally:
        _hid.HidD_FreePreparsedData(preparsed)
    if status != HIDP_STATUS_SUCCESS:
        # caps is still zero-filled. Reporting input_length=0 would hand
        # HidDevice.open a device whose every read asks for zero bytes and can
        # never return data, with no error anywhere in the chain.
        return None
    name = ctypes.create_unicode_buffer(128)
    _hid.HidD_GetProductString(handle, name, ctypes.sizeof(name))
    return DeviceInfo(
        path=path,
        vendor_id=attrs.VendorID,
        product_id=attrs.ProductID,
        product=name.value,
        input_length=caps.InputReportByteLength,
        output_length=caps.OutputReportByteLength,
        feature_length=caps.FeatureReportByteLength,
        transport=_TRANSPORT_BY_INPUT_LENGTH.get(caps.InputReportByteLength, "unknown"),
    )


def enumerate_devices(vendor_id=None):
    # type: (Optional[int]) -> List[DeviceInfo]
    """Every present HID interface, optionally filtered by vendor."""
    found = []
    for path in _interface_paths():
        # dwDesiredAccess = 0: HidD_GetAttributes, HidP_GetCaps and
        # HidD_GetProductString all work on a handle with no access rights.
        # Asking for GENERIC_READ | GENERIC_WRITE here would make every
        # interface another process holds unshared -- Steam's controller driver
        # and DS4Windows both do that to a DualSense -- disappear from the list
        # with no diagnostic. HidDevice.open still asks for the real rights.
        handle = _kernel32.CreateFileW(
            path, 0, FILE_SHARE_READ | FILE_SHARE_WRITE,
            None, OPEN_EXISTING, 0, None)
        if not handle or handle == INVALID_HANDLE_VALUE:
            continue
        try:
            info = _describe(handle, path)
        finally:
            _kernel32.CloseHandle(handle)
        if info and (vendor_id is None or info.vendor_id == vendor_id):
            found.append(info)
    return found


def _cancel_and_drain(handle, overlapped, transferred):
    """Cancel one pending request and block until the kernel is finished with it.

    CancelIoEx only *asks* for cancellation and returns before the request has
    completed. Until it completes the kernel still holds pointers to the
    OVERLAPPED and the data buffer and will write the completion status into
    them. Returning without this blocking GetOverlappedResult would let Python
    free memory the kernel is about to write to.
    """
    _kernel32.CancelIoEx(handle, ctypes.byref(overlapped))
    _kernel32.GetOverlappedResult(handle, ctypes.byref(overlapped),
                                  ctypes.byref(transferred), True)


class HidDevice(object):
    """One open HID interface with overlapped read and write.

    Threading contract: at most one thread inside read() and at most one thread
    inside write() at a time. The OVERLAPPED is per call but the two events are
    per instance, so a second concurrent read() would wait on the same
    manual-reset event as the first, wake on the wrong completion, and then
    drain the other read's request.

    close() may be called from any thread at any time, including while a reader
    is blocked in read(): it cancels the outstanding requests, waits for every
    operation to leave the object, and only then closes the device handle and
    the events -- in that order, because until an operation has returned, the
    handle value is still live in its frame and an event may still be under a
    WaitForSingleObject. The wait is bounded by the timeout of the read in
    flight, since an operation that has not yet issued its request has nothing
    for CancelIoEx to cancel.
    """

    def __init__(self, handle, info):
        self._handle = handle
        self.info = info
        self.last_error = None  # type: Optional[str]
        # _sync guards _handle, _ops and _closing, and is the condition close()
        # waits on for in-flight operations to drain.
        self._sync = threading.Condition()
        self._ops = 0
        self._closing = False
        self._read_event = _kernel32.CreateEventW(None, True, False, None)
        if not self._read_event:
            raise HidError("CreateEventW failed: Win32 error %d" % ctypes.get_last_error())
        self._write_event = _kernel32.CreateEventW(None, True, False, None)
        if not self._write_event:
            err = ctypes.get_last_error()
            _kernel32.CloseHandle(self._read_event)
            self._read_event = None
            raise HidError("CreateEventW failed: Win32 error %d" % err)

    @classmethod
    def open(cls, path):
        handle = _kernel32.CreateFileW(
            path, GENERIC_READ | GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE,
            None, OPEN_EXISTING, FILE_FLAG_OVERLAPPED, None)
        if not handle or handle == INVALID_HANDLE_VALUE:
            raise HidError("cannot open %s: Win32 error %d" % (path, ctypes.get_last_error()))
        try:
            info = _describe(handle, path)
            if info is None:
                raise HidError("cannot read capabilities for %s" % path)
            return cls(handle, info)
        except BaseException:
            _kernel32.CloseHandle(handle)
            raise

    def _begin(self):
        """Reserve the device for one operation: (handle, read event, write event).

        Every caller must release with _end() in a finally. While an operation
        is outstanding, close() will not close the device handle or the events,
        so the three values returned here stay valid for the whole call. Reading
        self._handle again later would be a use-after-close.
        """
        with self._sync:
            if self._handle is None or self._closing:
                raise HidError("device is closed")
            self._ops += 1
            return self._handle, self._read_event, self._write_event

    def _end(self):
        with self._sync:
            self._ops -= 1
            if not self._ops:
                self._sync.notify_all()

    def read(self, timeout_ms=1000):
        """One input report, or None on timeout. Raises HidError if the device left."""
        # INFINITE would produce exactly the uncancellable blocking read this
        # transport exists to avoid; a negative value converts to it silently.
        if timeout_ms < 0 or timeout_ms >= INFINITE:
            raise HidError("timeout_ms must be 0..%d, not %r" % (INFINITE - 1, timeout_ms))
        handle, event, _ = self._begin()
        try:
            length = self.info.input_length
            buf = ctypes.create_string_buffer(length)
            transferred = wintypes.DWORD(0)
            overlapped = OVERLAPPED()
            overlapped.hEvent = event
            ok = _kernel32.ReadFile(handle, buf, length,
                                    ctypes.byref(transferred), ctypes.byref(overlapped))
            if not ok:
                err = ctypes.get_last_error()
                if err != ERROR_IO_PENDING:
                    raise HidError("ReadFile failed: Win32 error %d" % err)
                wait = _kernel32.WaitForSingleObject(event, timeout_ms)
                if wait == WAIT_TIMEOUT:
                    _cancel_and_drain(handle, overlapped, transferred)
                    return None
                if wait != WAIT_OBJECT_0:
                    # The request is still pending; it has to be drained before
                    # this frame goes away with overlapped and buf in it.
                    _cancel_and_drain(handle, overlapped, transferred)
                    raise HidError("WaitForSingleObject returned %d" % wait)
                if not _kernel32.GetOverlappedResult(handle, ctypes.byref(overlapped),
                                                     ctypes.byref(transferred), False):
                    err = ctypes.get_last_error()
                    if err == ERROR_IO_INCOMPLETE:
                        _cancel_and_drain(handle, overlapped, transferred)
                    raise HidError("GetOverlappedResult failed: Win32 error %d" % err)
            return buf.raw[:transferred.value]
        finally:
            self._end()

    def write(self, data):
        """Send an output report, padded to OutputReportByteLength.

        WriteFile, never HidD_SetOutputReport: Microsoft documents that some
        devices stop responding when driven through HidD_SetXxx.
        """
        handle, _, event = self._begin()
        try:
            length = self.info.output_length
            if len(data) > length:
                raise HidError("report is %d bytes, device accepts %d" % (len(data), length))
            buf = ctypes.create_string_buffer(bytes(data).ljust(length, b"\x00"), length)
            transferred = wintypes.DWORD(0)
            overlapped = OVERLAPPED()
            overlapped.hEvent = event
            ok = _kernel32.WriteFile(handle, buf, length,
                                     ctypes.byref(transferred), ctypes.byref(overlapped))
            if not ok:
                err = ctypes.get_last_error()
                if err != ERROR_IO_PENDING:
                    self.last_error = "WriteFile failed: Win32 error %d" % err
                    raise HidError(self.last_error)
                if _kernel32.WaitForSingleObject(event, 1000) != WAIT_OBJECT_0:
                    # A sleeping Bluetooth controller lands here. The request is
                    # still in flight, so drain it before overlapped and buf go.
                    _cancel_and_drain(handle, overlapped, transferred)
                    self.last_error = "write timed out"
                    raise HidError(self.last_error)
                if not _kernel32.GetOverlappedResult(handle, ctypes.byref(overlapped),
                                                     ctypes.byref(transferred), False):
                    err = ctypes.get_last_error()
                    if err == ERROR_IO_INCOMPLETE:
                        _cancel_and_drain(handle, overlapped, transferred)
                    self.last_error = "write failed: Win32 error %d" % err
                    raise HidError(self.last_error)
            self.last_error = None
            return transferred.value
        finally:
            self._end()

    def get_feature(self, report_id, length):
        """Read a feature report, or None if the device refused."""
        handle, _, _ = self._begin()
        try:
            buf = ctypes.create_string_buffer(length)
            buf[0] = bytes([report_id])
            if not _hid.HidD_GetFeature(handle, buf, length):
                self.last_error = ("HidD_GetFeature(%#x) failed: Win32 error %d"
                                   % (report_id, ctypes.get_last_error()))
                return None
            return buf.raw[:length]
        finally:
            self._end()

    def close(self):
        """Cancel outstanding I/O, wait for it to drain, then release the handles.

        Safe to call while another thread is inside read() or write(), and safe
        to call twice. The order is forced by two Win32 rules: closing an event
        another thread is waiting on leaves that wait undefined, and a closed
        handle value can be reissued to any other CreateFile in the process --
        so an operation still holding this handle would end up talking to an
        unrelated object.
        """
        with self._sync:
            while self._closing:
                self._sync.wait()
            if self._handle is None:
                return
            self._closing = True  # no operation may start from here on
            handle = self._handle
        try:
            # Only a request, not a completion: each cancelled operation signals
            # its own event, drains its own OVERLAPPED, and then leaves _ops.
            _kernel32.CancelIoEx(handle, None)
            with self._sync:
                while self._ops:
                    self._sync.wait()
                _kernel32.CloseHandle(handle)
                self._handle = None
                for event in (self._read_event, self._write_event):
                    if event:
                        _kernel32.CloseHandle(event)
                self._read_event = None
                self._write_event = None
        finally:
            with self._sync:
                self._closing = False
                self._sync.notify_all()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False
