"""
Model shard coordinator — pipeline-parallel inference across the phone fleet.

A 70B model at 4-bit quantization is ~40 GB. No single phone holds that.
This coordinator splits the transformer layers across N devices, routes the
hidden state through the pipeline, and returns the final output token.

Architecture (pipeline parallelism):

  [Client] ─tokens─▶ [Shard 0: embed + layers 0..k]
                               │ hidden_state (float32)
                               ▼
                      [Shard 1: layers k..2k]
                               │ hidden_state
                               ▼
                             ...
                               │ hidden_state
                               ▼
                      [Shard N: layers ..end + lm_head] ─logits─▶ [Coordinator samples token]

Each shard runs on a phone that has loaded only its layer slice from the GGUF file.
The coordinator (this module) is stateless — it reads device state from the DB,
plans the shard assignment, configures devices, then drives each generation step.

Supported models:
  llama3.1-70b:   80 layers, hidden_dim=8192, vocab=128256
  llama3.2-3b:    28 layers, hidden_dim=3072, vocab=128256
  gemma2-27b:     46 layers, hidden_dim=4608, vocab=256000
  phi-4-14b:      40 layers, hidden_dim=5120, vocab=100352
"""

import base64
import logging
import struct
import time
from dataclasses import dataclass, field
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# ── Model specs ────────────────────────────────────────────────────────────────

MODEL_SPECS = {
    "llama3.1-70b": {
        "num_layers": 80,
        "hidden_dim": 8192,
        "vocab_size": 128256,
        "min_ram_per_shard_mb": 5_500,   # ~5.5 GB per shard for 10 layers at 4-bit
        "layers_per_gb": 1.8,            # rough: how many layers fit per GB of RAM
        "description": "Llama 3.1 70B — requires 6+ devices with 8 GB RAM",
    },
    "llama3.2-3b": {
        "num_layers": 28,
        "hidden_dim": 3072,
        "vocab_size": 128256,
        "min_ram_per_shard_mb": 700,
        "layers_per_gb": 14,
        "description": "Llama 3.2 3B — runs on 1 device, shard for speed",
    },
    "gemma2-27b": {
        "num_layers": 46,
        "hidden_dim": 4608,
        "vocab_size": 256000,
        "min_ram_per_shard_mb": 2_800,
        "layers_per_gb": 4,
        "description": "Gemma 2 27B — requires 4+ devices with 6 GB RAM",
    },
    "phi-4-14b": {
        "num_layers": 40,
        "hidden_dim": 5120,
        "vocab_size": 100352,
        "min_ram_per_shard_mb": 1_800,
        "layers_per_gb": 7,
        "description": "Phi-4 14B — requires 2+ devices with 8 GB RAM",
    },
}

# ── Data structures ────────────────────────────────────────────────────────────

@dataclass
class ShardAssignment:
    device_id: str
    device_ip: str
    shard_index: int
    total_shards: int
    layer_start: int
    layer_end: int       # exclusive
    is_final_shard: bool
    model_name: str
    hidden_dim: int
    ram_available_mb: int

@dataclass
class ShardPlan:
    model_name: str
    total_shards: int
    shards: list[ShardAssignment] = field(default_factory=list)
    hidden_dim: int = 8192
    vocab_size: int = 128256
    total_layers: int = 80
    feasible: bool = True
    reason: str = ""

# ── Planning ───────────────────────────────────────────────────────────────────

def plan_shards(model_name: str, devices: list) -> ShardPlan:
    """
    Given a model name and a list of active Device ORM objects,
    return a ShardPlan assigning layers to devices.

    Devices are sorted by available RAM descending.
    Layers are distributed proportionally to available RAM.
    """
    spec = MODEL_SPECS.get(model_name)
    if not spec:
        return ShardPlan(
            model_name=model_name,
            total_shards=0,
            feasible=False,
            reason=f"Unknown model '{model_name}'. Known: {list(MODEL_SPECS.keys())}",
        )

    num_layers = spec["num_layers"]
    hidden_dim = spec["hidden_dim"]
    vocab_size = spec["vocab_size"]
    min_ram_mb = spec["min_ram_per_shard_mb"]
    layers_per_gb = spec["layers_per_gb"]

    # Filter devices that have enough RAM
    eligible = [
        d for d in devices
        if (d.ram_available_mb or 0) >= min_ram_mb
        and d.device_ip
        and not d.is_quarantined
    ]

    if not eligible:
        return ShardPlan(
            model_name=model_name,
            total_shards=0,
            feasible=False,
            reason=(
                f"No eligible devices. Need {min_ram_mb} MB RAM each. "
                f"Available devices: {len(devices)}, eligible: 0. "
                f"Either add more devices or use a smaller model."
            ),
        )

    # Sort by RAM descending — bigger devices get more layers
    eligible.sort(key=lambda d: d.ram_available_mb or 0, reverse=True)

    # Compute how many layers each device can hold
    ram_capacities = [
        max(1, int((d.ram_available_mb / 1024) * layers_per_gb))
        for d in eligible
    ]
    total_capacity = sum(ram_capacities)

    # Check we can fit all layers
    if total_capacity < num_layers:
        needed_devices = (num_layers + ram_capacities[0] - 1) // ram_capacities[0]
        return ShardPlan(
            model_name=model_name,
            total_shards=0,
            feasible=False,
            reason=(
                f"Fleet RAM too small. Need capacity for {num_layers} layers, "
                f"have {total_capacity}. Add ~{needed_devices - len(eligible)} more devices."
            ),
        )

    # Assign layers proportionally, ensuring all layers are covered
    shards = []
    layer_cursor = 0
    for i, device in enumerate(eligible):
        if layer_cursor >= num_layers:
            break
        is_last = (i == len(eligible) - 1) or (layer_cursor + ram_capacities[i] >= num_layers)
        layer_end = num_layers if is_last else min(layer_cursor + ram_capacities[i], num_layers)

        shards.append(ShardAssignment(
            device_id=device.device_id,
            device_ip=device.device_ip,
            shard_index=i,
            total_shards=0,  # filled below
            layer_start=layer_cursor,
            layer_end=layer_end,
            is_final_shard=is_last,
            model_name=model_name,
            hidden_dim=hidden_dim,
            ram_available_mb=device.ram_available_mb or 0,
        ))
        layer_cursor = layer_end
        if is_last:
            break

    for s in shards:
        s.total_shards = len(shards)

    return ShardPlan(
        model_name=model_name,
        total_shards=len(shards),
        shards=shards,
        hidden_dim=hidden_dim,
        vocab_size=vocab_size,
        total_layers=num_layers,
        feasible=True,
    )

# ── Device configuration ───────────────────────────────────────────────────────

async def configure_shard_devices(plan: ShardPlan, model_base_path: str) -> dict:
    """
    Push shard configuration to each device via HTTP POST /shard/configure.
    Returns {device_id: success_bool}.
    """
    results = {}
    async with httpx.AsyncClient(timeout=30) as client:
        for i, shard in enumerate(plan.shards):
            next_url = None
            if not shard.is_final_shard and i + 1 < len(plan.shards):
                next_shard = plan.shards[i + 1]
                next_url = f"http://{next_shard.device_ip}:11434"

            # Model shard file naming convention:
            # {model_base_path}/{model_name}-shard{i:02d}-of{total:02d}.gguf
            model_path = (
                f"{model_base_path}/{plan.model_name}"
                f"-shard{i:02d}-of{plan.total_shards:02d}.gguf"
            )

            payload = {
                "shard_index":   shard.shard_index,
                "total_shards":  shard.total_shards,
                "layer_start":   shard.layer_start,
                "layer_end":     shard.layer_end,
                "is_final_shard": shard.is_final_shard,
                "model_path":    model_path,
                "next_shard_url": next_url,
                "hidden_dim":    plan.hidden_dim,
                "threads":       4,
            }

            url = f"http://{shard.device_ip}:11434/shard/configure"
            try:
                resp = await client.post(url, json=payload)
                results[shard.device_id] = resp.status_code == 200
            except Exception as e:
                logger.error("Failed to configure shard %d on %s: %s", i, shard.device_id, e)
                results[shard.device_id] = False

    return results

# ── Inference pipeline ─────────────────────────────────────────────────────────

async def run_sharded_inference(
    plan: ShardPlan,
    token_ids: list[int],
    max_new_tokens: int = 256,
    temperature: float = 0.7,
) -> dict:
    """
    Drive the full pipeline for one generation request.

    Sends token IDs to shard 0. Shard 0 runs its layers and either:
    - passes hidden state to shard 1 (which chains to shard 2, etc.), OR
    - if only 1 shard, returns logits directly.

    The coordinator receives logits from the final shard, samples the next token,
    feeds it back to shard 0, and repeats until max_new_tokens or EOS.

    Returns: {"tokens": [...], "text": "...", "pipeline_ms": ..., "shards_used": N}
    """
    if not plan.feasible or not plan.shards:
        raise ValueError(f"Shard plan not feasible: {plan.reason}")

    first_shard = plan.shards[0]
    first_url = f"http://{first_shard.device_ip}:11434"

    generated_tokens: list[int] = []
    pipeline_start = time.time()

    # Encode token IDs as int32 little-endian bytes
    def tokens_to_bytes(ids: list[int]) -> bytes:
        return struct.pack(f"<{len(ids)}i", *ids)

    def bytes_to_logits(raw: bytes) -> list[float]:
        n = len(raw) // 4
        return list(struct.unpack(f"<{n}f", raw[:n * 4]))

    def sample_token(logits: list[float], temp: float) -> int:
        if temp == 0:
            return logits.index(max(logits))
        import math
        max_l = max(logits)
        exps = [math.exp((l - max_l) / temp) for l in logits]
        total = sum(exps)
        probs = [e / total for e in exps]
        import random
        r = random.random()
        cumulative = 0.0
        for i, p in enumerate(probs):
            cumulative += p
            if r < cumulative:
                return i
        return len(probs) - 1

    EOS_TOKEN_ID = 128009  # Llama 3 EOS

    current_ids = list(token_ids)
    async with httpx.AsyncClient(timeout=120) as client:
        for _ in range(max_new_tokens):
            input_bytes = tokens_to_bytes(current_ids)
            input_b64 = base64.b64encode(input_bytes).decode()

            resp = await client.post(
                f"{first_url}/shard/forward",
                json={"token_ids_b64": input_b64, "is_token_ids": True},
            )
            if not resp.is_success:
                raise RuntimeError(f"Shard 0 returned {resp.status_code}: {resp.text}")

            data = resp.json()
            output_b64 = data.get("output_b64", "")
            output_bytes = base64.b64decode(output_b64)

            logits = bytes_to_logits(output_bytes)
            if len(logits) < plan.vocab_size:
                # Truncated — pipeline error
                raise RuntimeError(
                    f"Final shard returned {len(logits)} logits, expected {plan.vocab_size}"
                )
            logits = logits[:plan.vocab_size]

            next_token = sample_token(logits, temperature)
            generated_tokens.append(next_token)

            if next_token == EOS_TOKEN_ID:
                break

            current_ids = [next_token]  # autoregressive: feed one token at a time

    pipeline_ms = int((time.time() - pipeline_start) * 1000)

    return {
        "token_ids": generated_tokens,
        "token_count": len(generated_tokens),
        "pipeline_ms": pipeline_ms,
        "tokens_per_second": round(len(generated_tokens) / max((pipeline_ms / 1000), 0.001), 2),
        "shards_used": plan.total_shards,
        "model": plan.model_name,
        "shard_map": [
            {
                "shard": s.shard_index,
                "device_id": s.device_id,
                "layers": f"{s.layer_start}–{s.layer_end - 1}",
            }
            for s in plan.shards
        ],
    }

# ── Fleet shard status ─────────────────────────────────────────────────────────

async def get_fleet_shard_status(devices: list) -> list[dict]:
    """Poll each device for its current shard readiness."""
    status = []
    async with httpx.AsyncClient(timeout=5) as client:
        for device in devices:
            if not device.device_ip:
                continue
            url = f"http://{device.device_ip}:11434/shard/status"
            try:
                resp = await client.get(url)
                data = resp.json() if resp.is_success else {}
                status.append({
                    "device_id": device.device_id,
                    "device_ip": device.device_ip,
                    "shard_ready": data.get("shard_ready", False),
                    "ram_available_mb": data.get("ram_available_mb", device.ram_available_mb),
                    "reachable": True,
                })
            except Exception:
                status.append({
                    "device_id": device.device_id,
                    "device_ip": device.device_ip,
                    "shard_ready": False,
                    "ram_available_mb": device.ram_available_mb,
                    "reachable": False,
                })
    return status
