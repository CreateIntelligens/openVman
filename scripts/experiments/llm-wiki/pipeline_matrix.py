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


def ordered_arms(index):
    arms = list(ARMS)
    offset = index % len(arms)
    return arms[offset:] + arms[:offset]
