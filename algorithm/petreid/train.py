"""训练 PetReID（ResNet-50 + GeM + BNNeck + ArcFace）。

用法（在项目根目录）：
    python algorithm/scripts/train.py --data-root dataset --epochs 40
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import torch
from torch.utils.data import DataLoader

from .contract import EMBEDDING_DIM, MODEL_VERSION, PREPROCESS_SPEC
from .dataset import PetDataset
from .losses import ArcFaceLoss, accuracy_from_logits
from .metadata import group_by_pet, read_metadata, select_rows
from .model import PetReIDModel, set_backbone_trainable
from .preprocess import build_eval_transform, build_train_transform
from .retrieval import rank_metrics
from .sampling import PKBatchSampler


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="训练 PetReID 宠物个体检索模型")
    parser.add_argument("--data-root", type=Path, required=True, help="包含 images/ 与 metadata.jsonl 的目录")
    parser.add_argument("--output-dir", type=Path, default=Path("algorithm/weights"))
    parser.add_argument("--backbone", type=str, default="resnet50")
    parser.add_argument("--embedding-dim", type=int, default=EMBEDDING_DIM)
    parser.add_argument("--dropout", type=float, default=0.3)
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--batch-p", type=int, default=8)
    parser.add_argument("--batch-k", type=int, default=4)
    parser.add_argument("--lr", type=float, default=3e-4)
    parser.add_argument("--weight-decay", type=float, default=5e-4)
    parser.add_argument("--warmup-epochs", type=int, default=3)
    parser.add_argument("--freeze-epochs", type=int, default=2)
    parser.add_argument("--arcface-scale", type=float, default=30.0)
    parser.add_argument("--arcface-margin", type=float, default=0.3)
    parser.add_argument("--num-workers", type=int, default=0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--device", type=str, default="auto", help="auto / cpu / cuda")
    parser.add_argument("--pretrained", dest="pretrained", action="store_true", default=True)
    parser.add_argument("--no-pretrained", dest="pretrained", action="store_false")
    parser.add_argument("--amp", dest="amp", action="store_true", default=True)
    parser.add_argument("--no-amp", dest="amp", action="store_false")
    return parser.parse_args(argv)


def set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def resolve_device(name: str) -> torch.device:
    if name == "auto":
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
    return torch.device(name)


def adjust_lr(optimizer: torch.optim.Optimizer, base_lr: float, step: int, total: int, warmup: int) -> float:
    if warmup > 0 and step < warmup:
        lr = base_lr * float(step + 1) / float(warmup)
    else:
        progress = float(step - warmup) / float(max(1, total - warmup))
        progress = min(1.0, max(0.0, progress))
        lr = base_lr * 0.5 * (1.0 + math.cos(math.pi * progress))
    for group in optimizer.param_groups:
        group["lr"] = lr
    return lr


@torch.no_grad()
def encode_eval_loader(model: PetReIDModel, loader: DataLoader, device: torch.device) -> Tuple[np.ndarray, List[str]]:
    model.eval()
    features: List[np.ndarray] = []
    pet_ids: List[str] = []
    for images, labels in loader:
        images = images.to(device, non_blocking=True)
        embeddings = model(images, normalize=True)
        features.append(embeddings.float().cpu().numpy())
        pet_ids.extend([str(label) for label in labels])
    if not features:
        return np.zeros((0, EMBEDDING_DIM), dtype=np.float32), []
    return np.concatenate(features, axis=0), pet_ids


def evaluate_validation(
    model: PetReIDModel,
    val_rows: List[Dict],
    data_root: Path,
    device: torch.device,
    batch_size: int = 64,
) -> Dict:
    if not val_rows:
        return {}
    dataset = PetDataset(val_rows, data_root, build_eval_transform())
    loader = DataLoader(dataset, batch_size=batch_size, shuffle=False, num_workers=0)
    features, pet_ids = encode_eval_loader(model, loader, device)
    rows = dataset.rows
    image_ids = [row["image_id"] for row in rows]

    pet_to_index: Dict[str, List[int]] = {}
    for index, row in enumerate(rows):
        pet_to_index.setdefault(row["pet_id"], []).append(index)

    query_indices: List[int] = []
    for indices in pet_to_index.values():
        if len(indices) < 2:
            continue
        best_index = min(indices, key=lambda i: image_ids[i])
        query_indices.append(best_index)
    if not query_indices:
        return {"top1": 0.0, "top5": 0.0, "mAP": 0.0, "num_queries": 0}

    metrics = rank_metrics(
        query_features=features[query_indices],
        query_pet_ids=[pet_ids[i] for i in query_indices],
        query_image_ids=[image_ids[i] for i in query_indices],
        gallery_features=features,
        gallery_pet_ids=pet_ids,
        gallery_image_ids=image_ids,
        ks=(1, 5),
    )
    return metrics


def save_inference_checkpoint(
    path: Path,
    model: PetReIDModel,
    args: argparse.Namespace,
    metrics: Dict,
    epoch: int,
) -> None:
    payload = {
        "format": "petreid-inference-v1",
        "model_version": MODEL_VERSION,
        "preprocess": PREPROCESS_SPEC,
        "config": {
            "backbone": args.backbone,
            "embedding_dim": EMBEDDING_DIM,
            "dropout": args.dropout,
        },
        "metrics": metrics,
        "epoch": int(epoch),
        "model_state": {key: value.detach().cpu() for key, value in model.state_dict().items()},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(payload, str(path))


def save_train_state(
    path: Path,
    model: PetReIDModel,
    arcface: ArcFaceLoss,
    optimizer: torch.optim.Optimizer,
    args: argparse.Namespace,
    epoch: int,
    class_to_index: Dict[str, int],
) -> None:
    payload = {
        "format": "petreid-train-state-v1",
        "model_version": MODEL_VERSION,
        "config": {
            "backbone": args.backbone,
            "embedding_dim": EMBEDDING_DIM,
            "dropout": args.dropout,
        },
        "epoch": int(epoch),
        "class_to_index": class_to_index,
        "model_state": model.state_dict(),
        "arcface_state": arcface.state_dict(),
        "optimizer_state": optimizer.state_dict(),
        "args": vars(args),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(payload, str(path))


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    if args.embedding_dim != EMBEDDING_DIM:
        print("embedding_dim 必须为 %d（接口约定），当前为 %d" % (EMBEDDING_DIM, args.embedding_dim))
        return 2

    set_seed(args.seed)
    device = resolve_device(args.device)
    data_root = args.data_root.expanduser().resolve()
    metadata_path = data_root / "metadata.jsonl"
    rows = read_metadata(metadata_path)
    train_rows, missing_train = select_rows(rows, ["train"], data_root)
    val_rows, missing_val = select_rows(rows, ["val"], data_root)
    if missing_train:
        print("警告：train 有 %d 张图片缺失，将跳过" % len(missing_train))
    if missing_val:
        print("警告：val 有 %d 张图片缺失，将跳过" % len(missing_val))
    if len(train_rows) < 2:
        print("train 数据不足（至少需要 2 张）")
        return 2

    pet_ids = sorted({row["pet_id"] for row in train_rows})
    if len(pet_ids) < 2:
        print("train 至少需要 2 个个体（pet_id）")
        return 2
    class_to_index = {pet_id: index for index, pet_id in enumerate(pet_ids)}

    train_dataset = PetDataset(train_rows, data_root, build_train_transform(), class_to_index)
    sampler = PKBatchSampler(
        train_dataset.labels,
        p=args.batch_p,
        k=args.batch_k,
        seed=args.seed,
    )
    train_loader = DataLoader(
        train_dataset,
        batch_sampler=sampler,
        num_workers=args.num_workers,
        pin_memory=(device.type == "cuda"),
    )

    model = PetReIDModel(
        backbone=args.backbone,
        embedding_dim=EMBEDDING_DIM,
        pretrained=args.pretrained,
        dropout=args.dropout,
    ).to(device)
    arcface = ArcFaceLoss(
        num_classes=len(pet_ids),
        embedding_dim=EMBEDDING_DIM,
        scale=args.arcface_scale,
        margin=args.arcface_margin,
    ).to(device)

    optimizer = torch.optim.AdamW(
        list(model.parameters()) + list(arcface.parameters()),
        lr=args.lr,
        weight_decay=args.weight_decay,
    )
    use_amp = bool(args.amp and device.type == "cuda")
    if hasattr(torch, "amp") and hasattr(torch.amp, "GradScaler"):
        scaler = torch.amp.GradScaler("cuda", enabled=use_amp)
    else:
        scaler = torch.cuda.amp.GradScaler(enabled=use_amp)

    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    log_path = output_dir / "train_log.jsonl"
    best_score = (-1.0, -1.0)
    best_epoch = -1
    total_steps = max(1, len(train_loader) * args.epochs)
    warmup_steps = max(0, len(train_loader) * args.warmup_epochs)

    print("设备: %s | 训练个体: %d | 训练图片: %d | batch: %d x %d"
          % (device, len(pet_ids), len(train_dataset), args.batch_p, args.batch_k))
    print("每个 epoch batch 数: %d" % len(train_loader))

    for epoch in range(args.epochs):
        model.train()
        set_backbone_trainable(model, trainable=epoch >= args.freeze_epochs)
        arcface.train()
        sampler.set_epoch(epoch)

        running_loss = 0.0
        running_acc = 0.0
        steps = 0
        start_time = time.time()

        for batch_index, (images, labels) in enumerate(train_loader):
            images = images.to(device, non_blocking=True)
            labels = labels.to(device, non_blocking=True)
            global_step = epoch * len(train_loader) + batch_index
            adjust_lr(optimizer, args.lr, global_step, total_steps, warmup_steps)

            optimizer.zero_grad(set_to_none=True)
            with torch.autocast(device_type="cuda", enabled=use_amp):
                embeddings = model(images)
                logits = arcface.cosine_logits(embeddings)
                loss = arcface(embeddings, labels)
            scaler.scale(loss).backward()
            scaler.step(optimizer)
            scaler.update()

            running_loss += float(loss.detach().item())
            running_acc += accuracy_from_logits(logits.detach(), labels)
            steps += 1

        train_loss = running_loss / max(1, steps)
        train_acc = running_acc / max(1, steps)
        metrics = evaluate_validation(model, val_rows, data_root, device) if val_rows else {}
        elapsed = time.time() - start_time

        record = {
            "epoch": epoch + 1,
            "train_loss": round(train_loss, 5),
            "train_acc": round(train_acc, 5),
            "val": metrics,
            "seconds": round(elapsed, 1),
            "lr": optimizer.param_groups[0]["lr"],
        }
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

        print(
            "epoch %02d/%02d | loss %.4f | acc %.4f | val %s | %.1fs"
            % (
                epoch + 1,
                args.epochs,
                train_loss,
                train_acc,
                json.dumps(metrics, ensure_ascii=False) if metrics else "无 val",
                elapsed,
            )
        )

        save_inference_checkpoint(output_dir / "last.pt", model, args, metrics, epoch + 1)
        if metrics:
            score = (float(metrics.get("top1", 0.0)), float(metrics.get("mAP", 0.0)))
        else:
            score = (0.0, 0.0)
        if score > best_score:
            best_score = score
            best_epoch = epoch + 1
            save_inference_checkpoint(output_dir / "best.pt", model, args, metrics, best_epoch)

    save_train_state(
        output_dir / "train_state.pt",
        model,
        arcface,
        optimizer,
        args,
        args.epochs,
        class_to_index,
    )
    if best_epoch < 0:
        save_inference_checkpoint(output_dir / "best.pt", model, args, {}, args.epochs)
    print("训练完成。best epoch=%s，权重目录: %s" % (best_epoch, output_dir))
    return 0


if __name__ == "__main__":
    sys.exit(main())

