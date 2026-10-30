"""Frozen controls for attributing recall gains without changing source facts."""


ARMS = {
    "main": {},
    "main_k5": {"top_k":5},
    "main_history": {"history":True},
    "main_policy": {"policy":True},
    "main_units": {"units":True},
    "main_fixes": {"top_k":5, "history":True, "policy":True, "units":True},
    "main_fixes_rewrite": {"top_k":5, "history":True, "policy":True,
                           "units":True, "rewrite":True},
    "wiki": {"top_k":5, "history":True, "policy":True,
             "units":True, "rewrite":True, "wiki":True},
}


def ordered_arms(index, rep=0):
    """Rotate all arms before reversing a repeat, balancing first position."""
    arms = list(ARMS)
    offset = index % len(arms)
    arms = arms[offset:] + arms[:offset]
    return list(reversed(arms)) if rep % 2 else arms


def recall_controls(arm):
    settings = ARMS[arm]
    return {
        "formal_top_k":settings.get("top_k", 3),
        "include_units":settings.get("units", False),
        "include_wiki":settings.get("wiki", False),
        "rewrite":settings.get("rewrite", False),
    }
