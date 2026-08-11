"""Development-only conversion of local MiniLM weights to CPU ONNX."""

from __future__ import annotations

import argparse
from pathlib import Path

import torch
from transformers import AutoModel, AutoTokenizer


class Encoder(torch.nn.Module):
    def __init__(self, model: torch.nn.Module) -> None:
        super().__init__()
        self.model = model

    def forward(self, input_ids, attention_mask, token_type_ids):
        return self.model(
            input_ids=input_ids,
            attention_mask=attention_mask,
            token_type_ids=token_type_ids,
            return_dict=False,
        )[0]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("model_dir", type=Path)
    args = parser.parse_args()
    model_dir = args.model_dir.resolve()
    tokenizer = AutoTokenizer.from_pretrained(model_dir, local_files_only=True)
    model = AutoModel.from_pretrained(model_dir, local_files_only=True).eval()
    sample = tokenizer("Clippy local embedding export", return_tensors="pt")
    output = model_dir / "model.onnx"
    torch.onnx.export(
        Encoder(model),
        (sample["input_ids"], sample["attention_mask"], sample["token_type_ids"]),
        output,
        input_names=["input_ids", "attention_mask", "token_type_ids"],
        output_names=["token_embeddings"],
        dynamic_axes={
            "input_ids": {0: "batch", 1: "sequence"},
            "attention_mask": {0: "batch", 1: "sequence"},
            "token_type_ids": {0: "batch", 1: "sequence"},
            "token_embeddings": {0: "batch", 1: "sequence"},
        },
        opset_version=17,
        do_constant_folding=True,
    )
    print(output)


if __name__ == "__main__":
    main()
