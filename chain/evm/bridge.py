"""
EVM Bridge — interazione con HTLCSwap.sol su Sepolia (o qualsiasi EVM)
Nessun wallet proprietario: accetta chiave privata o signing esterno.
"""

import hashlib
import json
import os
import time
from typing import Optional
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

# ABI minimale del contratto HTLCSwap
HTLC_ABI = json.loads("""[
  {
    "name": "fund",
    "type": "function",
    "stateMutability": "nonpayable",
    "inputs": [
      {"name": "swapId",     "type": "bytes32"},
      {"name": "secretHash", "type": "bytes32"},
      {"name": "timelock",   "type": "uint256"},
      {"name": "recipient",  "type": "address"},
      {"name": "token",      "type": "address"},
      {"name": "amount",     "type": "uint256"}
    ],
    "outputs": []
  },
  {
    "name": "fundETH",
    "type": "function",
    "stateMutability": "payable",
    "inputs": [
      {"name": "swapId",     "type": "bytes32"},
      {"name": "secretHash", "type": "bytes32"},
      {"name": "timelock",   "type": "uint256"},
      {"name": "recipient",  "type": "address"}
    ],
    "outputs": []
  },
  {
    "name": "claim",
    "type": "function",
    "stateMutability": "nonpayable",
    "inputs": [
      {"name": "swapId", "type": "bytes32"},
      {"name": "secret", "type": "bytes32"}
    ],
    "outputs": []
  },
  {
    "name": "refund",
    "type": "function",
    "stateMutability": "nonpayable",
    "inputs": [{"name": "swapId", "type": "bytes32"}],
    "outputs": []
  },
  {
    "name": "getSwap",
    "type": "function",
    "stateMutability": "view",
    "inputs": [{"name": "swapId", "type": "bytes32"}],
    "outputs": [
      {"name": "", "type": "tuple", "components": [
        {"name": "secretHash", "type": "bytes32"},
        {"name": "timelock",   "type": "uint256"},
        {"name": "funder",     "type": "address"},
        {"name": "recipient",  "type": "address"},
        {"name": "token",      "type": "address"},
        {"name": "amount",     "type": "uint256"},
        {"name": "state",      "type": "uint8"},
        {"name": "secret",     "type": "bytes32"},
        {"name": "fundedAt",   "type": "uint256"},
        {"name": "claimedAt",  "type": "uint256"}
      ]}
    ]
  },
  {
    "name": "isClaimable",
    "type": "function",
    "stateMutability": "view",
    "inputs": [{"name": "swapId", "type": "bytes32"}],
    "outputs": [{"name": "", "type": "bool"}]
  },
  {
    "name": "isRefundable",
    "type": "function",
    "stateMutability": "view",
    "inputs": [{"name": "swapId", "type": "bytes32"}],
    "outputs": [{"name": "", "type": "bool"}]
  },
  {
    "name": "Funded",
    "type": "event",
    "inputs": [
      {"name": "swapId",     "type": "bytes32", "indexed": true},
      {"name": "secretHash", "type": "bytes32", "indexed": true},
      {"name": "funder",     "type": "address", "indexed": true},
      {"name": "recipient",  "type": "address", "indexed": false},
      {"name": "token",      "type": "address", "indexed": false},
      {"name": "amount",     "type": "uint256", "indexed": false},
      {"name": "timelock",   "type": "uint256", "indexed": false}
    ]
  },
  {
    "name": "Claimed",
    "type": "event",
    "inputs": [
      {"name": "swapId",    "type": "bytes32", "indexed": true},
      {"name": "secret",    "type": "bytes32", "indexed": false},
      {"name": "recipient", "type": "address", "indexed": true}
    ]
  },
  {
    "name": "Refunded",
    "type": "event",
    "inputs": [
      {"name": "swapId", "type": "bytes32", "indexed": true},
      {"name": "funder", "type": "address", "indexed": true}
    ]
  }
]""")

# ABI minimale ERC20 per approve
ERC20_ABI = json.loads("""[
  {"name": "approve",    "type": "function", "stateMutability": "nonpayable",
   "inputs": [{"name": "spender", "type": "address"}, {"name": "amount", "type": "uint256"}],
   "outputs": [{"name": "", "type": "bool"}]},
  {"name": "allowance",  "type": "function", "stateMutability": "view",
   "inputs": [{"name": "owner", "type": "address"}, {"name": "spender", "type": "address"}],
   "outputs": [{"name": "", "type": "uint256"}]},
  {"name": "balanceOf",  "type": "function", "stateMutability": "view",
   "inputs": [{"name": "account", "type": "address"}],
   "outputs": [{"name": "", "type": "uint256"}]},
  {"name": "decimals",   "type": "function", "stateMutability": "view",
   "inputs": [], "outputs": [{"name": "", "type": "uint8"}]},
  {"name": "symbol",     "type": "function", "stateMutability": "view",
   "inputs": [], "outputs": [{"name": "", "type": "string"}]}
]""")

# Token noti su Sepolia testnet
KNOWN_TOKENS = {
    "sepolia": {
        "USDC": "0x1c7D4B196Cb0C7B01d743Fbc6116a902379C7238",  # Circle USDC Sepolia
        "DAI":  "0x68194a729C2450ad26072b3D33ADaCbcef39D574",  # DAI Sepolia
    }
}

STATE_NAMES = {0: "EMPTY", 1: "FUNDED", 2: "CLAIMED", 3: "REFUNDED"}


class EVMBridge:
    """
    Bridge verso HTLCSwap.sol su qualsiasi rete EVM.
    Accetta RPC pubblico — nessun nodo proprio necessario.
    """

    def __init__(self, rpc_url: str, contract_address: Optional[str] = None):
        self.w3 = Web3(Web3.HTTPProvider(rpc_url))
        # middleware per reti PoA (Sepolia, BSC, Polygon...)
        self.w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)

        if not self.w3.is_connected():
            raise ConnectionError(f"Impossibile connettersi a {rpc_url}")

        self.contract_address = contract_address
        self.contract = None
        if contract_address:
            self.contract = self.w3.eth.contract(
                address=Web3.to_checksum_address(contract_address),
                abi=HTLC_ABI
            )

        self.chain_id = self.w3.eth.chain_id

    def set_contract(self, address: str):
        self.contract_address = address
        self.contract = self.w3.eth.contract(
            address=Web3.to_checksum_address(address),
            abi=HTLC_ABI
        )

    # ── helpers ──────────────────────────────────────────────────

    def secret_to_bytes32(self, secret_hex: str) -> bytes:
        """Converte secret hex string in bytes32."""
        return bytes.fromhex(secret_hex.zfill(64))

    def secret_hash_bytes32(self, secret_hex: str) -> bytes:
        """Calcola sha256(secret) come bytes32 — compatibile con Solidity."""
        secret_bytes = bytes.fromhex(secret_hex.zfill(64))
        return hashlib.sha256(secret_bytes).digest()

    def swap_id_bytes32(self, swap_id: str) -> bytes:
        """Converte swap_id string in bytes32."""
        return bytes.fromhex(swap_id.zfill(64))

    def get_gas_price(self) -> int:
        try:
            return self.w3.eth.gas_price
        except Exception:
            return Web3.to_wei(20, "gwei")

    # ── read ─────────────────────────────────────────────────────

    def get_swap_onchain(self, swap_id: str) -> Optional[dict]:
        """Legge stato dello swap direttamente dalla chain."""
        if not self.contract:
            raise RuntimeError("Contract non impostato")
        try:
            sid = self.swap_id_bytes32(swap_id)
            s = self.contract.functions.getSwap(sid).call()
            return {
                "secretHash": s[0].hex(),
                "timelock":   s[1],
                "funder":     s[2],
                "recipient":  s[3],
                "token":      s[4],
                "amount":     s[5],
                "state":      STATE_NAMES.get(s[6], "UNKNOWN"),
                "secret":     s[7].hex() if s[7] != b'\x00'*32 else None,
                "fundedAt":   s[8],
                "claimedAt":  s[9],
            }
        except Exception as e:
            return {"error": str(e)}

    def get_token_info(self, token_address: str, wallet: str) -> dict:
        """Restituisce balance e decimali di un token ERC20."""
        token = self.w3.eth.contract(
            address=Web3.to_checksum_address(token_address),
            abi=ERC20_ABI
        )
        decimals = token.functions.decimals().call()
        symbol   = token.functions.symbol().call()
        balance  = token.functions.balanceOf(Web3.to_checksum_address(wallet)).call()
        return {
            "symbol":   symbol,
            "decimals": decimals,
            "balance_raw": balance,
            "balance": balance / (10 ** decimals),
        }

    def is_claimable(self, swap_id: str) -> bool:
        if not self.contract:
            return False
        sid = self.swap_id_bytes32(swap_id)
        return self.contract.functions.isClaimable(sid).call()

    def is_refundable(self, swap_id: str) -> bool:
        if not self.contract:
            return False
        sid = self.swap_id_bytes32(swap_id)
        return self.contract.functions.isRefundable(sid).call()

    # ── write — richiedono private key ───────────────────────────

    def _sign_and_send(self, tx: dict, private_key: str) -> str:
        """Firma e invia una transazione, restituisce tx hash."""
        account = self.w3.eth.account.from_key(private_key)
        tx["from"]     = account.address
        tx["nonce"]    = self.w3.eth.get_transaction_count(account.address)
        tx["chainId"]  = self.chain_id
        tx["gasPrice"] = self.get_gas_price()

        if "gas" not in tx:
            tx["gas"] = self.w3.eth.estimate_gas(tx)

        signed = self.w3.eth.account.sign_transaction(tx, private_key)
        tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
        return tx_hash.hex()

    def approve_token(
        self, token_address: str, amount_raw: int, private_key: str
    ) -> str:
        """Approva il contratto HTLC a spendere token ERC20."""
        token = self.w3.eth.contract(
            address=Web3.to_checksum_address(token_address),
            abi=ERC20_ABI
        )
        tx = token.functions.approve(
            self.contract_address, amount_raw
        ).build_transaction({"gas": 100000})
        return self._sign_and_send(tx, private_key)

    def fund_token(
        self,
        swap_id: str,
        secret_hash_hex: str,
        timelock: int,
        recipient: str,
        token_address: str,
        amount_raw: int,
        private_key: str,
    ) -> str:
        """Deposita token ERC20 nel contratto HTLC."""
        sid  = self.swap_id_bytes32(swap_id)
        sh   = bytes.fromhex(secret_hash_hex)
        tx = self.contract.functions.fund(
            sid, sh, timelock,
            Web3.to_checksum_address(recipient),
            Web3.to_checksum_address(token_address),
            amount_raw
        ).build_transaction({"gas": 200000})
        return self._sign_and_send(tx, private_key)

    def fund_eth(
        self,
        swap_id: str,
        secret_hash_hex: str,
        timelock: int,
        recipient: str,
        amount_wei: int,
        private_key: str,
    ) -> str:
        """Deposita ETH nativo nel contratto HTLC."""
        sid = self.swap_id_bytes32(swap_id)
        sh  = bytes.fromhex(secret_hash_hex)
        tx = self.contract.functions.fundETH(
            sid, sh, timelock,
            Web3.to_checksum_address(recipient)
        ).build_transaction({"value": amount_wei, "gas": 150000})
        return self._sign_and_send(tx, private_key)

    def claim(self, swap_id: str, secret_hex: str, private_key: str) -> str:
        """Esegue il claim rivelando il secret on-chain."""
        sid    = self.swap_id_bytes32(swap_id)
        secret = self.secret_to_bytes32(secret_hex)
        tx = self.contract.functions.claim(
            sid, secret
        ).build_transaction({"gas": 150000})
        return self._sign_and_send(tx, private_key)

    def refund(self, swap_id: str, private_key: str) -> str:
        """Esegue il refund dopo la scadenza del timelock."""
        sid = self.swap_id_bytes32(swap_id)
        tx = self.contract.functions.refund(
            sid
        ).build_transaction({"gas": 100000})
        return self._sign_and_send(tx, private_key)

    def wait_for_receipt(self, tx_hash: str, timeout: int = 120) -> dict:
        """Aspetta la conferma di una transazione."""
        start = time.time()
        while time.time() - start < timeout:
            try:
                receipt = self.w3.eth.get_transaction_receipt(tx_hash)
                if receipt:
                    return {
                        "status":      receipt["status"],  # 1=ok, 0=revert
                        "blockNumber": receipt["blockNumber"],
                        "gasUsed":     receipt["gasUsed"],
                        "tx_hash":     tx_hash,
                    }
            except Exception:
                pass
            time.sleep(3)
        return {"error": "timeout", "tx_hash": tx_hash}

    # ── info ─────────────────────────────────────────────────────

    def connection_info(self) -> dict:
        return {
            "connected":   self.w3.is_connected(),
            "chain_id":    self.chain_id,
            "block":       self.w3.eth.block_number,
            "contract":    self.contract_address,
        }
