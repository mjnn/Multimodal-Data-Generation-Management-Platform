"""Gong-style AST (DeiT-B distilled, fstride=tstride=10) for AudioSet-527 inference.

Architecture and forward match YuanGongND/ast ``ASTModel`` (cls+dist average → mlp_head).
No timm / no Dropbox download; weights come from remapped HuggingFace ``pytorch_model.bin``.
"""

from __future__ import annotations

import os
from pathlib import Path

import torch
import torch.nn as nn

REPO = Path(__file__).resolve().parents[5]
DEFAULT_WEIGHTS = REPO / "hmi" / "data" / "models" / "ast" / "pytorch_model.bin"
ENV_WEIGHTS = "HMI_NVH_AST_WEIGHTS"

EMBED_DIM = 768
NUM_HEADS = 12
DEPTH = 12
MLP_RATIO = 4
NUM_LABELS = 527
PATCH = 16
FSTRIDE = 10
TSTRIDE = 10
INPUT_FDIM = 128
INPUT_TDIM = 1024


class PatchEmbed(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.proj = nn.Conv2d(1, EMBED_DIM, kernel_size=(PATCH, PATCH), stride=(FSTRIDE, TSTRIDE))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.proj(x).flatten(2).transpose(1, 2)
        return x


class Attention(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.num_heads = NUM_HEADS
        head_dim = EMBED_DIM // NUM_HEADS
        self.scale = head_dim ** -0.5
        self.qkv = nn.Linear(EMBED_DIM, EMBED_DIM * 3, bias=True)
        self.proj = nn.Linear(EMBED_DIM, EMBED_DIM)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        b, n, c = x.shape
        qkv = self.qkv(x).reshape(b, n, 3, self.num_heads, c // self.num_heads).permute(2, 0, 3, 1, 4)
        q, k, v = qkv[0], qkv[1], qkv[2]
        attn = (q @ k.transpose(-2, -1)) * self.scale
        attn = attn.softmax(dim=-1)
        x = (attn @ v).transpose(1, 2).reshape(b, n, c)
        return self.proj(x)


class Mlp(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        hidden = int(EMBED_DIM * MLP_RATIO)
        self.fc1 = nn.Linear(EMBED_DIM, hidden)
        self.act = nn.GELU()
        self.fc2 = nn.Linear(hidden, EMBED_DIM)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.fc2(self.act(self.fc1(x)))


class Block(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.norm1 = nn.LayerNorm(EMBED_DIM)
        self.attn = Attention()
        self.norm2 = nn.LayerNorm(EMBED_DIM)
        self.mlp = Mlp()

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = x + self.attn(self.norm1(x))
        x = x + self.mlp(self.norm2(x))
        return x


class _Vision(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        f_dim = (INPUT_FDIM - PATCH) // FSTRIDE + 1
        t_dim = (INPUT_TDIM - PATCH) // TSTRIDE + 1
        num_patches = f_dim * t_dim
        self.cls_token = nn.Parameter(torch.zeros(1, 1, EMBED_DIM))
        self.dist_token = nn.Parameter(torch.zeros(1, 1, EMBED_DIM))
        self.pos_embed = nn.Parameter(torch.zeros(1, num_patches + 2, EMBED_DIM))
        self.patch_embed = PatchEmbed()
        self.blocks = nn.ModuleList([Block() for _ in range(DEPTH)])
        self.norm = nn.LayerNorm(EMBED_DIM)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.patch_embed(x)
        b = x.shape[0]
        cls_tokens = self.cls_token.expand(b, -1, -1)
        dist_token = self.dist_token.expand(b, -1, -1)
        x = torch.cat((cls_tokens, dist_token, x), dim=1)
        x = x + self.pos_embed
        for blk in self.blocks:
            x = blk(x)
        x = self.norm(x)
        return (x[:, 0] + x[:, 1]) / 2


class ASTModel(nn.Module):
    """Minimal Gong ASTModel: input (B, 1024, 128) → logits (B, 527)."""

    def __init__(self) -> None:
        super().__init__()
        self.v = _Vision()
        self.mlp_head = nn.Sequential(nn.LayerNorm(EMBED_DIM), nn.Linear(EMBED_DIM, NUM_LABELS))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # Gong: (B, time, freq) → (B, 1, freq, time)
        x = x.unsqueeze(1).transpose(2, 3)
        x = self.v(x)
        return self.mlp_head(x)


def resolve_weights_path() -> Path | None:
    env = (os.getenv(ENV_WEIGHTS) or "").strip()
    path = Path(env) if env else DEFAULT_WEIGHTS
    return path if path.is_file() else None


_MODEL: ASTModel | None = None


def load_ast_model(weights: Path | None = None) -> ASTModel:
    global _MODEL
    path = weights or resolve_weights_path()
    if path is None:
        raise FileNotFoundError("AST weights not found; set HMI_NVH_AST_WEIGHTS")
    if _MODEL is not None and weights is None:
        return _MODEL
    from hmi.local.nvh_ast.remap import remap_hf_to_ast

    raw = torch.load(str(path), map_location="cpu", weights_only=False)
    if not isinstance(raw, dict):
        raise TypeError(f"unexpected checkpoint type {type(raw)}")
    sd = remap_hf_to_ast(raw)
    model = ASTModel()
    missing, unexpected = model.load_state_dict(sd, strict=True)
    del missing, unexpected
    model.eval()
    if weights is None:
        _MODEL = model
    return model
