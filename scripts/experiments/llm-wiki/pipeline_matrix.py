"""Separate prepared MD retrieval from optional online processing."""


ARMS = {
    "main": {},
    "raw_direct": {"banks":["raw"], "multi":False},
    "grouped_direct": {"banks":["grouped"], "multi":False},
    "md_direct": {"banks":["compiled"], "multi":False},
    "md_multi": {"banks":["compiled"], "multi":True},
    "md_rewrite": {"banks":["compiled"], "multi":True, "rewrite":True},
    "mixed_multi": {"banks":["raw", "compiled"], "multi":True},
    "md_products": {"banks":["compiled"], "multi":False, "products":True},
}


FOLLOWUP_ARMS = {
    **ARMS,
    "raw_multi": {"banks": ["raw"], "multi": True},
    "raw_guarded": {
        "banks": ["raw"], "multi": True, "products": True,
        "force_products": True, "policy": "evidence_v2",
    },
    "md_guarded": {
        "banks": ["compiled"], "multi": True, "products": True,
        "force_products": True, "policy": "evidence_v2",
    },
}

FOLLOWUP_ARMS.update({
    name + "_cached": {**FOLLOWUP_ARMS[name], "catalog_cache": True}
    for name in ("raw_guarded", "md_guarded")
})


CLEAN_INDEX_ARMS = {
    "main": {},
    "main_noise": {"formal": True, "products": True},
    "raw_multi": {"banks": ["raw"], "multi": True, "products": True},
}


def selected_arms(followup=False, names=None):
    matrix = FOLLOWUP_ARMS if followup else ARMS
    if names is None:
        return dict(matrix)
    if not names or len(set(names)) != len(names) or set(names) - matrix.keys():
        raise ValueError("Invalid pipeline arm selection")
    if "main" not in names:
        raise ValueError("Pipeline comparison requires the main control")
    return {name: matrix[name] for name in names}


def ordered_arms(index, rep=0, arms=None):
    arms = list(ARMS if arms is None else arms)
    offset = (index + rep) % len(arms)
    order = arms[offset:] + arms[:offset]
    return order if rep % 2 == 0 else list(reversed(order))
