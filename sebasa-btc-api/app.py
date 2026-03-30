"""
Bitcoin Node API - Umbrel App
FastAPI service that connects to the local Bitcoin node and Mempool instance.
Minimal dependencies: fastapi, uvicorn, bit, httpx
"""

import os
import hashlib
import struct
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from bit import Key

# ── Config from environment ──────────────────────────────────────────────────
RPC_USER = os.getenv("BITCOIN_RPC_USER", "umbrel")
RPC_PASS = os.getenv("BITCOIN_RPC_PASS", "")
RPC_HOST = os.getenv("BITCOIN_RPC_HOST", "10.21.21.8")
RPC_PORT = int(os.getenv("BITCOIN_RPC_PORT", "8332"))
MEMPOOL_HOST = os.getenv("MEMPOOL_HOST", "10.21.21.26")
MEMPOOL_PORT = int(os.getenv("MEMPOOL_PORT", "8999"))
SWEEP_ADDRESS = os.getenv("SWEEP_ADDRESS", "")

MEMPOOL_URL = f"http://{MEMPOOL_HOST}:{MEMPOOL_PORT}/api"
RPC_URL = f"http://{RPC_USER}:{RPC_PASS}@{RPC_HOST}:{RPC_PORT}"

# ── App ──────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Bitcoin Node API",
    description="Lightweight API for interacting with a local Bitcoin node on Umbrel",
    version="1.1.0",
)

http = httpx.AsyncClient(timeout=30.0)


# ═════════════════════════════════════════════════════════════════════════════
#  RAW TX PARSER — extract R, S, Z, pubkey from each input (zero dependencies)
# ═════════════════════════════════════════════════════════════════════════════

def _read_varint(data: bytes, offset: int) -> tuple[int, int]:
    """Read a Bitcoin variable-length integer. Returns (value, new_offset)."""
    first = data[offset]
    if first < 0xFD:
        return first, offset + 1
    elif first == 0xFD:
        return struct.unpack_from("<H", data, offset + 1)[0], offset + 3
    elif first == 0xFE:
        return struct.unpack_from("<I", data, offset + 1)[0], offset + 5
    else:
        return struct.unpack_from("<Q", data, offset + 1)[0], offset + 9


def _parse_der_signature(sig_bytes: bytes) -> tuple[str, str]:
    """
    Parse a DER-encoded ECDSA signature and return (R, S) as hex strings.
    DER format: 30 <len> 02 <r_len> <r> 02 <s_len> <s> [sighash]
    """
    idx = 0
    if sig_bytes[idx] != 0x30:
        raise ValueError("Not a DER signature")
    idx += 1
    # total length
    idx += 1  # skip length byte

    # R
    if sig_bytes[idx] != 0x02:
        raise ValueError("Expected 0x02 for R")
    idx += 1
    r_len = sig_bytes[idx]
    idx += 1
    r_bytes = sig_bytes[idx:idx + r_len]
    idx += r_len

    # S
    if sig_bytes[idx] != 0x02:
        raise ValueError("Expected 0x02 for S")
    idx += 1
    s_len = sig_bytes[idx]
    idx += 1
    s_bytes = sig_bytes[idx:idx + s_len]

    # Strip leading zero padding
    r_hex = r_bytes.lstrip(b"\x00").hex()
    s_hex = s_bytes.lstrip(b"\x00").hex()
    return r_hex, s_hex


def _double_sha256(data: bytes) -> bytes:
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()


def _serialize_output(tx_data: bytes, offset: int) -> tuple[bytes, int]:
    """Serialize a single output: value (8 bytes) + scriptPubKey."""
    value = tx_data[offset:offset + 8]
    offset += 8
    script_len, offset = _read_varint(tx_data, offset)
    script = tx_data[offset:offset + script_len]
    offset += script_len
    return value + _encode_varint(script_len) + script, offset


def _encode_varint(n: int) -> bytes:
    if n < 0xFD:
        return bytes([n])
    elif n <= 0xFFFF:
        return b"\xfd" + struct.pack("<H", n)
    elif n <= 0xFFFFFFFF:
        return b"\xfe" + struct.pack("<I", n)
    else:
        return b"\xff" + struct.pack("<Q", n)


def _parse_legacy_tx(raw_hex: str) -> list[dict]:
    """
    Parse a legacy (non-segwit) raw transaction.
    For each input that has a standard P2PKH scriptsig (sig + pubkey),
    compute R, S from the DER signature, and Z (sighash) by re-serializing.
    Returns a list of dicts per input: {vin, R, S, Z, pubkey, sighash_type}.
    """
    data = bytes.fromhex(raw_hex)
    results = []

    offset = 0
    # version (4 bytes)
    version = data[offset:offset + 4]
    offset += 4

    # Check for segwit marker
    is_segwit = False
    if data[offset] == 0x00 and data[offset + 1] != 0x00:
        is_segwit = True
        offset += 2  # skip marker + flag

    # ── Parse inputs ─────────────────────────────────────────────────────
    in_count, offset = _read_varint(data, offset)
    inputs = []
    for _ in range(in_count):
        txid_prev = data[offset:offset + 32]
        offset += 32
        vout = struct.unpack_from("<I", data, offset)[0]
        offset += 4
        script_len, offset = _read_varint(data, offset)
        scriptsig = data[offset:offset + script_len]
        offset += script_len
        sequence = data[offset:offset + 4]
        offset += 4
        inputs.append({
            "txid": txid_prev,
            "vout": vout,
            "scriptsig": scriptsig,
            "sequence": sequence,
        })

    # ── Parse outputs (we need them for sighash) ─────────────────────────
    out_start = offset
    out_count, offset = _read_varint(data, offset)
    outputs_raw = []
    for _ in range(out_count):
        out_begin = offset
        offset += 8  # value
        spk_len, offset = _read_varint(data, offset)
        offset += spk_len
        outputs_raw.append(data[out_begin:offset])

    # ── Witness data (if segwit) ─────────────────────────────────────────
    witness_data = []
    if is_segwit:
        for _ in range(in_count):
            wit_count, offset = _read_varint(data, offset)
            items = []
            for _ in range(wit_count):
                item_len, offset = _read_varint(data, offset)
                items.append(data[offset:offset + item_len])
                offset += item_len
            witness_data.append(items)

    # locktime (4 bytes)
    locktime = data[offset:offset + 4]

    # ── Extract R, S, Z per input ────────────────────────────────────────
    for i, inp in enumerate(inputs):
        sig_bytes = None
        pubkey_bytes = None

        if not is_segwit and len(inp["scriptsig"]) > 0:
            # Legacy P2PKH: scriptsig = <push sig> <push pubkey>
            ss = inp["scriptsig"]
            try:
                pos = 0
                sig_push_len = ss[pos]
                pos += 1
                sig_bytes = ss[pos:pos + sig_push_len]
                pos += sig_push_len
                pub_push_len = ss[pos]
                pos += 1
                pubkey_bytes = ss[pos:pos + pub_push_len]
            except (IndexError, ValueError):
                continue
        elif is_segwit and i < len(witness_data) and len(witness_data[i]) >= 2:
            # Segwit P2WPKH: witness = [sig, pubkey]
            sig_bytes = witness_data[i][-2]  # second to last is sig
            pubkey_bytes = witness_data[i][-1]  # last is pubkey

        if sig_bytes is None or pubkey_bytes is None:
            continue
        if len(sig_bytes) < 8:
            continue

        # Sighash type is the last byte of the signature
        sighash_type = sig_bytes[-1]
        der_sig = sig_bytes[:-1]

        try:
            r_hex, s_hex = _parse_der_signature(der_sig)
        except (ValueError, IndexError):
            continue

        # ── Compute Z (sighash) ──────────────────────────────────────────
        # For legacy: SIGHASH_ALL → blank all scriptsigs except current,
        # put the subscript (scriptPubKey of prev output) in current input.
        # For simplicity, we use the pubkey to derive the expected P2PKH script.
        if not is_segwit:
            # Build the scriptPubKey for P2PKH from the pubkey
            pubkey_hash = hashlib.new("ripemd160", hashlib.sha256(pubkey_bytes).digest()).digest()
            subscript = b"\x76\xa9\x14" + pubkey_hash + b"\x88\xac"

            # Serialize for signing
            preimage = version
            preimage += _encode_varint(in_count)
            for j, jinp in enumerate(inputs):
                preimage += jinp["txid"]
                preimage += struct.pack("<I", jinp["vout"])
                if j == i:
                    preimage += _encode_varint(len(subscript)) + subscript
                else:
                    preimage += b"\x00"  # empty scriptsig
                preimage += jinp["sequence"]
            preimage += _encode_varint(out_count)
            for out_raw in outputs_raw:
                preimage += out_raw
            preimage += locktime
            preimage += struct.pack("<I", sighash_type)

            z = _double_sha256(preimage).hex()
        else:
            # BIP143 sighash for segwit v0
            # hashPrevouts
            prevouts = b""
            for jinp in inputs:
                prevouts += jinp["txid"] + struct.pack("<I", jinp["vout"])
            hash_prevouts = _double_sha256(prevouts)

            # hashSequence
            sequences = b""
            for jinp in inputs:
                sequences += jinp["sequence"]
            hash_sequence = _double_sha256(sequences)

            # hashOutputs
            all_outputs = b""
            for out_raw in outputs_raw:
                all_outputs += out_raw
            hash_outputs = _double_sha256(all_outputs)

            # scriptCode for P2WPKH
            pubkey_hash = hashlib.new("ripemd160", hashlib.sha256(pubkey_bytes).digest()).digest()
            script_code = b"\x19\x76\xa9\x14" + pubkey_hash + b"\x88\xac"

            # We need the input amount for BIP143, which we don't have from raw tx alone.
            # Set Z to "unavailable" — would need UTXO lookup to compute.
            z = "requires_utxo_amount"

        results.append({
            "vin": i,
            "R": r_hex,
            "S": s_hex,
            "Z": z,
            "pubkey": pubkey_bytes.hex(),
            "sighash_type": sighash_type,
        })

    return results


# ═════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ═════════════════════════════════════════════════════════════════════════════

async def rpc_call(method: str, params: list = None):
    """Make a JSON-RPC call to the Bitcoin node."""
    payload = {"jsonrpc": "1.0", "id": "api", "method": method, "params": params or []}
    try:
        r = await http.post(RPC_URL, json=payload)
        data = r.json()
        if data.get("error"):
            raise HTTPException(status_code=500, detail=data["error"])
        return data["result"]
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"Node connection error: {e}")


async def mempool_get(path: str):
    """GET request to the local Mempool API."""
    url = f"{MEMPOOL_URL}{path}"
    try:
        r = await http.get(url)
        r.raise_for_status()
        return r.json()
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"Mempool API error: {e.response.status_code} on {url} — {e.response.text[:200]}"
        )
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"Mempool connection error: {url} — {e}")


async def get_raw_hex(txid: str) -> str:
    """Get raw tx hex, trying node first then Mempool."""
    try:
        return await rpc_call("getrawtransaction", [txid])
    except HTTPException:
        r = await http.get(f"{MEMPOOL_URL}/tx/{txid}/hex")
        r.raise_for_status()
        return r.text


# ═════════════════════════════════════════════════════════════════════════════
#  ENDPOINTS
# ═════════════════════════════════════════════════════════════════════════════

# ── Node Info ────────────────────────────────────────────────────────────────
@app.get("/info")
async def node_info():
    """Get Bitcoin node information: block height, sync status, network."""
    blockchain = await rpc_call("getblockchaininfo")
    network = await rpc_call("getnetworkinfo")
    return {
        "chain": blockchain["chain"],
        "blocks": blockchain["blocks"],
        "headers": blockchain["headers"],
        "sync_progress": round(blockchain["verificationprogress"] * 100, 2),
        "pruned": blockchain["pruned"],
        "version": network["subversion"],
        "connections": network["connections"],
    }

# ── Fees (via Mempool) ───────────────────────────────────────────────────────
@app.get("/fees/recommended")
async def recommended_fees():
    """Get recommended fees from local Mempool instance."""
    return await mempool_get("/v1/fees/recommended")

# ── Address ──────────────────────────────────────────────────────────────────
@app.get("/address/{address}")
async def address_info(address: str):
    """Get address info from Mempool (balance, tx count)."""
    return await mempool_get(f"/address/{address}")


@app.get("/address/{address}/utxos")
async def address_utxos(address: str):
    """Get UTXOs for an address via Mempool."""
    return await mempool_get(f"/address/{address}/utxo")


@app.get("/address/{address}/txs")
async def address_txs(address: str):
    """Get transaction history for an address."""
    return await mempool_get(f"/address/{address}/txs")


# ── Transactions ─────────────────────────────────────────────────────────────
@app.get("/tx/{txid}")
async def get_transaction(txid: str):
    """Get transaction details from Mempool."""
    return await mempool_get(f"/tx/{txid}")


@app.get("/tx/{txid}/hex")
async def get_tx_hex(txid: str):
    """Get raw transaction hex from the node."""
    raw = await get_raw_hex(txid)
    return {"hex": raw}


@app.get("/tx/{txid}/rsz")
async def get_rsz(txid: str):
    """
    Extract ECDSA signature values (R, S, Z) and public key for each input.
    Parses the raw transaction hex directly — no external crypto libraries needed.
    For segwit inputs, Z requires UTXO amounts (BIP143) and will show 'requires_utxo_amount'.
    """
    raw = await get_raw_hex(txid)
    try:
        inputs = _parse_legacy_tx(raw)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Parse error: {e}")
    if not inputs:
        raise HTTPException(
            status_code=404,
            detail="No extractable signatures found (multisig/taproot inputs are not supported)"
        )
    return {"txid": txid, "inputs": inputs}


@app.post("/tx/broadcast")
async def broadcast_tx(body: dict):
    """Broadcast a raw transaction hex to the network."""
    hex_tx = body.get("hex", "")
    if not hex_tx:
        raise HTTPException(status_code=400, detail="Missing 'hex' field in body")
    txid = await rpc_call("sendrawtransaction", [hex_tx])
    return {"txid": txid}


# ── Sweep ────────────────────────────────────────────────────────────────────
@app.post("/sweep/wif")
async def sweep_wif(body: dict):
    """Sweep all funds from a WIF private key to the configured sweep address."""
    if not SWEEP_ADDRESS:
        raise HTTPException(status_code=500, detail="SWEEP_ADDRESS not configured")
    wif = body.get("key", "")
    if not wif:
        raise HTTPException(status_code=400, detail="Missing 'key' field")
    try:
        k = Key(wif)
        tx = k.create_transaction([], leftover=SWEEP_ADDRESS)
        txid = await rpc_call("sendrawtransaction", [tx])
        return {"txid": txid, "from": k.address, "to": SWEEP_ADDRESS}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/sweep/hex")
async def sweep_hex(body: dict):
    """Sweep all funds from a hex private key to the configured sweep address."""
    if not SWEEP_ADDRESS:
        raise HTTPException(status_code=500, detail="SWEEP_ADDRESS not configured")
    hexkey = body.get("key", "")
    if not hexkey:
        raise HTTPException(status_code=400, detail="Missing 'key' field")
    try:
        k = Key.from_hex(hexkey)
        tx = k.create_transaction([], leftover=SWEEP_ADDRESS)
        txid = await rpc_call("sendrawtransaction", [tx])
        return {"txid": txid, "from": k.address, "to": SWEEP_ADDRESS}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Public Key Recovery ───────────────────────────────────────────────────────

def _hash160(data: bytes) -> bytes:
    """RIPEMD160(SHA256(data))"""
    return hashlib.new("ripemd160", hashlib.sha256(data).digest()).digest()


def _base58check_encode(version: bytes, payload: bytes) -> str:
    """Base58Check encode: version + payload + checksum."""
    data = version + payload
    checksum = hashlib.sha256(hashlib.sha256(data).digest()).digest()[:4]
    raw = data + checksum
    # Base58 encoding
    alphabet = b"123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    n = int.from_bytes(raw, "big")
    chars = []
    while n > 0:
        n, r = divmod(n, 58)
        chars.append(alphabet[r])
    # leading zeros
    for byte in raw:
        if byte == 0:
            chars.append(alphabet[0])
        else:
            break
    return bytes(reversed(chars)).decode()


_BECH32_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"


def _bech32_polymod(values):
    GEN = [0x3b6a57b2, 0x26508e6d, 0x1ea119fa, 0x3d4233dd, 0x2a1462b3]
    chk = 1
    for v in values:
        b = chk >> 25
        chk = ((chk & 0x1FFFFFF) << 5) ^ v
        for i in range(5):
            chk ^= GEN[i] if ((b >> i) & 1) else 0
    return chk


def _bech32_hrp_expand(hrp):
    return [ord(x) >> 5 for x in hrp] + [0] + [ord(x) & 31 for x in hrp]


def _bech32_encode(hrp, witver, witprog):
    """Encode a segwit address (bech32 for v0)."""
    data = [witver] + _convertbits(witprog, 8, 5)
    polymod = _bech32_polymod(_bech32_hrp_expand(hrp) + data + [0, 0, 0, 0, 0, 0]) ^ 1
    checksum = [(polymod >> 5 * (5 - i)) & 31 for i in range(6)]
    return hrp + "1" + "".join(_BECH32_CHARSET[d] for d in data + checksum)


def _convertbits(data, frombits, tobits):
    acc, bits, ret = 0, 0, []
    maxv = (1 << tobits) - 1
    for value in data:
        acc = (acc << frombits) | value
        bits += frombits
        while bits >= tobits:
            bits -= tobits
            ret.append((acc >> bits) & maxv)
    if bits:
        ret.append((acc << (tobits - bits)) & maxv)
    return ret


def _pubkey_to_addresses(pubkey_hex: str) -> list[str]:
    """Derive all standard address forms from a public key."""
    pubkey_bytes = bytes.fromhex(pubkey_hex)
    h160 = _hash160(pubkey_bytes)
    addresses = []
    # P2PKH (1...)
    addresses.append(_base58check_encode(b"\x00", h160))
    # P2SH-P2WPKH (3...)
    witness_script = b"\x00\x14" + h160
    addresses.append(_base58check_encode(b"\x05", _hash160(witness_script)))
    # P2WPKH bech32 (bc1q...)
    addresses.append(_bech32_encode("bc", 0, list(h160)))
    return addresses


@app.get("/address/{address}/getpubkey")
async def get_pubkey(address: str):
    """
    Recover the public key for a Bitcoin address by scanning its transaction history.
    Only works if the address has spent funds at least once (pubkey is revealed on-chain).
    """
    txs = await mempool_get(f"/address/{address}/txs")
    if not txs:
        raise HTTPException(status_code=404, detail="No transactions found for this address")

    for tx in txs:
        txid = tx["txid"]
        # Check if any input belongs to this address
        has_matching_input = False
        for vin in tx.get("vin", []):
            prevout = vin.get("prevout", {})
            if prevout and prevout.get("scriptpubkey_address") == address:
                has_matching_input = True
                break
        if not has_matching_input:
            continue

        # Parse the raw tx to extract pubkeys
        try:
            raw = await get_raw_hex(txid)
            parsed_inputs = _parse_legacy_tx(raw)
        except Exception:
            continue

        for pinp in parsed_inputs:
            pubkey_hex = pinp["pubkey"]
            derived = _pubkey_to_addresses(pubkey_hex)
            if address in derived:
                return {
                    "address": address,
                    "pubkey": pubkey_hex,
                    "found_in_txid": txid,
                    "derived_addresses": {
                        "p2pkh": derived[0],
                        "p2sh_p2wpkh": derived[1],
                        "p2wpkh": derived[2],
                    },
                }

    raise HTTPException(
        status_code=404,
        detail="Public key not found. The address may have never spent funds (only received)."
    )


# ── Health ───────────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    """Health check — verifies node and Mempool connectivity."""
    status = {"node": False, "mempool": False}
    try:
        await rpc_call("getblockcount")
        status["node"] = True
    except Exception:
        pass
    try:
        await mempool_get("/v1/fees/recommended")
        status["mempool"] = True
    except Exception:
        pass
    ok = all(status.values())
    return JSONResponse(content=status, status_code=200 if ok else 503)


# ── Startup / Shutdown ───────────────────────────────────────────────────────
@app.on_event("shutdown")
async def shutdown():
    await http.aclose()
