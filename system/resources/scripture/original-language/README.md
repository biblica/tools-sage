# Governed original-language resources

SAGE resolves two stable logical aliases:

- `@GRK` (machine binding ID `GRK`) — Greek original-language Scripture.
- `@HEB` (machine binding ID `HEB`) — Hebrew original-language Scripture.

The default source is the corresponding bundled directory below this folder. The `0.01beta`
distribution includes the manually governed Greek NT and Hebrew Bible `.SFM` corpora in these two
directories. SAGE does not fabricate, infer a replacement authority, or silently download
original-language Scripture data. USFM remains the immutable distribution source; bounded USJ is
generated deterministically for runtime comparison.

Operators can explicitly reconfigure either alias to a recognized Paratext project or another local
resource. Overrides are stored in `SAGEdata/.system/state/original-language-resources.json`; ordinary Paratext Project
registration is not used for these governed aliases.
