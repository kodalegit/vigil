from vigil.settings import _secret_version_name


def test_secret_version_name_accepts_full_resource_or_secret_id() -> None:
    assert (
        _secret_version_name(
            "projects/acme/secrets/slack-token/versions/3",
            project_id="ignored",
        )
        == "projects/acme/secrets/slack-token/versions/3"
    )
    assert (
        _secret_version_name(
            "projects/acme/secrets/slack-token",
            project_id="ignored",
        )
        == "projects/acme/secrets/slack-token/versions/latest"
    )
    assert _secret_version_name("slack-token", project_id="acme") == (
        "projects/acme/secrets/slack-token/versions/latest"
    )
    assert _secret_version_name("slack-token", project_id=None) is None
