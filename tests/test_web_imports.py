"""Every ES-module specifier under web/ must resolve to a file on disk.

Nothing else in this suite loads the page, so a missing module is invisible
to it: Python never imports the JavaScript, and the browser reports the 404
only to a console nobody is reading. That is exactly how the vendored
three.js shipped broken -- `three.module.js` is the *minified* build, which
re-exports from `./three.core.min.js`, and only that one half was copied.
Every import in the graph 404'd and the 3D view was a blank canvas.

So this walks the real tree and resolves the real specifiers. It is a file
check, not a parser: it cannot tell you the page works, only that no import
points at nothing.
"""

import pathlib
import re
import unittest

WEB = pathlib.Path(__file__).resolve().parent.parent / "web"

# An import may span several lines:
#     import {
#       Foo,
#     } from './bar.js';
# but never a semicolon, which is what bounds the gap. The minified build
# writes `from"./x.js"` with no space, so the whitespace is optional.
_FROM = re.compile(r"^[ \t]*(?:import|export)[^;]*?from\s*['\"]([^'\"]+)['\"]",
                   re.MULTILINE)
# `import './side-effect.js';` has no `from` clause at all.
_BARE = re.compile(r"^[ \t]*import\s*['\"]([^'\"]+)['\"]", re.MULTILINE)


def specifiers():
    """(source file, specifier) for every real import statement under web/.

    Line-initial only, on purpose. The vendored three.js addons carry JSDoc
    examples that read `import {x} from 'three/addons/...'` inside a comment
    block, where every line starts with ` * `. Anchoring to the line start
    keeps those out without having to strip comments.
    """
    for path in sorted(WEB.rglob("*.js")):
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in _FROM.finditer(text):
            yield path, match.group(1)
        for match in _BARE.finditer(text):
            yield path, match.group(1)


class TestWebImports(unittest.TestCase):
    def test_web_directory_exists(self):
        # A rename of web/ would otherwise make every test below pass on an
        # empty iterator.
        self.assertTrue(WEB.is_dir(), "%s is missing" % WEB)
        self.assertTrue(any(WEB.rglob("*.js")), "no .js found under %s" % WEB)

    def test_every_relative_import_resolves(self):
        missing = []
        for path, spec in specifiers():
            if not spec.startswith("."):
                continue
            target = (path.parent / spec).resolve()
            if not target.is_file():
                missing.append("%s imports %s -> %s"
                               % (path.relative_to(WEB), spec, target))
        self.assertEqual([], missing)

    def test_no_import_uses_a_bare_specifier(self):
        # The page loads from a plain static server with no import map, so a
        # bare specifier cannot resolve in the browser at all.
        bare = ["%s imports %s" % (path.relative_to(WEB), spec)
                for path, spec in specifiers()
                if not spec.startswith(".") and not spec.startswith("/")]
        self.assertEqual([], bare)

    def test_the_check_can_actually_fail(self):
        # A guard whose negative case is never exercised is a guard that
        # passes because it matched nothing. This is the same check against a
        # specifier that is known not to exist.
        probe = WEB / "js" / "app.js"
        self.assertTrue(probe.is_file(), "fixture moved: %s" % probe)
        self.assertFalse((probe.parent / "./definitely-not-here.js").resolve().is_file())

    def test_the_split_three_build_is_whole(self):
        # Named directly because this is the defect that shipped: the minified
        # three.module.js is only half the library.
        vendor = WEB / "vendor" / "three"
        module = vendor / "three.module.js"
        self.assertTrue(module.is_file(), "three.module.js is missing")
        if 'from"./three.core.min.js"' in module.read_text(
                encoding="utf-8", errors="replace"):
            self.assertTrue((vendor / "three.core.min.js").is_file(),
                            "three.module.js is the minified build and needs "
                            "three.core.min.js beside it")


if __name__ == "__main__":
    unittest.main()
