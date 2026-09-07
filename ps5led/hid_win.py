"""Windows HID transport over ctypes — setupapi for discovery, hid.dll for caps,
CreateFile/ReadFile/WriteFile for I/O.

Windows only. Import this from inside a function body, never at the module scope
of anything the Linux CI runner imports.

Every prototype below declares argtypes and restype. On 64-bit Windows an
undeclared handle return defaults to c_int and silently truncates.
"""

import ctypes
import ctypes.wintypes as wintypes
from typing import List, NamedTuple, Optional

_hid = ctypes.WinDLL("hid")
_setupapi = ctypes.WinDLL("setupapi")
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

ERROR_IO_PENDING = 997
ERROR_DEVICE_NOT_CONNECTED = 1167
WAIT_TIMEOUT = 0x102
WAIT_OBJECT_0 = 0

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
        _hid.HidP_GetCaps(preparsed, ctypes.byref(caps))
    finally:
        _hid.HidD_FreePreparsedData(preparsed)
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
        handle = _kernel32.CreateFileW(
            path, GENERIC_READ | GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE,
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


class HidDevice(object):
    """One open HID interface with overlapped read and write.

    The reader thread and the writer thread may share an instance: each
    operation uses its own OVERLAPPED and event, which is what makes that safe.
    """

    def __init__(self, handle, info):
        self._handle = handle
        self.info = info
        self.last_error = None  # type: Optional[str]
        self._read_event = _kernel32.CreateEventW(None, True, False, None)
        self._write_event = _kernel32.CreateEventW(None, True, False, None)

    @classmethod
    def open(cls, path):
        handle = _kernel32.CreateFileW(
            path, GENERIC_READ | GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE,
            None, OPEN_EXISTING, FILE_FLAG_OVERLAPPED, None)
        if not handle or handle == INVALID_HANDLE_VALUE:
            raise HidError("cannot open %s: Win32 error %d" % (path, ctypes.get_last_error()))
        info = _describe(handle, path)
        if info is None:
            _kernel32.CloseHandle(handle)
            raise HidError("cannot read capabilities for %s" % path)
        return cls(handle, info)

    def read(self, timeout_ms=1000):
        """One input report, or None on timeout. Raises HidError if the device left."""
        if self._handle is None:
            raise HidError("device is closed")
        length = self.info.input_length
        buf = ctypes.create_string_buffer(length)
        transferred = wintypes.DWORD(0)
        overlapped = OVERLAPPED()
        overlapped.hEvent = self._read_event
        ok = _kernel32.ReadFile(self._handle, buf, length,
                                ctypes.byref(transferred), ctypes.byref(overlapped))
        if not ok:
            err = ctypes.get_last_error()
            if err != ERROR_IO_PENDING:
                raise HidError("ReadFile failed: Win32 error %d" % err)
            wait = _kernel32.WaitForSingleObject(self._read_event, timeout_ms)
            if wait == WAIT_TIMEOUT:
                _kernel32.CancelIoEx(self._handle, ctypes.byref(overlapped))
                _kernel32.GetOverlappedResult(self._handle, ctypes.byref(overlapped),
                                              ctypes.byref(transferred), True)
                return None
            if wait != WAIT_OBJECT_0:
                raise HidError("WaitForSingleObject returned %d" % wait)
            if not _kernel32.GetOverlappedResult(self._handle, ctypes.byref(overlapped),
                                                 ctypes.byref(transferred), False):
                raise HidError("GetOverlappedResult failed: Win32 error %d"
                               % ctypes.get_last_error())
        return buf.raw[:transferred.value]

    def write(self, data):
        """Send an output report, padded to OutputReportByteLength.

        WriteFile, never HidD_SetOutputReport: Microsoft documents that some
        devices stop responding when driven through HidD_SetXxx.
        """
        if self._handle is None:
            raise HidError("device is closed")
        length = self.info.output_length
        if len(data) > length:
            raise HidError("report is %d bytes, device accepts %d" % (len(data), length))
        buf = ctypes.create_string_buffer(bytes(data).ljust(length, b"\x00"), length)
        transferred = wintypes.DWORD(0)
        overlapped = OVERLAPPED()
        overlapped.hEvent = self._write_event
        ok = _kernel32.WriteFile(self._handle, buf, length,
                                 ctypes.byref(transferred), ctypes.byref(overlapped))
        if not ok:
            err = ctypes.get_last_error()
            if err != ERROR_IO_PENDING:
                self.last_error = "WriteFile failed: Win32 error %d" % err
                raise HidError(self.last_error)
            if _kernel32.WaitForSingleObject(self._write_event, 1000) != WAIT_OBJECT_0:
                _kernel32.CancelIoEx(self._handle, ctypes.byref(overlapped))
                self.last_error = "write timed out"
                raise HidError(self.last_error)
            if not _kernel32.GetOverlappedResult(self._handle, ctypes.byref(overlapped),
                                                 ctypes.byref(transferred), False):
                self.last_error = ("write failed: Win32 error %d" % ctypes.get_last_error())
                raise HidError(self.last_error)
        self.last_error = None
        return transferred.value

    def get_feature(self, report_id, length):
        """Read a feature report, or None if the device refused."""
        if self._handle is None:
            raise HidError("device is closed")
        buf = ctypes.create_string_buffer(length)
        buf[0] = bytes([report_id])
        if not _hid.HidD_GetFeature(self._handle, buf, length):
            self.last_error = ("HidD_GetFeature(%#x) failed: Win32 error %d"
                               % (report_id, ctypes.get_last_error()))
            return None
        return buf.raw[:length]

    def close(self):
        for event in (self._read_event, self._write_event):
            if event:
                _kernel32.CloseHandle(event)
        self._read_event = self._write_event = None
        if self._handle is not None:
            _kernel32.CancelIoEx(self._handle, None)
            _kernel32.CloseHandle(self._handle)
            self._handle = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False
