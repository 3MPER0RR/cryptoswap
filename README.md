## Quickstart

```bash
# install the only external dependency (for EVM side)
pip install web3

# run from the project root
python3 run.py
```

---

## CLI commands

| Key | Action |
|-----|--------|
| `N` | Create new BTC ↔ USDT/USDC swap |
| `B` | Generate Bitcoin P2SH HTLC address |
| `K` | Check BTC deposit status (via Mempool.space) |
| `F` | Fund EVM contract (Bob deposits USDT/USDC) |
| `C` | Claim EVM funds (Alice reveals secret) |
| `R` | Refund EVM funds (after timelock expiry) |
| `S` | Swap status (local + on-chain) |
| `I` | Network info (EVM + Bitcoin) |
| `E` | Export swap to JSON |
| `Q` | Quit |

---

## One-time setup: deploy the Solidity contract

This only needs to be done once. The contract lives on-chain permanently after deployment.

1. Open **https://remix.ethereum.org**
2. Create a new file → paste the contents of `chain/evm/HTLCSwap.sol`
3. Compile with Solidity **0.8.19**
4. Deploy → Environment: **Injected Provider (Metamask)** → select **Sepolia**
5. Copy the deployed contract address
6. Update `config.py`:
   ```python
   HTLC_CONTRACTS = {
       "sepolia": "0x<YOUR_CONTRACT_ADDRESS>"
   }
   ```
   or via environment variable:
   ```bash
   export HTLC_CONTRACT_SEPOLIA=0x<YOUR_CONTRACT_ADDRESS>
   ```

---

## Getting testnet funds

| Asset | Faucet |
|-------|--------|
| ETH Sepolia (gas fees) | https://sepoliafaucet.com |
| USDC Sepolia | https://faucet.circle.com |
| BTC Testnet | https://coinfaucet.eu/en/btc-testnet/ |

---

## Typical test flow

You can test the full swap solo using two Metamask accounts and two Electrum testnet wallets.


## Configuration reference

| Variable | Default | Description |
|----------|---------|-------------|
| `HTLC_CONTRACT_SEPOLIA` | `""` | Contract address after deploy |
| `BTC_NETWORK` | `testnet` | `testnet` or `mainnet` |
| `DEFAULT_TIMELOCK` | `86400` | Timelock in seconds (24h) |
| `SWAP_STORE` | `~/.atomicswap/swaps.json` | Local swap persistence file |

Override via environment variables or edit `config.py` directly.

---

## How the Bitcoin HTLC script works

```
IF
  OP_SHA256 <secretHash> OP_EQUALVERIFY
  OP_DUP OP_HASH160 <recipientPKH> OP_EQUALVERIFY OP_CHECKSIG
ELSE
  <timelock> OP_CHECKLOCKTIMEVERIFY OP_DROP
  OP_DUP OP_HASH160 <refundPKH> OP_EQUALVERIFY OP_CHECKSIG
ENDIF
```

The script is compiled into a P2SH address. Alice sends BTC to that address from any wallet (Electrum, hardware wallet, anything). No proprietary wallet required.

---

## Dependencies

- `web3` — EVM interactions only
- Everything else: Python 3.10+ stdlib

```bash
pip install web3
```

---

## Tests

```bash
python3 tests/test_htlc.py
```

```
── Happy path: BTC ↔ USDT complete swap
  ✓ Swap created in PENDING state
  ✓ Secret hash generated
  ✓ Secret verification correct
  ✓ Wrong secret rejected
  ✓ Alice deposits BTC → FUNDED_A
  ✓ Bob deposits USDT → ACTIVE
  ✓ Double deposit rejected
  ✓ Claim with wrong secret rejected
  ✓ Claim with correct secret succeeds
  ✓ State: CLAIMED
  ...

  Total: 34  ✓ 34  ✗ 0
```

---

## Security notes

Known HTLC attack vectors worth being aware of:

- **Timelock griefing** — attacker locks funds until expiry with no intent to claim
- **Fee sniping** — miners delay confirmations to exploit timelock boundaries
- **Secret leakage** — the secret must be transmitted out-of-band securely before claim
- **Race conditions** — claim vs timelock expiry on a congested chain

---

## Roadmap

- [ ] Electrum plugin — native UI tab inside Electrum wallet
- [ ] P2P layer (libp2p) — find counterparties without a central server
- [ ] Bitcoin spending transaction — native claim/refund via Bitcoin Script
- [ ] Tor hidden service — globally accessible, censorship-resistant
- [ ] Multi-asset support (ETH native, other ERC-20 tokens)

---

*Zero external dependencies on the core engine. Portable. No-KYC. No server.*
