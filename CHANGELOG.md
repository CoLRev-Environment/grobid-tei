# Changelog

## 0.2.0 - 2026-11-05

### Added

- Add `GrobidClient.version()` and optional `check_compatibility()` to identify
  known-incompatible GROBID service versions and warn about untested versions.
- Allow `TEIDocument.metadata(abstract=True)` to include the abstract in the
  returned metadata.
