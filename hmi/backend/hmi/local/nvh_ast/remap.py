"""Remap HuggingFace AST state_dict keys to YuanGongND ASTModel / timm DeiT keys."""

from __future__ import annotations

from typing import Any

_HF_PREFIX = "audio_spectrogram_transformer."

_SIMPLE = {
    f"{_HF_PREFIX}embeddings.cls_token": "v.cls_token",
    f"{_HF_PREFIX}embeddings.distillation_token": "v.dist_token",
    f"{_HF_PREFIX}embeddings.position_embeddings": "v.pos_embed",
    f"{_HF_PREFIX}embeddings.patch_embeddings.projection.weight": "v.patch_embed.proj.weight",
    f"{_HF_PREFIX}embeddings.patch_embeddings.projection.bias": "v.patch_embed.proj.bias",
    f"{_HF_PREFIX}layernorm.weight": "v.norm.weight",
    f"{_HF_PREFIX}layernorm.bias": "v.norm.bias",
    "classifier.layernorm.weight": "mlp_head.0.weight",
    "classifier.layernorm.bias": "mlp_head.0.bias",
    "classifier.dense.weight": "mlp_head.1.weight",
    "classifier.dense.bias": "mlp_head.1.bias",
}

_LAYER_SUFFIX = {
    "attention.output.dense.weight": "attn.proj.weight",
    "attention.output.dense.bias": "attn.proj.bias",
    "intermediate.dense.weight": "mlp.fc1.weight",
    "intermediate.dense.bias": "mlp.fc1.bias",
    "output.dense.weight": "mlp.fc2.weight",
    "output.dense.bias": "mlp.fc2.bias",
    "layernorm_before.weight": "norm1.weight",
    "layernorm_before.bias": "norm1.bias",
    "layernorm_after.weight": "norm2.weight",
    "layernorm_after.bias": "norm2.bias",
}

_QKV_PARTS = ("query", "key", "value")


def remap_hf_to_ast(state: dict[str, Any]) -> dict[str, Any]:
    """Convert HF AST keys to Gong ``v.*`` / ``mlp_head.*`` keys.

    Separate q/k/v weights are concatenated on dim 0 into fused ``attn.qkv``.
    """
    out: dict[str, Any] = {}
    qkv_w: dict[int, dict[str, Any]] = {}
    qkv_b: dict[int, dict[str, Any]] = {}
    layer_prefix = f"{_HF_PREFIX}encoder.layer."

    for key, tensor in state.items():
        if key in _SIMPLE:
            out[_SIMPLE[key]] = tensor
            continue
        if not key.startswith(layer_prefix):
            continue
        rest = key[len(layer_prefix) :]
        layer_s, _, tail = rest.partition(".")
        try:
            layer_i = int(layer_s)
        except ValueError:
            continue
        attn_qkv = "attention.attention."
        if tail.startswith(attn_qkv):
            qkv_tail = tail[len(attn_qkv) :]
            part, _, wb = qkv_tail.partition(".")
            if part not in _QKV_PARTS:
                continue
            bucket = qkv_w if wb == "weight" else qkv_b if wb == "bias" else None
            if bucket is None:
                continue
            bucket.setdefault(layer_i, {})[part] = tensor
            continue
        mapped_suffix = _LAYER_SUFFIX.get(tail)
        if mapped_suffix:
            out[f"v.blocks.{layer_i}.{mapped_suffix}"] = tensor

    def _cat(parts: dict[str, Any]) -> Any:
        import torch

        return torch.cat([parts["query"], parts["key"], parts["value"]], dim=0)

    for layer_i, parts in qkv_w.items():
        if set(parts) == set(_QKV_PARTS):
            out[f"v.blocks.{layer_i}.attn.qkv.weight"] = _cat(parts)
    for layer_i, parts in qkv_b.items():
        if set(parts) == set(_QKV_PARTS):
            out[f"v.blocks.{layer_i}.attn.qkv.bias"] = _cat(parts)
    return out
