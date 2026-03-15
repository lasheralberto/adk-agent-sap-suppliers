def test_import_packages():
    """Smoke test: ensure top-level packages import without ImportError.
    This test does not execute side-effects intentionally.
    """
    import importlib

    modules = [
        "agent",
        "tools.vectors",
        "tools.vectors.providers",
        "tools.memory",
    ]

    for m in modules:
        importlib.import_module(m)

    assert True
