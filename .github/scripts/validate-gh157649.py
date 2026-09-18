"""Apply the reviewed, exact-text regression test and C++ compatibility fix."""
from pathlib import Path
import sys

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
NEW = '''// On C23, use typeof(). Otherwise, use __typeof__() if on GCC, clang or
// MSVC 17.9 and newer.
//
// In C++, decltype() can produce a reference type for an lvalue expression,
// making a refcount macro's temporary alias its destination (gh-157649).
// Leave _Py_TYPEOF undefined to use the existing memcpy() implementations.
#if !defined(__cplusplus)
#  if defined (__STDC_VERSION__) && __STDC_VERSION__ >= 202311L
#    define _Py_TYPEOF(expr) typeof(expr)
#  elif defined(__GNUC__) || defined(__clang__) || \\
        (defined(_MSC_VER) && _MSC_VER >= 1939)
#    define _Py_TYPEOF(expr) __typeof__(expr)
#  endif
#endif'''
TEST = '''// gh-157649: Refcount temporaries must copy the old pointer, not bind to
// an array item or reference that the macro is about to overwrite.
static int
test_refcount_lvalues(void)
{
    PyObject *old_obj = PyList_New(0);
    if (old_obj == _Py_NULL) {
        return -1;
    }
    PyObject *new_obj = PyList_New(0);
    if (new_obj == _Py_NULL) {
        Py_DECREF(old_obj);
        return -1;
    }
    PyObject *slots[2] = {Py_NewRef(old_obj), _Py_NULL};

#ifndef Py_LIMITED_API
    Py_SETREF(slots[0], Py_NewRef(new_obj));
    assert(slots[0] == new_obj);
    assert(Py_REFCNT(old_obj) == 1);
    assert(Py_REFCNT(new_obj) == 2);

    Py_XSETREF(slots[0], Py_NewRef(old_obj));
    assert(slots[0] == old_obj);
    assert(Py_REFCNT(old_obj) == 2);
    assert(Py_REFCNT(new_obj) == 1);
#endif

    int index = 0;
    Py_CLEAR(slots[index++]);
    assert(index == 1);
    assert(slots[0] == _Py_NULL);
    assert(Py_REFCNT(old_obj) == 1);
    Py_CLEAR(slots[0]);

    slots[0] = Py_NewRef(old_obj);
    PyObject *&slot = slots[0];
    Py_CLEAR(slot);
    assert(slots[0] == _Py_NULL);
    assert(Py_REFCNT(old_obj) == 1);

#ifndef Py_LIMITED_API
    slot = Py_NewRef(old_obj);
    Py_SETREF(slot, Py_NewRef(new_obj));
    assert(slots[0] == new_obj);
    assert(Py_REFCNT(old_obj) == 1);
    assert(Py_REFCNT(new_obj) == 2);

    Py_XSETREF((slot), Py_NewRef(old_obj));
    assert(slots[0] == old_obj);
    assert(Py_REFCNT(old_obj) == 2);
    assert(Py_REFCNT(new_obj) == 1);
    Py_CLEAR(slot);

    // Both arguments must be evaluated once, including a NULL destination.
    index = 0;
    Py_XSETREF(slots[index++], Py_NewRef(new_obj));
    assert(index == 1);
    assert(slots[0] == new_obj);
    assert(Py_REFCNT(new_obj) == 2);
    Py_CLEAR(slots[0]);

    // Preserve support for pointers to concrete object types.
    PyListObject *lists[1] = {(PyListObject *)Py_NewRef(old_obj)};
    Py_SETREF(lists[0], (PyListObject *)Py_NewRef(new_obj));
    assert((PyObject *)lists[0] == new_obj);
    assert(Py_REFCNT(old_obj) == 1);
    assert(Py_REFCNT(new_obj) == 2);
    Py_CLEAR(lists[0]);
    assert(lists[0] == _Py_NULL);
#endif

    assert(Py_REFCNT(old_obj) == 1);
    assert(Py_REFCNT(new_obj) == 1);
    Py_DECREF(old_obj);
    Py_DECREF(new_obj);
    return 0;
}

'''

def replace_once(path, before, after):
    path = Path(path)
    text = path.read_text()
    if text.count(before) != 1:
        raise RuntimeError(f"Expected exactly one anchor in {path}")
    path.write_text(text.replace(before, after, 1))

if sys.argv[1:] == ["tests"]:
    path = "Lib/test/test_cppext/extension.cpp"
    anchor = "static PyMethodDef _testcppext_methods[] = {"
    replace_once(path, anchor, TEST + anchor)
    anchor = "    // test Py_BUILD_ASSERT() and Py_BUILD_ASSERT_EXPR()"
    replace_once(path, anchor, "    if (test_refcount_lvalues() < 0) {\n        return -1;\n    }\n\n" + anchor)
elif sys.argv[1:] == ["fix"]:
    replace_once("Include/pyport.h", OLD, NEW)
    Path("Misc/NEWS.d/next/C_API/2026-09-18-00-00-00.gh-issue-157649.CppRef.rst").write_text(
        "Fix a C++ regression in :c:macro:`Py_CLEAR`, :c:macro:`Py_SETREF` and\n"
        ":c:macro:`Py_XSETREF` when the destination is an array item or a reference.\n"
        "The macros could decrement the wrong object's reference count or crash.\n"
    )
else:
    raise SystemExit("usage: prepare.py tests|fix")
