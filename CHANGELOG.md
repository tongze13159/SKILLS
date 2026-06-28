# Changelog

## v0.1.0-external-review

Released for third-party review and handoff.

### Added

- `README.md` with installation, run, and test instructions.
- `.env.example` with blank placeholders only, no real API keys.
- `docs/external_review_requirements.md` and `docs/external_review_requirements.docx` for review intake.
- `docs/review_tree.txt` for a complete source tree reference.
- `tests/test_review_pack.py` as a minimal review-oriented validation test.
- `docs/external_review_requirements.md` sections covering:
  - script inputs
  - script outputs
  - dependencies
  - environment variables
  - known risks
  - acceptance criteria

### Updated

- `SKILL.md` trigger wording for clearer activation on:
  - product showcase video remakes
  - viral shot replication
  - no-face product video reconstruction
  - TikTok / Douyin-style product demos
- `README.md` structure to make the project easier to audit externally.

### Verified

- Local unit tests passed before release.
- GitHub repository was updated and published with a tagged pre-release package.

### Notes

- The published release tag is `v0.1.0-external-review`.
- The repository `main` branch may move forward after the release tag if additional improvements are added.
