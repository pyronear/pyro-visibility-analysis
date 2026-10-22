"""Greedy selection of camera sites by marginal contribution.

Two callers need the same answer to the same question — "which N sites add the
most to what is already there" — `prioritise_sites.py` to rank candidates and
`scenario_layers.py` to build an « existants + N » scenario. Keeping one
implementation means a scenario can never disagree with the ranking that
justified it.

Two criteria, because they do not progress at the same rate. Between 92 % and
95 % of coverage on a test département, triangulation gained 13 points: the best sites
for *seeing* a zone are not always the best for *locating* a fire in it.

    couverture     maximise the area seen by at least one camera
    triangulation  maximise the area seen by at least two
"""

import numpy as np

CRITERIA = ("couverture", "triangulation")


class WindowedMask:
    """A visibility mask kept as its bounding window only.

    A viewshed is a disc of the detection radius on a DEM that covers every
    site plus a buffer: at 15 km on a test département's grid, one mask is ~9 Mpx of
    signal in a 117 Mpx raster. Holding 32 of them as full boolean arrays took
    ~3.7 GB; holding the windows takes ~0.3 GB, and the gain is computed on the
    window alone — identical, since outside it the mask adds nothing.
    """

    __slots__ = ("rows", "cols", "data")

    def __init__(self, mask):
        rows = np.flatnonzero(mask.any(axis=1))
        cols = np.flatnonzero(mask.any(axis=0))
        if rows.size == 0:
            self.rows = self.cols = slice(0, 0)
        else:
            self.rows = slice(int(rows[0]), int(rows[-1]) + 1)
            self.cols = slice(int(cols[0]), int(cols[-1]) + 1)
        self.data = mask[self.rows, self.cols].copy()


def _windowed(mask):
    return mask if isinstance(mask, WindowedMask) else WindowedMask(mask)


def _gain(counts, extra, zone, criterion):
    """Zone area the `extra` mask would add under `criterion`, in cells."""
    threshold = 2 if criterion == "triangulation" else 1
    window = (extra.rows, extra.cols)
    before = counts[window]
    after = (before + extra.data) >= threshold
    return int((after & (before < threshold) & zone[window]).sum())


def greedy_pick(candidates, zone_mask, baseline_masks=(), picks=None,
                criterion="couverture", target_cells=None, on_pick=None,
                categories=None, max_operateurs=None):
    """Pick sites, each time the one adding the most under `criterion`.

    `candidates` maps a site name to its boolean visibility mask. Returns a list
    of (name, gain_in_cells, cumulative_in_cells).

    Stops at whichever comes first: `picks` sites chosen, `target_cells` reached,
    or nothing left that adds anything. Passing `target_cells` answers the more
    useful question — not "what do 6 sites give me" but "how many sites does
    95 % take" — and a caller that gets back fewer sites than candidates offered
    with the target unmet knows the target is out of reach.

    Counts are kept as a running per-cell camera count rather than a single
    boolean union, because triangulation needs to know the difference between
    one camera and two.

    `categories` (name → "public"/"operateur"/…) and `max_operateurs` cap the
    access cost of the result: once that many non-public sites are chosen,
    every later step is restricted to public candidates only, instead of
    picking the single best site regardless of who owns it. On a test département,
    an uncapped top 30 took 28 operator sites and 2 public — the best individual
    points are almost all private, so without this the "free" and "capped"
    scenarios would otherwise need two separate, hand-reconciled runs.
    """
    if criterion not in CRITERIA:
        raise ValueError(f"criterion must be one of {CRITERIA}, got {criterion!r}")

    counts = np.zeros(zone_mask.shape, dtype=np.uint8)
    for mask in baseline_masks:
        counts += mask

    # Callers may pass full arrays or WindowedMask; either way only the window
    # is kept, so a caller that already windowed its masks pays nothing here.
    remaining = {name: _windowed(mask) for name, mask in candidates.items()}
    chosen = []
    limit = len(remaining) if picks is None else min(picks, len(remaining))

    def reached_now():
        seen = (counts >= 2) if criterion == "triangulation" else (counts >= 1)
        return int((seen & zone_mask).sum())

    if target_cells is not None and reached_now() >= target_cells:
        return chosen  # the baseline alone already meets the target

    # Only the sites picked in *this* call count against the cap — a baseline
    # passed as plain masks carries no names, so an operator site already
    # EN PLACE is not counted. Harmless while no scenario mixes the two; worth
    # revisiting if one ever does.
    n_operateurs = 0

    for _ in range(limit):
        cap_hit = max_operateurs is not None and n_operateurs >= max_operateurs
        best, best_key = None, (0, 0)
        for name, mask in remaining.items():
            if cap_hit and categories is not None and categories.get(name) != "public":
                continue
            gain = _gain(counts, mask, zone_mask, criterion)
            # With no baseline, no single camera triangulates anything: every
            # gain is 0 and the greedy used to stop before its first pick. A test
            # département always had cameras EN PLACE, which hid it; another
            # had none. Coverage breaks the tie, so the first picks lay the
            # ground the next ones triangulate on.
            tie = (_gain(counts, mask, zone_mask, "couverture")
                   if criterion == "triangulation" else 0)
            if (gain, tie) > best_key:
                best, best_key = name, (gain, tie)
        if best is None:
            break  # nothing left adds anything — stop rather than pad the list
        best_gain = best_key[0]
        picked = remaining.pop(best)
        if categories is not None and categories.get(best) != "public":
            n_operateurs += 1
        counts[picked.rows, picked.cols] += picked.data
        reached = reached_now()
        chosen.append((best, best_gain, reached))
        if on_pick:
            on_pick(len(chosen), best, best_gain, reached)
        if target_cells is not None and reached >= target_cells:
            break
    return chosen
