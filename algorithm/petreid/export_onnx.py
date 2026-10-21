"""将训练好的 PetReID 导出为 ONNX（可选交付物）。

ONNX 输入固定为 (N, 3, 224, 224) 的 float32 张量，输出已 L2 归一化的 512 维向量。
默认输出 float32；若下游需要严格对齐接口，可用 --output-dtype float16。
预处理参数同时写入 <onnx>.meta.json。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, Sequence

from .contract import INPUT_SIZE, MODEL_VERSION, PREPROCESS_SPEC


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="导出 PetReID ONNX 模型")
    parser.add_argument("--checkpoint", type=Path, default=None, help=".pt 权重；缺省用 PETREID_CHECKPOINT 或 weights/best.pt")
    parser.add_argument("--output", type=Path, default=Path("algorithm/weights/petreid.onnx"))
    parser.add_argument("--opset", type=int, default=17)
    parser.add_argument("--output-dtype", choices=("float32", "float16"), default="float32")
    parser.add_argument("--verify", action="store_true", help="安装 onnxruntime 后校验导出结果")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    try:
        import torch
        import torch.nn as nn
    except ImportError as exc:
        print("错误: 导出 ONNX 需要 torch：%s" % exc)
        return 2

    from .embedder import PetEmbedder

    try:
        embedder = PetEmbedder(checkpoint_path=args.checkpoint, device="cpu")
    except (FileNotFoundError, ValueError) as exc:
        print("错误: %s" % exc)
        return 2

    output_path = args.output.expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_dtype = torch.float16 if args.output_dtype == "float16" else torch.float32

    class NormalizedExportModel(nn.Module):
        def __init__(self, model: nn.Module, dtype: torch.dtype):
            super().__init__()
            self.model = model
            self.dtype = dtype

        def forward(self, images: torch.Tensor) -> torch.Tensor:
            features = self.model(images, normalize=True)
            if self.dtype == torch.float16:
                features = features.half()
            return features

    wrapper = NormalizedExportModel(embedder.model.eval(), output_dtype).eval()
    dummy = torch.randn(1, 3, INPUT_SIZE, INPUT_SIZE, dtype=torch.float32)
    export_kwargs = dict(
        input_names=["images"],
        output_names=["embedding"],
        opset_version=args.opset,
        do_constant_folding=True,
        dynamic_axes={"images": {0: "batch"}, "embedding": {0: "batch"}},
    )
    try:
        torch.onnx.export(wrapper, dummy, str(output_path), dynamo=False, **export_kwargs)
    except TypeError:
        torch.onnx.export(wrapper, dummy, str(output_path), **export_kwargs)

    meta = {
        "model_version": getattr(embedder, "model_version", MODEL_VERSION),
        "format": "onnx",
        "file": output_path.name,
        "input": {
            "name": "images",
            "shape": ["batch", 3, INPUT_SIZE, INPUT_SIZE],
            "dtype": "float32",
        },
        "output": {
            "name": "embedding",
            "shape": ["batch", 512],
            "dtype": args.output_dtype,
            "l2_normalized": True,
        },
        "opset": args.opset,
        "preprocess": getattr(embedder, "preprocess_spec", PREPROCESS_SPEC),
        "note": "ONNX 输出已归一化；若为 float32，下游按接口约定转 float16 即可。",
    }
    meta_path = output_path.with_suffix(output_path.suffix + ".meta.json")
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print("ONNX 已导出: %s" % output_path)
    print("元信息: %s" % meta_path)

    if args.verify:
        try:
            import numpy as np
            import onnxruntime as ort
        except ImportError:
            print("跳过校验：未安装 onnxruntime（pip install onnxruntime）")
            return 0
        session = ort.InferenceSession(str(output_path), providers=["CPUExecutionProvider"])
        input_name = session.get_inputs()[0].name
        reference = wrapper(dummy).detach().float().cpu().numpy()
        exported = session.run(None, {input_name: dummy.numpy()})[0].astype("float32")
        reference_norm = np.linalg.norm(reference, axis=1)
        exported_norm = np.linalg.norm(exported, axis=1)
        denominator = np.maximum(reference_norm * exported_norm, 1e-12)
        cosine = float(((reference * exported).sum(axis=1) / denominator).mean())
        print("ONNX 校验：与 PyTorch 输出余弦相似度 %.6f" % cosine)
    return 0


if __name__ == "__main__":
    sys.exit(main())
