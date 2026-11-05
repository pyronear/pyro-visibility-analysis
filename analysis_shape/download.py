"""Download raster chunks in parallel, retrying the failed ones at the end.

The IGN WMS takes seconds per chunk, so a DEM of a few hundred chunks took
hours one request at a time, and a single failed chunk threw the whole
download away. Here a few requests run at once, and a chunk that fails is set
aside: once every chunk has been tried, the failed ones get another pass, up to
RETRY_PASSES times.

Results go to `on_result` in the calling thread, so a raster is only ever
written from one thread (rasterio datasets are not thread-safe).
"""

import time
from concurrent.futures import ThreadPoolExecutor, as_completed

WORKERS = 4  # more risks being throttled by the IGN servers
RETRY_PASSES = 3
PASS_PAUSE_S = 30  # lets a short WMS outage pass before retrying


def fetch_parallel(chunks, fetch, on_result, workers=WORKERS,
                   retry_passes=RETRY_PASSES, pause_s=PASS_PAUSE_S):
    """Call fetch(chunk) for every chunk, then on_result(chunk, data).

    Only an exception raised by fetch is retried; one raised by on_result (a
    write error) stops the run. Returns the chunks still failing after the
    retry passes.
    """
    pending = list(chunks)
    for attempt in range(retry_passes + 1):
        if not pending:
            break
        if attempt:
            print(f"   ↻ retry pass {attempt}/{retry_passes}: "
                  f"{len(pending)} chunk(s) in {pause_s}s")
            time.sleep(pause_s)
        failed = []
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(fetch, chunk): chunk for chunk in pending}
            try:
                for future in as_completed(futures):
                    chunk = futures.pop(future)  # frees the array once written
                    try:
                        data = future.result()
                    except Exception as exc:  # noqa: BLE001 - retried next pass
                        print(f"   ⚠️  chunk failed ({type(exc).__name__}: {exc})")
                        failed.append(chunk)
                        continue
                    on_result(chunk, data)
            except BaseException:
                # Leaving the block would otherwise wait for every queued request.
                pool.shutdown(wait=False, cancel_futures=True)
                raise
        pending = failed
    return pending


if __name__ == "__main__":
    import threading

    calls = {}
    main_thread = threading.get_ident()

    def fake_fetch(chunk):
        calls[chunk] = calls.get(chunk, 0) + 1
        if chunk == "dead" or (chunk == "flaky" and calls[chunk] == 1):
            raise OSError("boom")
        return chunk.upper()

    written = {}

    def record(chunk, data):
        assert threading.get_ident() == main_thread
        written[chunk] = data

    left = fetch_parallel(["ok", "flaky", "dead"], fake_fetch, record, pause_s=0)
    assert left == ["dead"], left
    assert written == {"ok": "OK", "flaky": "FLAKY"}, written
    assert calls == {"ok": 1, "flaky": 2, "dead": 1 + RETRY_PASSES}, calls

    def broken_write(chunk, data):
        raise ValueError("disk full")

    try:
        fetch_parallel(["ok"], fake_fetch, broken_write, pause_s=0)
    except ValueError:
        pass
    else:
        raise AssertionError("a write error must stop the run, not be retried")
    print("download self-check ok")
