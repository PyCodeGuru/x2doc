def test_package_exposes_version() -> None:
    """The installed package exposes a stable stage-one version."""
    import x2doc

    assert x2doc.__version__ == "0.1.0"
