# Security

Never commit Binance API credentials. Keep secrets in `.env`, which is ignored by Git.

Oberon currently permits only `paper` and `testnet` trading modes and validates that Testnet mode points at `testnet.binance.vision` endpoints.

If credentials are accidentally exposed, revoke them immediately in Binance Testnet and generate replacements.
