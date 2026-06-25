// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

/**
 * HTLCSwap — Hashed Timelock Contract per EVM
 * Supporta ETH nativo e qualsiasi ERC-20 (USDT, USDC, DAI...)
 *
 * Flusso:
 *   1. Bob chiama fund() depositando token + secret_hash + timelock
 *   2. Alice chiama claim() rivelando il secret → secret scritto on-chain
 *   3. Se Alice non fa claim → Bob chiama refund() dopo il timelock
 */

interface IERC20 {
    function transferFrom(address from, address to, uint256 amount) external returns (bool);
    function transfer(address to, uint256 amount) external returns (bool);
}

contract HTLCSwap {

    enum State { EMPTY, FUNDED, CLAIMED, REFUNDED }

    struct Swap {
        bytes32  secretHash;
        uint256  timelock;
        address  funder;
        address  recipient;
        address  token;        // address(0) = ETH nativo
        uint256  amount;
        State    state;
        bytes32  secret;       // rivelato al claim
        uint256  fundedAt;
        uint256  claimedAt;
    }

    mapping(bytes32 => Swap) public swaps;

    event Funded(bytes32 indexed swapId, bytes32 indexed secretHash,
                 address indexed funder, address recipient,
                 address token, uint256 amount, uint256 timelock);
    event Claimed(bytes32 indexed swapId, bytes32 secret, address indexed recipient);
    event Refunded(bytes32 indexed swapId, address indexed funder);

    error SwapAlreadyExists();
    error SwapNotFound();
    error AlreadyClaimed();
    error AlreadyRefunded();
    error TimelockNotExpired();
    error TimelockExpired();
    error InvalidSecret();
    error NotRecipient();
    error InvalidAmount();
    error TransferFailed();

    function fund(
        bytes32 swapId, bytes32 secretHash, uint256 timelock,
        address recipient, address token, uint256 amount
    ) external {
        if (swaps[swapId].state != State.EMPTY) revert SwapAlreadyExists();
        if (amount == 0)                         revert InvalidAmount();
        if (timelock <= block.timestamp)         revert TimelockExpired();

        bool ok = IERC20(token).transferFrom(msg.sender, address(this), amount);
        if (!ok) revert TransferFailed();

        swaps[swapId] = Swap(secretHash, timelock, msg.sender, recipient,
                             token, amount, State.FUNDED, bytes32(0),
                             block.timestamp, 0);
        emit Funded(swapId, secretHash, msg.sender, recipient, token, amount, timelock);
    }

    function fundETH(
        bytes32 swapId, bytes32 secretHash, uint256 timelock, address recipient
    ) external payable {
        if (swaps[swapId].state != State.EMPTY) revert SwapAlreadyExists();
        if (msg.value == 0)                      revert InvalidAmount();
        if (timelock <= block.timestamp)         revert TimelockExpired();

        swaps[swapId] = Swap(secretHash, timelock, msg.sender, recipient,
                             address(0), msg.value, State.FUNDED, bytes32(0),
                             block.timestamp, 0);
        emit Funded(swapId, secretHash, msg.sender, recipient, address(0), msg.value, timelock);
    }

    function claim(bytes32 swapId, bytes32 secret) external {
        Swap storage s = swaps[swapId];
        if (s.state == State.EMPTY)        revert SwapNotFound();
        if (s.state == State.CLAIMED)      revert AlreadyClaimed();
        if (s.state == State.REFUNDED)     revert AlreadyRefunded();
        if (block.timestamp >= s.timelock) revert TimelockExpired();
        if (msg.sender != s.recipient)     revert NotRecipient();
        if (sha256(abi.encodePacked(secret)) != s.secretHash) revert InvalidSecret();

        s.state = State.CLAIMED; s.secret = secret; s.claimedAt = block.timestamp;

        if (s.token == address(0)) {
            (bool ok,) = payable(s.recipient).call{value: s.amount}("");
            if (!ok) revert TransferFailed();
        } else {
            if (!IERC20(s.token).transfer(s.recipient, s.amount)) revert TransferFailed();
        }
        emit Claimed(swapId, secret, s.recipient);
    }

    function refund(bytes32 swapId) external {
        Swap storage s = swaps[swapId];
        if (s.state == State.EMPTY)       revert SwapNotFound();
        if (s.state == State.CLAIMED)     revert AlreadyClaimed();
        if (s.state == State.REFUNDED)    revert AlreadyRefunded();
        if (block.timestamp < s.timelock) revert TimelockNotExpired();

        s.state = State.REFUNDED;
        if (s.token == address(0)) {
            (bool ok,) = payable(s.funder).call{value: s.amount}("");
            if (!ok) revert TransferFailed();
        } else {
            if (!IERC20(s.token).transfer(s.funder, s.amount)) revert TransferFailed();
        }
        emit Refunded(swapId, s.funder);
    }

    function getSwap(bytes32 swapId) external view returns (Swap memory) {
        return swaps[swapId];
    }

    function isClaimable(bytes32 swapId) external view returns (bool) {
        Swap storage s = swaps[swapId];
        return s.state == State.FUNDED && block.timestamp < s.timelock;
    }

    function isRefundable(bytes32 swapId) external view returns (bool) {
        Swap storage s = swaps[swapId];
        return s.state == State.FUNDED && block.timestamp >= s.timelock;
    }
}
