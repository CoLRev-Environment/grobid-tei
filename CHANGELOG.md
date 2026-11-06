# Changelog

## 0.3.0 - 2026-11-06

### Added

- Add support for processing individual raw citations and citation lists.
- Declare Python 3.10–3.15 classifiers.

### Changed

- Cache the GROBID service version per client and document Docker startup.

## 0.2.0 - 2026-11-05

### Added

- Add `GrobidClient.version()` and optional `check_compatibility()` to identify
  known-incompatible GROBID service versions and warn about untested versions.
- Allow `TEIDocument.metadata(abstract=True)` to include the abstract in the
  returned metadata.
