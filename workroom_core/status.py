from . import VERSION


def collect_status(data_dir=None, hermes_version=None):
    """Plain data describing the plugin's readiness. No Hermes imports here: the adapters pass values in."""
    return {
        "workroom_version": VERSION,
        "hermes_version": hermes_version,
        "data_dir": str(data_dir) if data_dir else None,
        "ready": True,
        "stage": "skeleton",
    }
