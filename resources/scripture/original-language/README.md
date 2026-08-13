# Governed original-language resources

SAGE resolves two stable logical aliases:

- `@GRK` (machine binding ID `GRK`) — Greek original-language Scripture.
- `@HEB` (machine binding ID `HEB`) — Hebrew original-language Scripture.

The default source is the corresponding bundled directory below this folder. The source package
contains the governed slots and validation/configuration logic; an authorised Scripture corpus must
be present as top-level `.SFM` files for an alias to become `READY`. SAGE does not fabricate or
silently download original-language Scripture data.

Operators can explicitly reconfigure either alias to a recognised Paratext project or another local
resource. Overrides are stored in `state/original-language-resources.json`; ordinary Paratext Project
registration is not used for these governed aliases.
