"""
SwapFactory — crea e gestisce istanze HTLC.
Gestisce storage in-memory e persistenza su file JSON.
"""

import hashlib
import os
import secrets
import time
import json
from typing import Optional
from .htlc import HTLC, Party, SwapState, AssetType

# default timelock: 24 ore
DEFAULT_TIMELOCK_SECONDS = 86400


class SwapFactory:

    def __init__(self, store_path: str = "swaps.json"):
        self.store_path = store_path
        self._swaps: dict[str, HTLC] = {}
        self._load()

    # ── creazione ────────────────────────────────────────────────

    def create_swap(
        self,
        initiator_name:    str,
        initiator_address: str,
        btc_amount:        float,
        counterparty_name:    str,
        counterparty_address: str,
        usdt_amount:          float,
        timelock_seconds:     int = DEFAULT_TIMELOCK_SECONDS,
    ) -> tuple[HTLC, str]:
        """
        Crea un nuovo swap BTC <-> USDT.
        Restituisce (htlc, secret_plaintext).
        Il secret NON va mai condiviso finché il claim non è pronto.
        """
        # genera secret casuale
        secret_plain = secrets.token_hex(32)
        secret_hash  = hashlib.sha256(secret_plain.encode()).hexdigest()

        swap_id  = secrets.token_hex(8)
        timelock = int(time.time()) + timelock_seconds

        party_a = Party(
            name    = initiator_name,
            address = initiator_address,
            asset   = AssetType.BTC,
            amount  = btc_amount,
        )
        party_b = Party(
            name    = counterparty_name,
            address = counterparty_address,
            asset   = AssetType.USDT,
            amount  = usdt_amount,
        )

        htlc = HTLC(
            swap_id     = swap_id,
            secret_hash = secret_hash,
            timelock    = timelock,
            party_a     = party_a,
            party_b     = party_b,
        )

        self._swaps[swap_id] = htlc
        self._save()

        return htlc, secret_plain

    # ── lookup ───────────────────────────────────────────────────

    def get(self, swap_id: str) -> Optional[HTLC]:
        return self._swaps.get(swap_id)

    def list_all(self) -> list[HTLC]:
        return list(self._swaps.values())

    def list_by_state(self, state: SwapState) -> list[HTLC]:
        return [s for s in self._swaps.values() if s.state == state]

    # ── persistenza ──────────────────────────────────────────────

    def save_swap(self, htlc: HTLC):
        self._swaps[htlc.swap_id] = htlc
        self._save()

    def _save(self):
        data = {sid: htlc.to_dict() for sid, htlc in self._swaps.items()}
        with open(self.store_path, "w") as f:
            json.dump(data, f, indent=2)

    def _load(self):
        if not os.path.exists(self.store_path):
            return
        try:
            with open(self.store_path) as f:
                data = json.load(f)
            for sid, d in data.items():
                htlc = self._dict_to_htlc(d)
                self._swaps[sid] = htlc
        except Exception:
            pass  # file corrotto o vuoto, si riparte da zero

    @staticmethod
    def _dict_to_htlc(d: dict) -> HTLC:
        pa = d["party_a"]
        pb = d["party_b"]
        return HTLC(
            swap_id     = d["swap_id"],
            secret_hash = d["secret_hash"],
            timelock    = d["timelock"],
            party_a     = Party(
                name    = pa["name"],
                address = pa["address"],
                asset   = AssetType(pa["asset"]),
                amount  = pa["amount"],
                funded  = pa["funded"],
                claimed = pa["claimed"],
            ),
            party_b     = Party(
                name    = pb["name"],
                address = pb["address"],
                asset   = AssetType(pb["asset"]),
                amount  = pb["amount"],
                funded  = pb["funded"],
                claimed = pb["claimed"],
            ),
            state       = SwapState(d["state"]),
            created_at  = d["created_at"],
            secret      = d.get("secret"),
            claimed_at  = d.get("claimed_at"),
            refunded_at = d.get("refunded_at"),
        )
