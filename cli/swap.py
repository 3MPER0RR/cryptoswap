#!/usr/bin/env python3
"""
CLI — BTC <-> USDT/USDC HTLC
Real on-chain swaps: Bitcoin Testnet + Sepolia EVM
Zero wallet proprietario — funziona con Electrum, Metamask, qualsiasi wallet.
"""
import sys, os, time, json, hashlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.htlc    import SwapState
from core.factory import SwapFactory
import config

# ── ANSI ─────────────────────────────────────────────────────────────────────
R="\033[0m"; BOLD="\033[1m"; DIM="\033[2m"
RED="\033[91m"; GREEN="\033[92m"; YELLOW="\033[93m"; CYAN="\033[96m"; WHITE="\033[97m"

def c(col, t): return f"{col}{t}{R}"
def ok(m):   print(c(GREEN,  f"  ✓ {m}"))
def err(m):  print(c(RED,    f"  ✗ {m}"))
def info(m): print(c(CYAN,   f"  ℹ {m}"))
def warn(m): print(c(YELLOW, f"  ⚠ {m}"))
def hr():    print(c(DIM, "  " + "─"*50))
def prompt(t): return input(c(YELLOW, f"  ▶ {t}: ")).strip()

def banner():
    print(c(CYAN, r"""
  ╔════════════════════════════════════════════════════╗
  ║           BTC ↔ USDT/USDC                          ║
  ║   Bitcoin Testnet  +  Sepolia EVM  |  trustless    ║
  ╚════════════════════════════════════════════════════╝
"""))

def fmt_time(ts): return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))

STATE_COL = {
    SwapState.PENDING: YELLOW, SwapState.FUNDED_A: CYAN,
    SwapState.FUNDED_B: CYAN,  SwapState.ACTIVE: GREEN,
    SwapState.CLAIMED: GREEN,  SwapState.REFUNDED: DIM,
    SwapState.EXPIRED: RED,
}

def fmt_state(s):
    return c(STATE_COL.get(s, WHITE)+BOLD, f"[{s.value}]")

def show_swap(htlc, secret=None):
    hr()
    print(c(BOLD+WHITE, "  Swap ID  : ") + c(CYAN, htlc.swap_id))
    print(c(BOLD+WHITE, "  Stato    : ") + fmt_state(htlc.state))
    print(c(BOLD+WHITE, "  Scadenza : ") + fmt_time(htlc.timelock))
    remaining = htlc.time_remaining()
    if remaining > 0:
        h,r=divmod(remaining,3600); m,s=divmod(r,60)
        col = RED if remaining<300 else (YELLOW if remaining<3600 else GREEN)
        print(c(BOLD+WHITE, "  Rimane   : ") + c(col, f"{h:02d}h {m:02d}m {s:02d}s"))
    hr()
    fa = c(GREEN,"✓ FUNDED") if htlc.party_a.funded else c(DIM,"○ in attesa")
    fb = c(GREEN,"✓ FUNDED") if htlc.party_b.funded else c(DIM,"○ in attesa")
    print(c(BOLD, f"  [BTC]  {htlc.party_a.name}"))
    print(f"    amount  : {c(YELLOW, str(htlc.party_a.amount))} BTC")
    print(f"    wallet  : {c(DIM, htlc.party_a.address)}")
    print(f"    stato   : {fa}")
    print()
    print(c(BOLD, f"  [USDT] {htlc.party_b.name}"))
    print(f"    amount  : {c(YELLOW, str(htlc.party_b.amount))} USDT/USDC")
    print(f"    wallet  : {c(DIM, htlc.party_b.address)}")
    print(f"    stato   : {fb}")
    hr()
    print(c(BOLD, "  Hashlock  : ") + c(DIM, htlc.secret_hash[:40]+"..."))
    if secret:
        print(c(BOLD+RED, "  Secret    : ") + c(RED+BOLD, secret))
    if htlc.claimed_at:
        print(c(GREEN, f"  Claimed   : {fmt_time(htlc.claimed_at)}"))
    # campi extra (btc_address, evm_tx, ecc.)
    extra = getattr(htlc, '_extra', {})
    if extra.get("btc_htlc_address"):
        print(c(BOLD+YELLOW, "  BTC HTLC  : ") + c(YELLOW, extra["btc_htlc_address"]))
    if extra.get("evm_fund_tx"):
        print(c(BOLD+CYAN, "  EVM TX    : ") + c(CYAN, extra["evm_fund_tx"]))
    hr()

# ── lazy imports chain ────────────────────────────────────────────────────────

def _evm_bridge(network="sepolia"):
    from chain.evm.bridge import EVMBridge
    rpc = config.get_evm_rpc(network)
    contract = config.get_htlc_contract(network)
    info(f"Connessione a {network} ({rpc})")
    b = EVMBridge(rpc_url=rpc, contract_address=contract or None)
    ci = b.connection_info()
    ok(f"Connesso — block #{ci['block']}  chain_id={ci['chain_id']}")
    if not contract:
        warn("Contratto HTLC non configurato. Imposta HTLC_CONTRACT_SEPOLIA o aggiorna config.py")
    return b

def _btc_bridge(testnet=True):
    from chain.btc.bridge import BitcoinHTLC
    b = BitcoinHTLC(testnet=testnet)
    ni = b.network_info()
    ok(f"Bitcoin {'testnet' if testnet else 'mainnet'} — block #{ni['block_height']}")
    return b

# ── actions ───────────────────────────────────────────────────────────────────

def action_new(factory):
    print(c(BOLD+CYAN, "\n  ── Nuovo Swap BTC ↔ USDT/USDC ──\n"))
    info("Inserisci i dati dello swap. Nessun wallet richiesto ora.")
    print()

    # Party A — BTC
    name_a   = prompt("Il tuo nome (Party A — manda BTC)")
    addr_a   = prompt("Il tuo indirizzo BTC (Electrum o altro)")
    btc_amt  = float(prompt("Quantità BTC da inviare"))

    print()
    # Party B — USDT/USDC
    name_b   = prompt("Nome controparte (Party B — manda USDT/USDC)")
    addr_b   = prompt("Indirizzo EVM controparte (0x...)")
    usdt_amt = float(prompt("Quantità USDT/USDC equivalente"))

    print()
    info("Timelock default 24h. Cambia? (invio = default)")
    tl = prompt("Ore di timelock (default 24)")
    timelock_s = int(float(tl)*3600) if tl else config.DEFAULT_TIMELOCK

    network = prompt("Rete EVM [sepolia/mainnet] (default sepolia)") or "sepolia"
    btc_net = (prompt("BTC network [testnet/mainnet] (default testnet)") or "testnet") != "mainnet"

    htlc, secret = factory.create_swap(
        initiator_name=name_a, initiator_address=addr_a, btc_amount=btc_amt,
        counterparty_name=name_b, counterparty_address=addr_b, usdt_amount=usdt_amt,
        timelock_seconds=timelock_s,
    )

    # Genera indirizzo P2SH HTLC Bitcoin (serve pubkey hash)
    print()
    info("Per generare l'indirizzo BTC HTLC servono i pubkey hash (HASH160).")
    info("Puoi ottenerli da Electrum: Console → bitcoin.pubkey_hash(address)")
    pkh_a = prompt("HASH160 del tuo pubkey BTC (hex, 40 chars) — o invio per skip")
    pkh_b = prompt("HASH160 del pubkey BTC della controparte (hex, 40 chars) — o invio per skip")

    btc_htlc_address = None
    redeem_script    = None

    if pkh_a and pkh_b and len(pkh_a)==40 and len(pkh_b)==40:
        try:
            btc = _btc_bridge(testnet=btc_net)
            result = btc.create_htlc_address(
                secret_hash           = htlc.secret_hash,
                recipient_pubkey_hash = pkh_b,   # Bob riceve i BTC
                refund_pubkey_hash    = pkh_a,   # Alice può fare refund
                timelock              = htlc.timelock,
            )
            btc_htlc_address = result["address"]
            redeem_script    = result["redeem_script"]
        except Exception as e:
            warn(f"Errore generazione indirizzo BTC: {e}")
    else:
        info("Skip generazione indirizzo BTC — puoi farlo dopo con il comando [B]")

    print()
    ok("Swap creato!")
    show_swap(htlc)

    print(c(RED+BOLD, """
  ╔═════════════════════════════════════════════════╗
  ║  SALVA QUESTI DATI — non vengono memorizzati   ║
  ╚═════════════════════════════════════════════════╝
"""))
    print(c(BOLD,"  Swap ID : ") + c(CYAN+BOLD, htlc.swap_id))
    print(c(BOLD,"  Secret  : ") + c(RED+BOLD, secret))
    print(c(DIM,  "  (rivela il secret SOLO dopo che la controparte ha depositato)\n"))

    if btc_htlc_address:
        print(c(BOLD+YELLOW, "\n  ── Indirizzo BTC per il deposito ──"))
        print(c(BOLD,"  Indirizzo HTLC : ") + c(YELLOW+BOLD, btc_htlc_address))
        print(c(DIM,  "  Invia BTC a questo indirizzo dal tuo wallet Electrum"))
        print(c(BOLD,"  Redeem Script  : ") + c(DIM, redeem_script[:60]+"..."))
        print(c(DIM,  "  Conserva il redeem script — serve per il claim/refund\n"))

    # salva dati extra nel JSON
    _save_extra(factory, htlc.swap_id, {
        "btc_htlc_address": btc_htlc_address,
        "btc_redeem_script": redeem_script,
        "evm_network": network,
        "btc_testnet": btc_net,
    })


def action_btc_address(factory):
    """Genera/mostra indirizzo BTC HTLC per uno swap esistente."""
    swap_id = prompt("Swap ID")
    htlc = factory.get(swap_id)
    if not htlc:
        err("Swap non trovato"); return

    pkh_a = prompt("HASH160 pubkey BTC Party A (hex 40 chars)")
    pkh_b = prompt("HASH160 pubkey BTC Party B (hex 40 chars)")
    btc_net = (prompt("BTC network [testnet/mainnet]") or "testnet") != "mainnet"

    try:
        btc = _btc_bridge(testnet=btc_net)
        result = btc.create_htlc_address(
            secret_hash           = htlc.secret_hash,
            recipient_pubkey_hash = pkh_b,
            refund_pubkey_hash    = pkh_a,
            timelock              = htlc.timelock,
        )
        print()
        ok("Indirizzo HTLC generato")
        print(c(BOLD+YELLOW,"  Indirizzo  : ") + c(YELLOW+BOLD, result["address"]))
        print(c(BOLD,       "  Script     : ") + c(DIM, result["redeem_script"][:60]+"..."))
        print()
        info(f"Invia {htlc.party_a.amount} BTC a questo indirizzo dal tuo wallet")
        _save_extra(factory, swap_id, {
            "btc_htlc_address":  result["address"],
            "btc_redeem_script": result["redeem_script"],
            "btc_testnet":       btc_net,
        })
    except Exception as e:
        err(f"Errore: {e}")


def action_check_btc(factory):
    """Controlla stato deposito BTC su Mempool.space."""
    swap_id = prompt("Swap ID")
    htlc    = factory.get(swap_id)
    if not htlc: err("Swap non trovato"); return

    extra   = _load_extra(swap_id)
    address = extra.get("btc_htlc_address") or prompt("Indirizzo BTC HTLC")
    testnet = extra.get("btc_testnet", True)

    try:
        btc = _btc_bridge(testnet=testnet)
        res = btc.check_deposit(address)
        print()
        if res["status"] == "empty":
            warn(f"Nessun deposito su {address}")
        elif res["status"] == "mempool":
            warn(f"In mempool: {res['sats']} sats — in attesa di conferma")
            if res.get("txids"):
                info(f"TxID: {res['txids'][0]}")
        else:
            ok(f"Deposito confermato: {res['confirmed']} sats")
            if res.get("txids"):
                info(f"TxID: {res['txids'][0]}")
                net = "testnet/" if testnet else ""
                info(f"Explorer: https://mempool.space/{net}tx/{res['txids'][0]}")

            # aggiorna stato locale
            ok_dep, msg = htlc.deposit(htlc.party_a.name)
            if ok_dep:
                factory.save_swap(htlc)
                ok(f"Stato aggiornato: {htlc.state.value}")
    except Exception as e:
        err(f"Errore: {e}")


def action_fund_evm(factory):
    """Bob deposita USDT/USDC sul contratto HTLC EVM."""
    swap_id = prompt("Swap ID")
    htlc    = factory.get(swap_id)
    if not htlc: err("Swap non trovato"); return

    extra   = _load_extra(swap_id)
    network = extra.get("evm_network", "sepolia")

    print()
    info("Inserisci la chiave privata EVM di Party B (non viene salvata)")
    warn("Usa un wallet testnet — mai la chiave privata mainnet in chiaro")
    privkey = prompt("Private key EVM (0x...)")
    if not privkey:
        err("Chiave privata richiesta"); return

    token_sym = prompt("Token da inviare [USDC/DAI] (default USDC)") or "USDC"
    token_addr = config.get_token_address(token_sym, network)
    if not token_addr:
        token_addr = prompt(f"Indirizzo contratto {token_sym}")

    try:
        bridge  = _evm_bridge(network)
        if not bridge.contract_address:
            err("Contratto HTLC non configurato. Imposta HTLC_CONTRACT_SEPOLIA")
            info("Dopo il deploy del contratto, aggiorna config.py o esporta la variabile")
            return

        # calcola amount in unità token (USDC ha 6 decimali)
        token_info = bridge.get_token_info(token_addr, bridge.w3.eth.account.from_key(privkey).address)
        decimals   = token_info["decimals"]
        amount_raw = int(htlc.party_b.amount * (10 ** decimals))

        ok(f"Token: {token_info['symbol']}  Balance: {token_info['balance']:.4f}")
        ok(f"Importo da depositare: {htlc.party_b.amount} {token_sym} ({amount_raw} raw)")

        # 1. Approve
        info("Step 1/2 — Approve token spending...")
        tx_approve = bridge.approve_token(token_addr, amount_raw, privkey)
        ok(f"Approve TX: {tx_approve}")
        info("Attendo conferma approve...")
        receipt = bridge.wait_for_receipt(tx_approve)
        if receipt.get("status") != 1:
            err("Approve fallita"); return
        ok(f"Approve confermata al blocco #{receipt['blockNumber']}")

        # 2. Fund
        info("Step 2/2 — Fund contratto HTLC...")
        sid_hex = htlc.swap_id
        tx_fund = bridge.fund_token(
            swap_id         = sid_hex,
            secret_hash_hex = htlc.secret_hash,
            timelock        = htlc.timelock,
            recipient       = htlc.party_a.address,  # Alice fa claim
            token_address   = token_addr,
            amount_raw      = amount_raw,
            private_key     = privkey,
        )
        ok(f"Fund TX: {tx_fund}")
        info("Attendo conferma fund...")
        receipt2 = bridge.wait_for_receipt(tx_fund)
        if receipt2.get("status") != 1:
            err("Fund fallita"); return
        ok(f"Fund confermata al blocco #{receipt2['blockNumber']}")

        # aggiorna stato locale
        ok_dep, msg = htlc.deposit(htlc.party_b.name)
        if ok_dep:
            factory.save_swap(htlc)
            ok(f"Stato locale aggiornato: {htlc.state.value}")

        _save_extra(factory, htlc.swap_id, {"evm_fund_tx": tx_fund, **extra})
        info(f"Explorer: https://sepolia.etherscan.io/tx/{tx_fund}")

        if htlc.state == SwapState.ACTIVE:
            print(c(GREEN+BOLD, "\n  ✓ ENTRAMBI I FONDI SUL TAVOLO — SWAP ATTIVO!\n"))
            info("Party A può ora fare il claim rivelando il secret")

    except Exception as e:
        err(f"Errore EVM: {e}")


def action_claim_evm(factory):
    """Alice rivela il secret e fa claim dei token EVM."""
    swap_id = prompt("Swap ID")
    htlc    = factory.get(swap_id)
    if not htlc: err("Swap non trovato"); return

    secret  = prompt("Secret (hex — quello generato alla creazione)")
    if not htlc.verify_secret(secret):
        err("Secret non valido"); return

    extra   = _load_extra(swap_id)
    network = extra.get("evm_network", "sepolia")

    warn("Inserisci la chiave privata di Party A (Alice) per firmare il claim EVM")
    privkey = prompt("Private key EVM di Alice (0x...)")

    try:
        bridge  = _evm_bridge(network)
        info("Esecuzione claim on-chain...")
        tx_claim = bridge.claim(htlc.swap_id, secret, privkey)
        ok(f"Claim TX: {tx_claim}")
        receipt  = bridge.wait_for_receipt(tx_claim)
        if receipt.get("status") != 1:
            err("Claim fallita on-chain"); return

        ok(f"Claim confermata al blocco #{receipt['blockNumber']}")
        info(f"Explorer: https://sepolia.etherscan.io/tx/{tx_claim}")

        # aggiorna stato locale
        ok_c, msg = htlc.claim(secret)
        if ok_c:
            factory.save_swap(htlc)
            print()
            ok("Swap completato!")
            ok(f"Alice riceve i token EVM")
            ok(f"Il secret è ora pubblico on-chain — Bob può clamare i BTC")
            print(c(BOLD+YELLOW, f"\n  Secret pubblico: {secret}\n"))

    except Exception as e:
        err(f"Errore claim: {e}")


def action_refund_evm(factory):
    """Bob fa refund dei token EVM dopo scadenza timelock."""
    swap_id = prompt("Swap ID")
    htlc    = factory.get(swap_id)
    if not htlc: err("Swap non trovato"); return

    if not htlc.is_expired():
        remaining = htlc.time_remaining()
        h,r=divmod(remaining,3600); m,s=divmod(r,60)
        err(f"Timelock non scaduto — rimangono {h:02d}h {m:02d}m {s:02d}s"); return

    extra   = _load_extra(swap_id)
    network = extra.get("evm_network", "sepolia")
    warn("Inserisci la chiave privata di chi ha depositato su EVM")
    privkey = prompt("Private key EVM (0x...)")

    try:
        bridge   = _evm_bridge(network)
        tx_ref   = bridge.refund(htlc.swap_id, privkey)
        ok(f"Refund TX: {tx_ref}")
        receipt  = bridge.wait_for_receipt(tx_ref)
        if receipt.get("status") == 1:
            ok(f"Refund confermato al blocco #{receipt['blockNumber']}")
            htlc.refund()
            factory.save_swap(htlc)
        else:
            err("Refund fallita on-chain")
    except Exception as e:
        err(f"Errore refund: {e}")


def action_status(factory):
    swap_id = prompt("Swap ID (invio = tutti)")
    if not swap_id:
        swaps = factory.list_all()
        if not swaps: warn("Nessuno swap"); return
        for h in swaps: show_swap(h)
        return
    htlc = factory.get(swap_id)
    if not htlc: err("Non trovato"); return
    show_swap(htlc)

    # controlla on-chain se configurato
    extra = _load_extra(swap_id)
    network = extra.get("evm_network", "sepolia")
    if config.get_htlc_contract(network):
        info("Verifica stato on-chain EVM...")
        try:
            bridge = _evm_bridge(network)
            onchain = bridge.get_swap_onchain(swap_id)
            if onchain and "error" not in onchain:
                ok(f"On-chain state: {onchain['state']}")
            else:
                warn("Swap non trovato on-chain (non ancora fondato)")
        except Exception as e:
            warn(f"Verifica on-chain non disponibile: {e}")

    if extra.get("btc_htlc_address"):
        info(f"BTC HTLC: {extra['btc_htlc_address']}")
        testnet = extra.get("btc_testnet", True)
        net_s   = "testnet/" if testnet else ""
        info(f"Explorer: https://mempool.space/{net_s}address/{extra['btc_htlc_address']}")


def action_network(factory):
    """Mostra info sulle reti connesse."""
    print()
    network = prompt("Rete EVM [sepolia/mainnet] (default sepolia)") or "sepolia"
    try:
        bridge = _evm_bridge(network)
        ci = bridge.connection_info()
        print()
        info(f"EVM Network   : {network}")
        info(f"Chain ID      : {ci['chain_id']}")
        info(f"Block         : #{ci['block']}")
        info(f"Contratto     : {ci['contract'] or c(RED,'non configurato')}")

        contract = config.get_htlc_contract(network)
        if not contract:
            print()
            warn("Per usare il contratto HTLC on-chain devi prima deployarlo.")
            info("1. Apri Remix IDE: https://remix.ethereum.org")
            info("2. Incolla HTLCSwap.sol e compila con Solidity 0.8.19")
            info("3. Deploy su Sepolia con Metamask (ottieni ETH da https://sepoliafaucet.com)")
            info("4. Aggiorna HTLC_CONTRACTS['sepolia'] in config.py con l'indirizzo")
    except Exception as e:
        err(f"Errore connessione EVM: {e}")

    print()
    testnet = (prompt("BTC network [testnet/mainnet] (default testnet)") or "testnet") != "mainnet"
    try:
        btc = _btc_bridge(testnet=testnet)
        ni  = btc.network_info()
        info(f"BTC Network   : {'testnet' if testnet else 'mainnet'}")
        info(f"Block         : #{ni['block_height']}")
        fees = ni.get("fees", {})
        info(f"Fee rate      : {fees.get('halfHourFee','?')} sat/vB (~30min)")
    except Exception as e:
        err(f"Errore connessione BTC: {e}")


def action_export(factory):
    swap_id = prompt("Swap ID")
    htlc = factory.get(swap_id)
    if not htlc: err("Non trovato"); return
    d = htlc.to_dict()
    d["_extra"] = _load_extra(swap_id)
    fname = f"swap_{swap_id}.json"
    with open(fname, "w") as f:
        json.dump(d, f, indent=2)
    ok(f"Esportato in {fname}")

# ── extra metadata store (btc addr, tx hash, ecc.) ───────────────────────────

_EXTRA_STORE = {}

def _save_extra(factory, swap_id, data):
    global _EXTRA_STORE
    if swap_id not in _EXTRA_STORE:
        _EXTRA_STORE[swap_id] = {}
    _EXTRA_STORE[swap_id].update(data)
    # persisti in sidecar file
    path = factory.store_path.replace(".json", "_extra.json")
    with open(path, "w") as f:
        json.dump(_EXTRA_STORE, f, indent=2)

def _load_extra(swap_id):
    return _EXTRA_STORE.get(swap_id, {})

def _init_extra(store_path):
    global _EXTRA_STORE
    path = store_path.replace(".json", "_extra.json")
    if os.path.exists(path):
        with open(path) as f:
            _EXTRA_STORE = json.load(f)

# ── menu ──────────────────────────────────────────────────────────────────────

MENU = [
    ("N", "Nuovo swap BTC ↔ USDT/USDC",              action_new),
    ("B", "Genera indirizzo BTC HTLC",               action_btc_address),
    ("K", "Controlla deposito BTC (Mempool.space)",  action_check_btc),
    ("F", "Fonda contratto EVM (Bob deposita)",      action_fund_evm),
    ("C", "Claim EVM (Alice rivela secret)",         action_claim_evm),
    ("R", "Refund EVM (dopo timelock)",              action_refund_evm),
    ("S", "Status swap",                             action_status),
    ("I", "Info reti (EVM + BTC)",                   action_network),
    ("E", "Esporta swap JSON",                       action_export),
    ("Q", "Esci",                                    None),
]

def print_menu():
    print(c(BOLD+WHITE, "\n  Comandi:\n"))
    for key, label, _ in MENU:
        print(f"    {c(CYAN+BOLD,key)}  {label}")
    print()

def main():
    banner()
    config.ensure_store_dir()
    store   = os.environ.get("SWAP_STORE", config.SWAP_STORE_PATH)
    factory = SwapFactory(store_path=store)
    _init_extra(store)
    info(f"Store: {store}")
    info(f"Swaps attivi: {len(factory.list_all())}")

    while True:
        print_menu()
        choice = input(c(BOLD, "  Cryptoswap> ")).strip().upper()
        print()
        if choice == "Q":
            info("Bye."); break
        matched = False
        for key, _, fn in MENU:
            if choice == key and fn:
                try:
                    fn(factory)
                except (KeyboardInterrupt, EOFError):
                    print(); warn("Annullato")
                except ValueError as ve:
                    err(f"Input non valido: {ve}")
                matched = True; break
        if not matched and choice != "Q":
            err(f"Comando sconosciuto: '{choice}'")

if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print(c(DIM, "\n  Bye.\n"))
        sys.exit(0)
