"""Package the native WGL/ctypes path used by this app.

The stock hook collects optional NumPy/.NET array adapters and GLUT/GLE DLLs.
Our renderer uses ctypes arrays and Windows' system OpenGL, exactly like the
tested source venv, so none of those optional runtimes belong in the EXE.
"""
hiddenimports = ['OpenGL.platform.win32'] + [
    'OpenGL.arrays.' + name for name in (
        'ctypesarrays', 'ctypesparameters', 'ctypespointers', 'lists', 'nones',
        'numbers', 'strings', 'buffers', 'arraydatatype', 'arrayhelpers',
        'formathandler', 'vbo')
]
