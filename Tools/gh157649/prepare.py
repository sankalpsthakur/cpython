"""Prepare the gh-157649 regression and fix against a pinned CPython tree."""
import argparse
import hashlib
from pathlib import Path

BASE = "854295809ad5a42c9461f34d47b1252a3b4a2027"
NEWS = "Misc/NEWS.d/next/C API/2026-09-18-01-00-00.gh-issue-157649.cppref.rst"
TEST = r'''// gh-157649: Reference-counting macros must copy the old pointer, not
// alias an array element or a C++ reference that is about to be overwritten.
static int
test_refcount_macros(void)
{
    PyObject *old_obj = PyList_New(0);
    if (old_obj == _Py_NULL) {
        return -1;
    }
    const Py_ssize_t old_refcnt = Py_REFCNT(old_obj);
    PyObject *objects[1] = {Py_NewRef(old_obj)};
    int index = 0;

    Py_CLEAR(objects[index++]);
    assert(index == 1);
    assert(objects[0] == _Py_NULL);
    assert(Py_REFCNT(old_obj) == old_refcnt);
    Py_CLEAR(objects[0]);  // A null destination is also valid.

    PyObject *&object_ref = objects[0];
    object_ref = Py_NewRef(old_obj);
    Py_CLEAR(object_ref);
    assert(objects[0] == _Py_NULL);
    assert(Py_REFCNT(old_obj) == old_refcnt);

    objects[0] = Py_NewRef(old_obj);
    Py_CLEAR((objects[0]));
    assert(objects[0] == _Py_NULL);
    assert(Py_REFCNT(old_obj) == old_refcnt);

#ifndef Py_LIMITED_API
    PyObject *new_obj = PyList_New(0);
    if (new_obj == _Py_NULL) {
        Py_DECREF(old_obj);
        return -1;
    }
    const Py_ssize_t new_refcnt = Py_REFCNT(new_obj);
    PyObject *sources[1] = {new_obj};
    int source_index = 0;

    objects[0] = Py_NewRef(old_obj);
    index = 0;
    Py_SETREF(objects[index++], Py_NewRef(sources[source_index++]));
    assert(index == 1 && source_index == 1);
    assert(objects[0] == new_obj);
    assert(Py_REFCNT(old_obj) == old_refcnt);
    assert(Py_REFCNT(new_obj) == new_refcnt + 1);
    Py_CLEAR(objects[0]);

    object_ref = Py_NewRef(old_obj);
    Py_SETREF(object_ref, Py_NewRef(new_obj));
    assert(objects[0] == new_obj);
    assert(Py_REFCNT(old_obj) == old_refcnt);
    assert(Py_REFCNT(new_obj) == new_refcnt + 1);
    Py_CLEAR(objects[0]);

    objects[0] = Py_NewRef(old_obj);
    index = source_index = 0;
    Py_XSETREF(objects[index++], Py_NewRef(sources[source_index++]));
    assert(index == 1 && source_index == 1);
    assert(objects[0] == new_obj);
    assert(Py_REFCNT(old_obj) == old_refcnt);
    assert(Py_REFCNT(new_obj) == new_refcnt + 1);
    Py_CLEAR(objects[0]);

    object_ref = Py_NewRef(old_obj);
    Py_XSETREF(object_ref, Py_NewRef(new_obj));
    assert(objects[0] == new_obj);
    assert(Py_REFCNT(old_obj) == old_refcnt);
    assert(Py_REFCNT(new_obj) == new_refcnt + 1);
    Py_XSETREF(objects[0], _Py_NULL);
    assert(objects[0] == _Py_NULL);
    assert(Py_REFCNT(new_obj) == new_refcnt);

    Py_XSETREF(objects[0], Py_NewRef(new_obj));
    assert(objects[0] == new_obj);
    assert(Py_REFCNT(new_obj) == new_refcnt + 1);
    Py_CLEAR(objects[0]);
    assert(Py_REFCNT(new_obj) == new_refcnt);
    Py_XSETREF(objects[0], _Py_NULL);

    // Keep the existing strict-aliasing-safe support for typed pointers.
    PyListObject *list_obj = (PyListObject *)Py_NewRef(old_obj);
    Py_CLEAR(list_obj);
    assert(list_obj == _Py_NULL);
    assert(Py_REFCNT(old_obj) == old_refcnt);
    list_obj = (PyListObject *)Py_NewRef(old_obj);
    Py_SETREF(list_obj, (PyListObject *)Py_NewRef(new_obj));
    assert((PyObject *)list_obj == new_obj);
    assert(Py_REFCNT(old_obj) == old_refcnt);
    assert(Py_REFCNT(new_obj) == new_refcnt + 1);
    Py_XSETREF(list_obj, _Py_NULL);
    assert(list_obj == _Py_NULL);
    assert(Py_REFCNT(new_obj) == new_refcnt);
    Py_DECREF(new_obj);
#endif

    Py_DECREF(old_obj);
    return 0;
}


'''
OLD = '''// On C23, use typeof(). On C++11, use decltype(). Otherwise, use __typeof__()
// if on GCC, clang or MSVC 17.9 and newer.
//
// On MSVC, check also _MSVC_LANG since __cplusplus is 199711L unless
// the /Zc:__cplusplus flag is used.
#if defined (__STDC_VERSION__) && __STDC_VERSION__ >= 202311L
#  define _Py_TYPEOF(expr) typeof(expr)
#elif defined(__cplusplus) && (__cplusplus >= 201103L ||  _MSVC_LANG >= 201103L)
#  define _Py_TYPEOF(expr) decltype(expr)
#elif defined(__GNUC__) || defined(__clang__) || \\
    (defined(_MSC_VER) && _MSC_VER >= 1939)
#  define _Py_TYPEOF(expr) __typeof__(expr)
#endif'''
NEW = '''// On C23, use typeof(). Otherwise, use __typeof__() if on GCC, clang
// or MSVC 17.9 and newer.
//
// Do not define _Py_TYPEOF() in C++: decltype() can produce a reference type,
// aliasing the old pointer in Py_CLEAR() and Py_SETREF(). Use their memcpy()
// implementations instead (gh-157649).
#ifndef __cplusplus
#  if defined (__STDC_VERSION__) && __STDC_VERSION__ >= 202311L
#    define _Py_TYPEOF(expr) typeof(expr)
#  elif defined(__GNUC__) || defined(__clang__) || \\
      (defined(_MSC_VER) && _MSC_VER >= 1939)
#    define _Py_TYPEOF(expr) __typeof__(expr)
#  endif
#endif'''


def read_verified(path, expected):
    data = Path(path).read_bytes()
    actual = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
    if actual != expected:
        raise RuntimeError(f"Unexpected input for {path}: {actual}")
    return data.decode()


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError("Replacement anchor was not unique")
    return text.replace(old, new, 1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("tests", "fix"))
    args = parser.parse_args()
    if args.phase == "tests":
        path = "Lib/test/test_cppext/extension.cpp"
        text = read_verified(path, "1ff56d0e7fd25a0c6f5d2625156d286a7a90aea5")
        anchor = "static int\n_testcppext_exec(PyObject *module)"
        text = replace_once(text, anchor, TEST + anchor)
        anchor = "    // test Py_BUILD_ASSERT() and Py_BUILD_ASSERT_EXPR()"
        text = replace_once(text, anchor, "    if (test_refcount_macros() < 0) {\n        return -1;\n    }\n\n" + anchor)
        Path(path).write_text(text)
    else:
        path = "Include/pyport.h"
        text = read_verified(path, "744bae6c57e299efcf8b5769fb9f42288b0146b3")
        Path(path).write_text(replace_once(text, OLD, NEW))
        Path(NEWS).write_text(
            "Fix a C++ regression in :c:macro:`Py_CLEAR`, :c:macro:`Py_SETREF`,\n"
            "and :c:macro:`Py_XSETREF` that could corrupt reference counts or crash\n"
            "when used with array elements or reference variables. Use the existing\n"
            "``memcpy()`` implementations in C++ instead of ``decltype()``.\n"
        )


if __name__ == "__main__":
    main()
