"""
Bitcoin Bridge — HTLC via P2SH script + Mempool.space API
Nessun nodo Bitcoin necessario. Funziona con qualsiasi wallet BTC
(Electrum, hardware wallet, ecc.) che supporti invio a indirizzo P2SH.

Flusso:
  1. Genera script HTLC P2SH → indirizzo BTC a cui Alice invia
  2. Alice invia BTC a quell'indirizzo dal suo wallet (Electrum, ecc.)
  3. Monitor conferme via Mempool.space API
  4. Reveal secret on-chain via spending transaction
"""

import hashlib
import hmac
import struct
import time
import json
import urllib.request
import urllib.error
from typing import Optional


# ── Bitcoin Script opcodes ────────────────────────────────────────────────────

OP_IF          = b'\x63'
OP_ELSE        = b'\x67'
OP_ENDIF       = b'\x68'
OP_SHA256      = b'\xa8'
OP_EQUALVERIFY = b'\x88'
OP_DUP         = b'\x76'
OP_HASH160     = b'\xa9'
OP_CHECKSIG    = b'\xac'
OP_CHECKLOCKTIMEVERIFY = b'\xb1'
OP_DROP        = b'\x75'
OP_EQUAL       = b'\x87'

# ── Base58Check ──────────────────────────────────────────────────────────────

BASE58_ALPHABET = b'123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'

def _b58encode(data: bytes) -> str:
    count = 0
    for byte in data:
        if byte == 0:
            count += 1
        else:
            break
    num = int.from_bytes(data, "big")
    result = []
    while num > 0:
        num, rem = divmod(num, 58)
        result.append(BASE58_ALPHABET[rem:rem+1])
    result.extend([BASE58_ALPHABET[0:1]] * count)
    return b''.join(reversed(result)).decode("ascii")

def _hash160(data: bytes) -> bytes:
    sha = hashlib.sha256(data).digest()
    return hashlib.new("ripemd160", sha).digest()

def _double_sha256(data: bytes) -> bytes:
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()

def _checksum(data: bytes) -> bytes:
    return _double_sha256(data)[:4]

def p2sh_address(script_hash: bytes, testnet: bool = False) -> str:
    """Genera indirizzo P2SH da script hash."""
    version = b'\xc4' if testnet else b'\x05'
    payload = version + script_hash
    return _b58encode(payload + _checksum(payload))

def push_data(data: bytes) -> bytes:
    """Genera push opcode per dati arbitrari."""
    n = len(data)
    if n < 0x4c:
        return bytes([n]) + data
    elif n <= 0xff:
        return b'\x4c' + bytes([n]) + data
    else:
        return b'\x4d' + struct.pack('<H', n) + data

def encode_locktime(t: int) -> bytes:
    """Encode timelock per OP_CHECKLOCKTIMEVERIFY."""
    if t < 0x80:
        return bytes([t])
    elif t < 0x8000:
        return struct.pack('<H', t)
    elif t < 0x800000:
        return struct.pack('<I', t)[:3]
    else:
        return struct.pack('<I', t)


# ── HTLC Script ──────────────────────────────────────────────────────────────

def build_htlc_script(
    secret_hash:      bytes,   # sha256(secret) — 32 bytes
    recipient_pubkey_hash: bytes,  # hash160(Alice pubkey) — 20 bytes
    refund_pubkey_hash:    bytes,  # hash160(Bob pubkey)   — 20 bytes
    timelock:         int,    # unix timestamp
) -> bytes:
    """
    Costruisce script HTLC P2SH:

    IF
      OP_SHA256 <secretHash> OP_EQUALVERIFY
      OP_DUP OP_HASH160 <recipientPKH> OP_EQUALVERIFY OP_CHECKSIG
    ELSE
      <timelock> OP_CHECKLOCKTIMEVERIFY OP_DROP
      OP_DUP OP_HASH160 <refundPKH> OP_EQUALVERIFY OP_CHECKSIG
    ENDIF
    """
    tl_bytes = encode_locktime(timelock)

    script = (
        OP_IF
        + OP_SHA256
        + push_data(secret_hash)
        + OP_EQUALVERIFY
        + OP_DUP
        + OP_HASH160
        + push_data(recipient_pubkey_hash)
        + OP_EQUALVERIFY
        + OP_CHECKSIG
        + OP_ELSE
        + push_data(tl_bytes)
        + OP_CHECKLOCKTIMEVERIFY
        + OP_DROP
        + OP_DUP
        + OP_HASH160
        + push_data(refund_pubkey_hash)
        + OP_EQUALVERIFY
        + OP_CHECKSIG
        + OP_ENDIF
    )
    return script

def script_to_p2sh_address(script: bytes, testnet: bool = False) -> str:
    """Converte redeem script in indirizzo P2SH."""
    script_hash = _hash160(script)
    return p2sh_address(script_hash, testnet=testnet)


# ── Mempool.space API ────────────────────────────────────────────────────────

class MempoolAPI:
    """
    Wrapper per Mempool.space API — no API key, no nodo necessario.
    Funziona su mainnet e testnet.
    """

    def __init__(self, testnet: bool = False):
        base = "https://mempool.space"
        if testnet:
            base += "/testnet4"
        self.base = base + "/api"

    def _get(self, path: str) -> Optional[dict]:
        url = self.base + path
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "AtomicSwap/1.0"})
            with urllib.request.urlopen(req, timeout=10) as r:
                data = r.read()
                try:
                    return json.loads(data)
                except Exception:
                    return {"raw": data.decode()}
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            return {"error": str(e)}
        except Exception as e:
            return {"error": str(e)}

    def get_address_info(self, address: str) -> Optional[dict]:
        """Info su un indirizzo: balance, tx count."""
        return self._get(f"/address/{address}")

    def get_address_txs(self, address: str) -> Optional[list]:
        """Lista transazioni di un indirizzo."""
        result = self._get(f"/address/{address}/txs")
        if isinstance(result, list):
            return result
        return []

    def get_utxos(self, address: str) -> Optional[list]:
        """UTXO non spesi di un indirizzo."""
        result = self._get(f"/address/{address}/utxo")
        if isinstance(result, list):
            return result
        return []

    def get_tx(self, txid: str) -> Optional[dict]:
        """Dettagli di una transazione."""
        return self._get(f"/tx/{txid}")

    def get_fee_estimates(self) -> dict:
        """Fee estimates in sat/vB per 1, 3, 6 blocchi."""
        result = self._get("/v1/fees/recommended")
        return result or {}

    def get_block_height(self) -> int:
        """Blocco corrente."""
        result = self._get("/blocks/tip/height")
        if isinstance(result, dict) and "raw" in result:
            return int(result["raw"])
        return 0

    def broadcast_tx(self, raw_hex: str) -> Optional[str]:
        """Broadcast transazione raw, restituisce txid."""
        url = self.base + "/tx"
        try:
            data = raw_hex.encode()
            req = urllib.request.Request(
                url, data=data, method="POST",
                headers={"Content-Type": "text/plain", "User-Agent": "AtomicSwap/1.0"}
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.read().decode().strip()
        except Exception as e:
            return None


# ── Bitcoin HTLC Manager ─────────────────────────────────────────────────────

class BitcoinHTLC:
    """
    Gestisce il lato Bitcoin di uno swap atomico.
    Non custodisce chiavi — genera solo script e monitora.
    """

    def __init__(self, testnet: bool = True):
        self.testnet = testnet
        self.api     = MempoolAPI(testnet=testnet)

    def create_htlc_address(
        self,
        secret_hash:           str,   # hex string
        recipient_pubkey_hash: str,   # hex — hash160 del pubkey di chi riceve
        refund_pubkey_hash:    str,   # hex — hash160 del pubkey di chi manda
        timelock:              int,   # unix timestamp
    ) -> dict:
        """
        Genera lo script HTLC e l'indirizzo P2SH corrispondente.
        Alice manda BTC a questo indirizzo dal suo wallet.
        """
        script = build_htlc_script(
            secret_hash           = bytes.fromhex(secret_hash),
            recipient_pubkey_hash = bytes.fromhex(recipient_pubkey_hash),
            refund_pubkey_hash    = bytes.fromhex(refund_pubkey_hash),
            timelock              = timelock,
        )
        address = script_to_p2sh_address(script, testnet=self.testnet)

        return {
            "address":       address,
            "redeem_script": script.hex(),
            "script_hash":   _hash160(script).hex(),
            "testnet":       self.testnet,
            "timelock":      timelock,
        }

    def monitor_deposit(
        self,
        address:       str,
        expected_sats: int,
        timeout:       int = 3600,
        poll_interval: int = 15,
    ) -> dict:
        """
        Monitora un indirizzo P2SH finché non arriva il deposito atteso.
        Polling via Mempool.space API.
        """
        start    = time.time()
        deadline = start + timeout

        print(f"  Monitoraggio {address}")
        print(f"  Attendo {expected_sats} sats  (timeout {timeout}s)")

        while time.time() < deadline:
            utxos = self.api.get_utxos(address)

            if utxos:
                total = sum(u.get("value", 0) for u in utxos)
                confirmed = sum(
                    u.get("value", 0) for u in utxos
                    if u.get("status", {}).get("confirmed", False)
                )

                if confirmed >= expected_sats:
                    return {
                        "status":    "confirmed",
                        "total_sats": total,
                        "confirmed":  confirmed,
                        "utxos":      utxos,
                        "txids":      [u["txid"] for u in utxos],
                    }
                elif total >= expected_sats:
                    return {
                        "status":    "mempool",   # in attesa di conferma
                        "total_sats": total,
                        "confirmed":  confirmed,
                        "utxos":      utxos,
                        "txids":      [u["txid"] for u in utxos],
                    }

            remaining = int(deadline - time.time())
            print(f"  Nessun deposito ancora — ricontrollo in {poll_interval}s "
                  f"(rimangono {remaining}s)")
            time.sleep(poll_interval)

        return {"status": "timeout", "address": address}

    def check_deposit(self, address: str) -> dict:
        """Controlla una volta sola lo stato del deposito."""
        utxos = self.api.get_utxos(address)
        if not utxos:
            return {"status": "empty", "sats": 0}

        total     = sum(u.get("value", 0) for u in utxos)
        confirmed = sum(
            u.get("value", 0) for u in utxos
            if u.get("status", {}).get("confirmed", False)
        )
        return {
            "status":    "confirmed" if confirmed > 0 else "mempool",
            "sats":      total,
            "confirmed": confirmed,
            "txids":     [u["txid"] for u in utxos],
        }

    def get_fee_rate(self) -> int:
        """Fee rate consigliato in sat/vB per conferma in ~3 blocchi."""
        fees = self.api.get_fee_estimates()
        return fees.get("halfHourFee", 10)

    def network_info(self) -> dict:
        return {
            "testnet":      self.testnet,
            "block_height": self.api.get_block_height(),
            "fees":         self.api.get_fee_estimates(),
        }
