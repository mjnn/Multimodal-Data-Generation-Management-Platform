"""CLI 入口：oms-multimodal 命令。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from dotenv import load_dotenv

from .acoustic_panel import AcousticPanelConfig
from .asr_client import AsrConfig
from .clip_video import ClipVideoConfig
from .client import OmsMultimodalClient
from .resources import resolve_taxonomy_path
from .config import ClipConfig, OutputConfig


def build_acoustic_panel_config(args: argparse.Namespace) -> AcousticPanelConfig:
    config = AcousticPanelConfig.from_env()
    if args.acoustic_panel_type is not None:
        config.panel_type = args.acoustic_panel_type
    if args.acoustic_n_fft is not None:
        config.n_fft = args.acoustic_n_fft
    if args.acoustic_hop_length is not None:
        config.hop_length = args.acoustic_hop_length
    if args.acoustic_n_mels is not None:
        config.n_mels = args.acoustic_n_mels
    if args.acoustic_fmin is not None:
        config.fmin = args.acoustic_fmin
    if args.acoustic_fmax is not None:
        config.fmax = args.acoustic_fmax
    if args.acoustic_panel_width is not None:
        config.target_width = args.acoustic_panel_width
    if args.acoustic_panel_height is not None:
        config.target_height = args.acoustic_panel_height
    return config


def build_asr_config(args: argparse.Namespace) -> AsrConfig:
    config = AsrConfig.from_env()
    if getattr(args, "no_asr", False):
        config.enabled = False
    if getattr(args, "asr_model", None) is not None:
        config.model = args.asr_model
    return config


def build_clip_video_config(args: argparse.Namespace) -> ClipVideoConfig:
    config = ClipVideoConfig.from_env()
    if getattr(args, "no_clip_video", False):
        config.enabled = False
    return config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Rosbag multimodal embedding + OMS labeling pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    inspect_parser = sub.add_parser("inspect", help="Inspect topics in a rosbag")
    inspect_parser.add_argument("--bag", type=Path, required=True)

    run_parser = sub.add_parser("run", help="Run embedding + labeling pipeline")
    run_parser.add_argument("--bag", type=Path, help="Path to a single .bag file")
    run_parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("rosbag/manifest.json"),
        help="Manifest json with bag paths",
    )
    run_parser.add_argument(
        "--taxonomy",
        type=Path,
        default=Path("oms_label_taxonomy.yaml"),
        help="OMS label taxonomy yaml",
    )
    run_parser.add_argument("--work-dir", type=Path, default=Path("output/work"))
    run_parser.add_argument("--embeddings-out", type=Path, default=Path("output/fusion_embeddings.jsonl"))
    run_parser.add_argument("--labels-out", type=Path, default=Path("output/labels.jsonl"))
    run_parser.add_argument("--videos-out", type=Path, default=Path("output/clip_videos.jsonl"))
    run_parser.add_argument("--clip-min-sec", type=float, default=15.0, help="Minimum clip length in seconds")
    run_parser.add_argument("--clip-max-sec", type=float, default=20.0, help="Maximum clip length in seconds")
    run_parser.add_argument(
        "--sample-fps",
        type=float,
        default=1.0,
        help="Sample frames per camera per second within each clip (for Omni video sequence)",
    )
    run_parser.add_argument("--max-clips", type=int, default=None)
    run_parser.add_argument("--clips-out", type=Path, default=Path("output/clips.jsonl"))
    run_parser.add_argument(
        "--extract-only",
        action="store_true",
        help="Only extract and align rosbag clips without calling cloud models",
    )
    run_parser.add_argument(
        "--acoustic-panel-type",
        choices=("stft", "mel"),
        default=None,
        help="Acoustic panel spectrogram type (default: env ACOUSTIC_PANEL_TYPE or mel)",
    )
    run_parser.add_argument("--acoustic-n-fft", type=int, default=None)
    run_parser.add_argument("--acoustic-hop-length", type=int, default=None)
    run_parser.add_argument("--acoustic-n-mels", type=int, default=None)
    run_parser.add_argument("--acoustic-fmin", type=float, default=None)
    run_parser.add_argument("--acoustic-fmax", type=float, default=None)
    run_parser.add_argument("--acoustic-panel-width", type=int, default=None)
    run_parser.add_argument("--acoustic-panel-height", type=int, default=None)
    run_parser.add_argument(
        "--no-asr",
        action="store_true",
        help="Disable ASR transcript before labeling/embedding",
    )
    run_parser.add_argument(
        "--asr-model",
        type=str,
        default=None,
        help="ASR model (default: env ASR_MODEL or qwen3-asr-flash)",
    )
    run_parser.add_argument(
        "--no-clip-video",
        action="store_true",
        help="Disable clip preview MP4 (frames + WAV)",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "inspect":
        client = OmsMultimodalClient(load_dotenv=False)
        topics = client.inspect_bag(args.bag)
        print(json.dumps([t.__dict__ for t in topics], ensure_ascii=False, indent=2))
        return

    bags: list[Path] = []
    if args.bag:
        bags = [args.bag]
    elif args.manifest.exists():
        bags = OmsMultimodalClient.resolve_bags(args.manifest)

    if not bags:
        raise SystemExit("No bag files found. Provide --bag or a valid manifest with existing bag paths.")

    acoustic_panel_config = build_acoustic_panel_config(args)
    asr_config = build_asr_config(args)
    clip_video_config = build_clip_video_config(args)
    client = OmsMultimodalClient(
        taxonomy_path=resolve_taxonomy_path(args.taxonomy),
        work_dir=args.work_dir,
        acoustic_panel_config=acoustic_panel_config,
        asr_config=asr_config,
        clip_video_config=clip_video_config,
        load_dotenv=False,
    )
    clip_config = ClipConfig(
        min_sec=args.clip_min_sec,
        max_sec=args.clip_max_sec,
        sample_fps=args.sample_fps,
        max_clips=args.max_clips,
    )

    for bag in bags:
        if len(bags) > 1:
            output = OutputConfig(
                embeddings_out=args.embeddings_out.with_name(f"{bag.stem}_{args.embeddings_out.name}"),
                labels_out=args.labels_out.with_name(f"{bag.stem}_{args.labels_out.name}"),
                clips_out=args.clips_out.with_name(f"{bag.stem}_{args.clips_out.name}"),
                videos_out=args.videos_out.with_name(f"{bag.stem}_{args.videos_out.name}"),
            )
        else:
            output = OutputConfig(
                embeddings_out=args.embeddings_out,
                labels_out=args.labels_out,
                clips_out=args.clips_out,
                videos_out=args.videos_out,
            )

        if args.extract_only:
            summary = client.extract_bag(bag, clip_config=clip_config, output=output)
        else:
            summary = client.process_bag(bag, clip_config=clip_config, output=output)
        print(json.dumps(summary.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
