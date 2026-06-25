"""
Config — AtomicSwap
Tutti i parametri di rete in un posto solo.
"""
import os, json

EVM_RPC_URLS = {
    "sepolia": [
        "https://rpc.sepolia.org",
        "https://ethereum-sepolia-rpc.publicnode.com",
        "https://sepolia.drpc.org",
    ],
    "mainnet": ["https://ethereum-rpc.publicnode.com"],
    "polygon": ["https://polygon-rpc.com"],
}

EVM_CHAIN_IDS = {"sepolia": 11155111, "mainnet": 1, "polygon": 137}

# Aggiorna dopo il deploy su Sepolia
HTLC_CONTRACTS = {
    "sepolia": os.environ.get("HTLC_CONTRACT_SEPOLIA", ""),
    "mainnet": os.environ.get("HTLC_CONTRACT_MAINNET", ""),
}

TOKENS = {
    "sepolia": {
        "USDC": "0x1c7D4B196Cb0C7B01d743Fbc6116a902379C7238",
        "DAI":  "0x68194a729C2450ad26072b3D33ADaCbcef39D574",
    },
    "mainnet": {
        "USDT": "0xdAC17F958D2ee523a2206206994597C13D831ec7",
        "USDC": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
        "DAI":  "0x6B175474E89094C44Da98b954EedeAC495271d0F",
    },
}

BTC_NETWORK  = os.environ.get("BTC_NETWORK", "testnet")
BTC_TESTNET  = BTC_NETWORK != "mainnet"
DEFAULT_TIMELOCK        = 86400
BTC_MIN_CONFIRMATIONS   = 1
EVM_MIN_CONFIRMATIONS   = 1

SWAP_STORE_PATH = os.environ.get(
    "SWAP_STORE",
    os.path.join(os.path.expanduser("~"), ".atomicswap", "swaps.json")
)

def get_evm_rpc(network="sepolia"):
    return EVM_RPC_URLS.get(network, EVM_RPC_URLS["sepolia"])[0]

def get_htlc_contract(network="sepolia"):
    return HTLC_CONTRACTS.get(network, "")

def get_token_address(symbol, network="sepolia"):
    return TOKENS.get(network, {}).get(symbol.upper(), "")

def ensure_store_dir():
    os.makedirs(os.path.dirname(SWAP_STORE_PATH), exist_ok=True)
