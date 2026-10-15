# Pinned Ripwire discovery fixture

Expected call chain: `test_invoice_total` → `invoice_total` → `calculate_total`.
Affected tests for `service.py` should include `test_service.py`.
Run `RIPWIRE_TEST_ARCHIVE=/absolute/path/to/published-platform-archive.tar.gz
python3 -m unittest tests.test_ripwire.PinnedRipwireTest` to verify the real pinned release.
The archive is supplied locally and checked against the production release manifest;
automated tests never download it. Without it, this optional test is skipped.
