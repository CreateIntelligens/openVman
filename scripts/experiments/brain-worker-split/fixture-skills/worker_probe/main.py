"""Synthetic skill used only by the isolated worker acceptance stack."""


def worker_probe_status(args):
    return {"synthetic": True}
