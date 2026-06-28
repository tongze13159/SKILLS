from .base import adapter_stub

def run(*, dry_run: bool, **kwargs):
    return adapter_stub("Remotion", "REMOTION_LOCAL", dry_run=dry_run, **kwargs)
