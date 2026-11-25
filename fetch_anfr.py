"""Download the latest ANFR register of radio supports into data/anfr/<date>/.

    uv run python fetch_anfr.py        # or: make anfr

find_candidates.py and resolve_points_hauts.py read the newest folder there by
default. Run it again before a new study: the register is published monthly,
and the owner of a pylon — public body, network operator or tower company —
changes as tower companies buy operators' pylons. See analysis_shape/anfr.py.
"""

from analysis_shape.anfr import fetch_latest

if __name__ == "__main__":
    fetch_latest()
