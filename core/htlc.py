"""
AtomicSwap - HTLC Engine
Hashed Timelock Contract implementation for BTC <-> USDT swaps.
No external dependencies.
"""

import hashlib
import os
import time
import json
from enum import Enum
from dataclasses import dataclass, field, asdict
from typing import Optional


class SwapState(Enum):
    PENDING    = "PENDING"     # creato, in attesa depositi
    FUNDED_A   = "FUNDED_A"   # party A ha depositato
    FUNDED_B   = "FUNDED_B"   # party B ha depositato
    ACTIVE     = "ACTIVE"      # entrambi depositato, swap attivo
    CLAIMED    = "CLAIMED"     # completato con successo
    REFUNDED   = "REFUNDED"   # scaduto, fondi restituiti
    EXPIRED    = "EXPIRED"     # timelock scaduto prima del claim


class AssetType(Enum):
    BTC  = "BTC"
    USDT = "USDT"


@dataclass
class Party:
    name:    str
    address: str
    asset:   AssetType
    amount:  float
    funded:  bool = False
    claimed: bool = False


@dataclass
class HTLC:
    swap_id:     str
    secret_hash: str                          # sha256(secret) — pubblico
    timelock:    int                          # unix timestamp scadenza
    party_a:     Party                        # iniziatore (BTC)
    party_b:     Party                        # controparte (USDT)
    state:       SwapState = SwapState.PENDING
    created_at:  int       = field(default_factory=lambda: int(time.time()))
    secret:      Optional[str] = None         # rivelato solo al claim
    claimed_at:  Optional[int] = None
    refunded_at: Optional[int] = None

    # ── validazione ──────────────────────────────────────────────

    def is_expired(self) -> bool:
        return int(time.time()) >= self.timelock

    def time_remaining(self) -> int:
        remaining = self.timelock - int(time.time())
        return max(0, remaining)

    def verify_secret(self, secret: str) -> bool:
        h = hashlib.sha256(secret.encode()).hexdigest()
        return h == self.secret_hash

    # ── azioni ───────────────────────────────────────────────────

    def deposit(self, party_name: str) -> tuple[bool, str]:
        if self.is_expired():
            self.state = SwapState.EXPIRED
            return False, "Timelock scaduto — swap annullato"

        if party_name == self.party_a.name:
            if self.party_a.funded:
                return False, f"{party_name} ha già depositato"
            self.party_a.funded = True
            if self.party_b.funded:
                self.state = SwapState.ACTIVE
            else:
                self.state = SwapState.FUNDED_A
            return True, f"{party_name} ha depositato {self.party_a.amount} {self.party_a.asset.value}"

        elif party_name == self.party_b.name:
            if self.party_b.funded:
                return False, f"{party_name} ha già depositato"
            self.party_b.funded = True
            if self.party_a.funded:
                self.state = SwapState.ACTIVE
            else:
                self.state = SwapState.FUNDED_B
            return True, f"{party_name} ha depositato {self.party_b.amount} {self.party_b.asset.value}"

        return False, "Party sconosciuto"

    def claim(self, secret: str) -> tuple[bool, str]:
        if self.state != SwapState.ACTIVE:
            return False, f"Swap non attivo (stato: {self.state.value})"

        if self.is_expired():
            self.state = SwapState.EXPIRED
            return False, "Timelock scaduto — claim non possibile"

        if not self.verify_secret(secret):
            return False, "Secret non valido — claim rifiutato"

        self.secret     = secret
        self.state      = SwapState.CLAIMED
        self.claimed_at = int(time.time())
        self.party_a.claimed = True
        self.party_b.claimed = True

        return True, (
            f"Swap completato!\n"
            f"  {self.party_a.name} riceve {self.party_b.amount} {self.party_b.asset.value}\n"
            f"  {self.party_b.name} riceve {self.party_a.amount} {self.party_a.asset.value}"
        )

    def refund(self) -> tuple[bool, str]:
        if self.state in (SwapState.CLAIMED, SwapState.REFUNDED):
            return False, f"Swap già in stato {self.state.value}"

        if not self.is_expired():
            remaining = self.time_remaining()
            return False, f"Timelock non ancora scaduto — rimangono {remaining}s"

        self.state       = SwapState.REFUNDED
        self.refunded_at = int(time.time())

        msgs = []
        if self.party_a.funded:
            msgs.append(f"  {self.party_a.name}: refund {self.party_a.amount} {self.party_a.asset.value}")
        if self.party_b.funded:
            msgs.append(f"  {self.party_b.name}: refund {self.party_b.amount} {self.party_b.asset.value}")
        if not msgs:
            msgs.append("  Nessun fondo da restituire")

        return True, "Refund eseguito:\n" + "\n".join(msgs)

    # ── serializzazione ──────────────────────────────────────────

    def to_dict(self) -> dict:
        d = asdict(self)
        d["state"]        = self.state.value
        d["party_a"]["asset"] = self.party_a.asset.value
        d["party_b"]["asset"] = self.party_b.asset.value
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)
